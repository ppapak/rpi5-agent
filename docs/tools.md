# Optional Tools

With `FEATURE_TOOLS=1`, the assistant can act rather than only answer. The
system prompt gains a tool block, and the streaming loop watches for a bracketed
call:

```
[WRITE: name.md | content]
[EMAIL: subject | body]
```

When one appears the stream is cut short, the tool runs, and its result is fed
back as an observation for a second pass. Nothing is spoken while a partial tool
call is in the buffer, so you never hear the assistant read out its own syntax.

Both tools are local. The assistant makes no outbound network calls of its own —
the only traffic it generates is SMTP, and only when you ask it to send mail.

This is a Pi 5 feature. It is off by default on the Pi 4, where the 0.5B model
is not reliable enough at emitting well-formed calls.

## The tools

| Tool | Backed by | Notes |
| :--- | :--- | :--- |
| `WRITE` | `$BASE_DIR/workspace/` | Confined to the workspace; `history.md` is protected. With RAG on, whatever it writes is indexed within seconds and becomes answerable. |
| `EMAIL` | SMTP | Sends to the fixed `RECEIVER_EMAIL`; the model is never given an address to choose. |

`WRITE` resolves the path and rejects anything that escapes the workspace, so a
model that emits `../../etc/passwd` gets an "Access Denied" observation rather
than a write.

## Enabling

In `$BASE_DIR/.env`:

```ini
FEATURE_TOOLS=1
```

`EMAIL` additionally needs SMTP credentials:

```ini
SMTP_SERVER=smtp.gmail.com
SMTP_PORT=587
SENDER_EMAIL=you@example.com
SENDER_PASSWORD=your-app-specific-password
RECEIVER_EMAIL=you@example.com
```

Use an app-specific password, never your account password — `.env` stores it in
plaintext. Keep the file at mode `600`, and remember it is *not* removed by
anything except `uninstall.sh`. With `SMTP_SERVER` unset, `EMAIL` returns
"Error: SMTP is not configured" instead of failing at the socket.

Restart to apply:

```bash
sudo systemctl restart voice-assistant
```

## Trying it

> *"Agent, write a note called groceries dot md with milk and bread."*
> *"Agent, email me a summary of that."*

Tool activity is logged as `[OBSERVATION: ...]` in
`journalctl -u voice-assistant -f`, which is the first place to look when a tool
appears to do nothing.

## Adding a tool

1. Write the function in [`src/native_ai/tools.py`](../src/native_ai/tools.py).
   Return a short string — it goes back to the model as an observation, and a
   long one crowds out the context.
2. Add its verb to `TOOL_PATTERN` and to `dispatch()`.
3. Document the syntax in `TOOLS_BLOCK` in
   [`src/native_ai/prompts.py`](../src/native_ai/prompts.py); that block is what
   the model actually sees.

Keep the count low. Every tool listed costs context on every single turn,
whether or not it is used.
