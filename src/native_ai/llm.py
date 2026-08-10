"""
The llama.cpp streaming loop.

Tokens are printed as they arrive and cut into sentences on the fly, so Piper
starts speaking the first clause while the model is still writing the rest.
"""
import datetime
import json

import requests

from . import audio, config, prompts, tools
from .memory import get_memory

HTTP_SESSION = requests.Session()

# Chunk on clause boundaries, not just sentence ends: shorter chunks reach the
# speaker sooner.
_BREAK_CHARS = ".!?\n,:;"


def wait_for_server(timeout=1):
    """Block until llama-server answers its health endpoint."""
    import time

    while True:
        try:
            if requests.get(config.HEALTH_URL, timeout=timeout).status_code == 200:
                return
        except Exception:
            time.sleep(1)


def _timestamp():
    now = datetime.datetime.now()
    return f"Date: {now.strftime('%A, %B %d, %Y')}. Time: {now.strftime('%H:%M')}."


def _build_prompt(template, user_prompt, sensor_context):
    memory = get_memory()
    history = template.format_history(memory.get_recent_turns(template.history_turns))
    knowledge = memory.query_knowledge(user_prompt) if template.uses_knowledge else ""
    return template.render(user_prompt, history, knowledge, _timestamp(), sensor_context)


def stream_think(user_prompt, sensor_context=""):
    """
    Answer `user_prompt`, speaking as it goes.

    With FEATURE_TOOLS on, a bracketed tool call cuts the stream short; the tool
    runs and its observation is fed back for a second pass.
    """
    template = prompts.get_template()
    memory = get_memory()
    active_prompt = user_prompt

    while True:
        payload = {
            "prompt": _build_prompt(template, active_prompt, sensor_context),
            "stream": True,
            "cache_prompt": True,
            "n_predict": config.N_PREDICT,
            "stop": template.stop(),
        }

        full_text, sentence = [], []
        is_thinking = False
        tool_triggered = None

        try:
            with HTTP_SESSION.post(config.LLAMA_API_URL, json=payload, stream=True) as r:
                for line in r.iter_lines():
                    if not line:
                        continue
                    try:
                        data = json.loads(line.decode("utf-8")[6:])
                        token = data.get("content", "")
                    except Exception:
                        continue

                    # Swallow chain-of-thought some models emit before the answer.
                    if any(x in token.lower() for x in ["thought", "<|"]):
                        is_thinking = True
                        continue
                    if is_thinking and (">" in token or "\n" in token):
                        is_thinking = False
                        continue
                    if is_thinking:
                        continue

                    print(token, end="", flush=True)
                    full_text.append(token)
                    sentence.append(token)

                    if config.FEATURE_TOOLS:
                        match = tools.TOOL_PATTERN.search("".join(full_text))
                        if match:
                            tool_triggered = (match.group(1), match.group(2))
                            sentence.clear()
                            break

                    buffer = "".join(sentence)
                    # Never speak a half-written tool call.
                    if config.FEATURE_TOOLS and "[" in buffer:
                        continue
                    if any(c in token for c in _BREAK_CHARS):
                        chunk = buffer.strip()
                        if len(chunk) > 1:
                            audio.speak(chunk)
                        sentence.clear()

            print("\n", flush=True)

            if tool_triggered:
                observation = tools.dispatch(*tool_triggered)
                print(f"[OBSERVATION: {observation}]", flush=True)
                active_prompt = f"Observation: {observation}\nAction: Now provide the final response."
                continue

            if sentence:
                final_chunk = "".join(sentence).strip()
                if final_chunk and "[" not in final_chunk:
                    audio.speak(final_chunk)
            memory.save(user_prompt, "".join(full_text).strip())
            return

        except Exception as e:
            print(f"LLM Connection Error: {e}", flush=True)
            return
