"""
Prompt templates, one per chat format.

Each board's model wants its own turn markers and stop sequences, and that is
the only reason the two assistants used to be separate files. Keep the rendered
strings byte-identical to what the model was tuned on — drift here degrades
answers silently instead of raising.
"""
from . import config

TOOLS_BLOCK = (
    "Tools:\n"
    "- [WRITE: name.md | content]\n"
    "- [EMAIL: subject | body] Do not ask for my email address. The tool has it.\n"
    "MANDATORY: Speak response fully, then use tools at the end.\n"
)


class PromptTemplate:
    name = ""
    # How many past turns to feed back in.
    history_turns = 3
    # Whether the rendered prompt has a slot for retrieved knowledge.
    uses_knowledge = True
    base_stop = []

    def stop(self):
        stop = list(self.base_stop)
        if config.FEATURE_TOOLS:
            stop.append("Observation:")
        return stop

    def format_history(self, turns):
        raise NotImplementedError

    def system_prompt(self, timestamp, sensor_context=""):
        raise NotImplementedError

    def render(self, user_prompt, history, knowledge, timestamp, sensor_context=""):
        raise NotImplementedError


class GemmaTemplate(PromptTemplate):
    """Gemma's <start_of_turn> format. Pi 5."""

    name = "gemma"
    history_turns = 3
    uses_knowledge = True
    base_stop = ["<end_of_turn>", "USER QUERY:", "RECENT HISTORY:"]

    def format_history(self, turns):
        return "\n\n".join(turns)

    def system_prompt(self, timestamp, sensor_context=""):
        prompt = (
            f"You are {config.AGENT_NAME}, a voice assistant. Be very polite. No fluff. "
            f"Short sentences. {timestamp}\n"
            "Ignore homophones; input is verbal dictation.\n"
            "Priority: Last Response > Knowledge Base."
        )
        if config.FEATURE_TOOLS:
            prompt += "\n" + TOOLS_BLOCK
        if sensor_context:
            prompt += f"\nCURRENT SENSOR DATA: {sensor_context}"
        return prompt

    def render(self, user_prompt, history, knowledge, timestamp, sensor_context=""):
        return (
            f"<start_of_turn>system\n{self.system_prompt(timestamp, sensor_context)}<end_of_turn>\n"
            f"<start_of_turn>user\n"
            f"RECENT HISTORY:\n{history}\n\n"
            f"KNOWLEDGE:\n{knowledge}\n\n"
            f"USER QUERY: {user_prompt}<end_of_turn>\n"
            f"<start_of_turn>model\n"
        )


class ChatMLTemplate(PromptTemplate):
    """ChatML <|im_start|> format, as used by Qwen. Pi 4."""

    name = "chatml"
    history_turns = 1
    uses_knowledge = False
    base_stop = ["<|im_end|>", "<|im_start|>", "U:", "A:", "user:"]

    def format_history(self, turns):
        """Replay the last turn as a real assistant/user exchange."""
        if not turns:
            return ""
        lines = turns[-1].split("\n")
        if len(lines) < 2:
            return ""
        u_text = lines[0][3:] if lines[0].startswith("U: ") else lines[0]
        a_text = lines[1][3:] if lines[1].startswith("A: ") else lines[1]
        return (
            f"<|im_start|>user\n{u_text}<|im_end|>\n"
            f"<|im_start|>assistant\n{a_text}<|im_end|>\n"
        )

    def system_prompt(self, timestamp, sensor_context=""):
        prompt = (
            f"You are {config.AGENT_NAME}, a hardware integrated polite voice assistant. "
            f"You possess a camera and run on a 7 volt battery. "
            f"Constraint 1: Never say As an AI or deny having physical sensors. "
            f"Constraint 2: Responses MUST be short, maximum 1 or 2 sentences. "
            f"Zero conversational filler. "
            f"{timestamp}"
        )
        if config.FEATURE_TOOLS:
            prompt += "\n" + TOOLS_BLOCK
        if sensor_context:
            prompt += f"\nCURRENT SENSOR DATA: {sensor_context}"
        return prompt

    def render(self, user_prompt, history, knowledge, timestamp, sensor_context=""):
        return (
            f"<|im_start|>system\n{self.system_prompt(timestamp, sensor_context)}<|im_end|>\n"
            f"{history}"
            f"<|im_start|>user\n{user_prompt}<|im_end|>\n"
            f"<|im_start|>assistant\n"
        )


TEMPLATES = {
    GemmaTemplate.name: GemmaTemplate(),
    ChatMLTemplate.name: ChatMLTemplate(),
}


def get_template(name=None):
    name = name or config.PROMPT_FORMAT
    if name not in TEMPLATES:
        raise ValueError(
            f"Unknown PROMPT_FORMAT {name!r}. Known formats: {', '.join(sorted(TEMPLATES))}"
        )
    return TEMPLATES[name]
