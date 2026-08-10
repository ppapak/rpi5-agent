# Optional Tools: Web Search and Email

With `FEATURE_TOOLS=1`, the assistant can act rather than only answer. The
system prompt gains a tool block, and the streaming loop watches for a bracketed
call:

```
[SEARCH: query]
[WRITE: name.md | content]
[EMAIL: subject | body]
```

When one appears the stream is cut short, the tool runs, and its result is fed
back as an observation for a second pass. Nothing is spoken while a partial tool
call is in the buffer, so you never hear the assistant read out its own syntax.

This is a Pi 5 feature. It is off by default on the Pi 4, where the 0.5B model
is not reliable enough at emitting well-formed calls.

## The tools

| Tool | Backed by | Notes |
| :--- | :--- | :--- |
| `SEARCH` | A local SearXNG instance | Returns the top 3 results, truncated to 1000 characters. |
| `WRITE` | `$BASE_DIR/workspace/` | Confined to the workspace; `history.md` is protected. With RAG on, whatever it writes is indexed within seconds and becomes answerable. |
| `EMAIL` | SMTP | Sends to the fixed `RECEIVER_EMAIL`; the model is never given an address to choose. |

`WRITE` resolves the path and rejects anything that escapes the workspace, so a
model that emits `../../etc/passwd` gets an "Access Denied" observation rather
than a write.

## Web search

Search runs through a local [SearXNG](https://github.com/searxng/searxng) in
Docker — a metasearch proxy, so no query carries your identity, and the
assistant only ever talks to `localhost`.

```bash
./scripts/install-searxng.sh
```

It installs Docker if missing, generates a persistent secret, enables the JSON
API, and runs the container on port `8081` with `--cap-drop ALL`. Verify:

```bash
curl "http://localhost:8081/search?q=test&format=json" | head -c 200
```

Then, in `$BASE_DIR/.env`:

```ini
FEATURE_TOOLS=1
SEARXNG_URL=http://localhost:8081/
```

Search is off by default because it is the one part of the system that reaches
the public internet. Everything else runs offline; enabling this trades some of
that for current information.

## Email

Add SMTP credentials to `$BASE_DIR/.env`:

```ini
SMTP_SERVER=smtp.gmail.com
SMTP_PORT=587
SENDER_EMAIL=you@example.com
SENDER_PASSWORD=your-app-specific-password
RECEIVER_EMAIL=you@example.com
```

Use an app-specific password, never your account password — `.env` stores it in
plaintext. Keep the file at mode `600`, and remember it is *not* removed by
anything except `uninstall.sh`.

Restart to apply:

```bash
sudo systemctl restart voice-assistant
```

## Trying it

> *"Agent, search for today's weather in Athens."*
> *"Agent, write a note called groceries dot md with milk and bread."*
> *"Agent, email me a summary of that."*

Tool activity is logged as `[OBSERVATION: ...]` in
`journalctl -u voice-assistant -f`, which is the first place to look when a tool
appears to do nothing.
