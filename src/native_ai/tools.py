"""
Optional tool calls, enabled by FEATURE_TOOLS.

The model emits a bracketed call ([WRITE: name | body], [EMAIL: subject | body]);
llm.py detects it mid-stream, runs the tool here, and feeds the result back as an
observation.

Every tool here is local. The assistant makes no outbound network calls.
"""
import os
import re
import smtplib
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from pathlib import Path

from . import config

TOOL_PATTERN = re.compile(r"\[(WRITE|EMAIL):\s*(.*?)\]", re.DOTALL)


def write_file(filename, content):
    """Write inside the workspace only — the model does not get the filesystem."""
    try:
        filename = filename.strip()
        if filename.lower() == "history.md":
            return "Error: history.md is a protected system log."
        path = (Path(config.WORKSPACE_DIR) / filename).resolve()
        if not str(path).startswith(os.path.abspath(config.WORKSPACE_DIR)):
            return "Access Denied: Path outside workspace."
        if not content:
            return "Error: No content provided."
        path.write_text(content.strip(), encoding="utf-8")
        return f"File {filename} successfully updated."
    except Exception as e:
        return f"Write Error: {e}"


def send_email(subject, body):
    """Send through the SMTP account configured in .env."""
    try:
        if not body or len(body.strip()) < 5:
            return "Error: Email body too short."
        if not config.SMTP_SERVER or not config.SENDER_EMAIL:
            return "Error: SMTP is not configured."
        msg = MIMEMultipart()
        msg["From"] = config.SENDER_EMAIL
        msg["To"] = config.RECEIVER_EMAIL
        msg["Subject"] = subject
        msg.attach(MIMEText(body, "plain"))
        server = smtplib.SMTP(config.SMTP_SERVER, config.SMTP_PORT)
        server.starttls()
        server.login(config.SENDER_EMAIL, config.SENDER_PASSWORD)
        server.send_message(msg)
        server.quit()
        return "Email sent successfully."
    except Exception as e:
        return f"Email Error: {e}"


def dispatch(tool_type, argument):
    """Run one parsed tool call and return the observation string."""
    if tool_type == "SEARCH":
        return web_search(argument)
    if tool_type == "WRITE" and "|" in argument:
        name, content = argument.split("|", 1)
        return write_file(name.strip(), content.strip())
    if tool_type == "EMAIL" and "|" in argument:
        subject, body = argument.split("|", 1)
        return send_email(subject.strip(), body.strip())
    return "Error: Invalid tool format."
