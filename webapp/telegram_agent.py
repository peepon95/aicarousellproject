"""Telegram control plane for the carousel agent.

Webhook requests stay fast: approvals and free-form topics dispatch a durable
GitHub Actions worker, while the lightweight daily suggestion is sent directly.
"""

from __future__ import annotations

import datetime
import hmac
import json
import mimetypes
import os
import re
import urllib.error
import urllib.request
import uuid
from pathlib import Path

from . import pipeline as P


SOURCE_TO_CODE = {
    "youtube_video": "y",
    "substack_article": "s",
    "github_repo": "g",
    "tool_website": "t",
    "mixed_sources": "m",
}
CODE_TO_SOURCE = {value: key for key, value in SOURCE_TO_CODE.items()}
FALLBACK_TOPICS = (
    ("video essays for when you feel sad", "youtube_video"),
    ("video essays for rebuilding after a breakup", "youtube_video"),
    ("Substack articles instead of doomscrolling", "substack_article"),
    ("AI tools that give you your evening back", "tool_website"),
    ("GitHub AI projects worth running locally", "github_repo"),
)


def telegram_configured() -> bool:
    return bool(os.environ.get("TELEGRAM_BOT_TOKEN", "").strip())


def _telegram_api(method: str, payload: dict | None = None) -> dict:
    token = os.environ.get("TELEGRAM_BOT_TOKEN", "").strip()
    if not token:
        raise RuntimeError("Add TELEGRAM_BOT_TOKEN before starting the Telegram agent")
    request = urllib.request.Request(
        f"https://api.telegram.org/bot{token}/{method}",
        data=json.dumps(payload or {}).encode(),
        headers={"Content-Type": "application/json"},
    )
    try:
        with urllib.request.urlopen(request, timeout=45) as response:
            result = json.load(response)
    except urllib.error.HTTPError as exc:
        detail = exc.read(700).decode("utf-8", "replace")
        raise RuntimeError(
            f"Telegram {method} failed (HTTP {exc.code}): {detail or exc.reason}"
        ) from exc
    if not result.get("ok"):
        raise RuntimeError(f"Telegram {method} failed: {result.get('description', result)}")
    return result.get("result", {})


def _multipart_api(method: str, fields: dict, field_name: str, path: str) -> dict:
    token = os.environ.get("TELEGRAM_BOT_TOKEN", "").strip()
    if not token:
        raise RuntimeError("Add TELEGRAM_BOT_TOKEN before sending carousel files")
    boundary = f"----carousel-{uuid.uuid4().hex}"
    body = bytearray()
    for name, value in fields.items():
        body.extend(f"--{boundary}\r\n".encode())
        body.extend(f'Content-Disposition: form-data; name="{name}"\r\n\r\n'.encode())
        body.extend(str(value).encode())
        body.extend(b"\r\n")
    source = Path(path)
    content_type = mimetypes.guess_type(source.name)[0] or "application/octet-stream"
    body.extend(f"--{boundary}\r\n".encode())
    body.extend(
        f'Content-Disposition: form-data; name="{field_name}"; '
        f'filename="{source.name}"\r\n'.encode()
    )
    body.extend(f"Content-Type: {content_type}\r\n\r\n".encode())
    body.extend(source.read_bytes())
    body.extend(f"\r\n--{boundary}--\r\n".encode())
    request = urllib.request.Request(
        f"https://api.telegram.org/bot{token}/{method}",
        data=bytes(body),
        headers={"Content-Type": f"multipart/form-data; boundary={boundary}"},
    )
    try:
        with urllib.request.urlopen(request, timeout=120) as response:
            result = json.load(response)
    except urllib.error.HTTPError as exc:
        detail = exc.read(700).decode("utf-8", "replace")
        raise RuntimeError(
            f"Telegram {method} upload failed (HTTP {exc.code}): {detail or exc.reason}"
        ) from exc
    if not result.get("ok"):
        raise RuntimeError(f"Telegram {method} upload failed: {result.get('description', result)}")
    return result.get("result", {})


def send_message(chat_id: str | int, text: str, keyboard: dict | None = None) -> dict:
    payload = {"chat_id": str(chat_id), "text": text}
    if keyboard:
        payload["reply_markup"] = keyboard
    return _telegram_api("sendMessage", payload)


def send_photo(chat_id: str | int, path: str, caption: str = "") -> dict:
    fields = {"chat_id": str(chat_id)}
    if caption:
        fields["caption"] = caption[:1024]
    return _multipart_api("sendPhoto", fields, "photo", path)


def send_document(chat_id: str | int, path: str, caption: str = "") -> dict:
    fields = {"chat_id": str(chat_id)}
    if caption:
        fields["caption"] = caption[:1024]
    return _multipart_api("sendDocument", fields, "document", path)


def answer_callback(callback_id: str, text: str = "") -> dict:
    payload = {"callback_query_id": callback_id}
    if text:
        payload["text"] = text[:200]
    return _telegram_api("answerCallbackQuery", payload)


def _best_effort(callable_, *args) -> None:
    """Do not let a cosmetic Telegram acknowledgement duplicate a queued job."""
    try:
        callable_(*args)
    except Exception as exc:
        print("Telegram acknowledgement failed:", exc)


def _allowed_chat(chat_id: str | int) -> bool:
    configured = (
        os.environ.get("TELEGRAM_ALLOWED_CHAT_ID", "").strip()
        or os.environ.get("TELEGRAM_CHAT_ID", "").strip()
    )
    return not configured or hmac.compare_digest(configured, str(chat_id))


def _clean_topic(value: str) -> str:
    topic = P.clean_cover_hook(value)
    topic = re.sub(r"\s+", " ", topic).strip(" .,:;|/")
    return topic[:90]


def _callback_data(topic: str, source_type: str) -> str:
    """Fit an approval instruction inside Telegram's 64-byte callback limit."""
    code = SOURCE_TO_CODE.get(source_type, "m")
    prefix = f"b|{code}|"
    available = 64 - len(prefix.encode("utf-8"))
    encoded = _clean_topic(topic).encode("utf-8")[:available]
    while True:
        try:
            compact_topic = encoded.decode("utf-8")
            break
        except UnicodeDecodeError:
            encoded = encoded[:-1]
    return prefix + compact_topic.rstrip()


def suggest_topic() -> dict:
    prompt = """Suggest one strong carousel topic for a thoughtful AI and self-education
creator. Rotate between: useful AI tools, emotionally specific video essay
watchlists, Substack reading instead of doomscrolling, and runnable GitHub AI
projects. The topic should sound natural and specific, like 'video essays for
when you feel sad'. Keep it under 52 characters. Return topic and source_type.
source_type must be exactly youtube_video, substack_article, github_repo, or
tool_website. Do not use em dashes, en dashes, a list count, Part 1, or hype."""
    try:
        result = P._openai_json(prompt, use_web_search=False)
        source_type = str(result.get("source_type", "")).strip()
        topic = _clean_topic(result.get("topic", ""))
        if topic and source_type in SOURCE_TO_CODE:
            return {"topic": topic, "source_type": source_type}
    except Exception as exc:
        print("Telegram topic suggestion fallback:", exc)
    index = datetime.date.today().toordinal() % len(FALLBACK_TOPICS)
    topic, source_type = FALLBACK_TOPICS[index]
    return {"topic": topic, "source_type": source_type}


def send_daily_suggestion(chat_id: str | int | None = None) -> dict:
    target = str(chat_id or os.environ.get("TELEGRAM_CHAT_ID", "").strip())
    if not target:
        raise RuntimeError("Add TELEGRAM_CHAT_ID for the daily 9 PM suggestion")
    suggestion = suggest_topic()
    topic = suggestion["topic"]
    keyboard = {"inline_keyboard": [[
        {"text": "Approve and build", "callback_data": _callback_data(
            topic, suggestion["source_type"])},
        {"text": "Another idea", "callback_data": "n"},
    ]]}
    send_message(
        target,
        f"Tonight's carousel idea\n\n{topic}\n\nApprove it, ask for another idea, "
        "or send me any topic of your own.",
        keyboard,
    )
    return suggestion


def _dispatch(event_type: str, payload: dict) -> None:
    token = os.environ.get("GITHUB_DISPATCH_TOKEN", "").strip()
    repository = os.environ.get(
        "TELEGRAM_WORKER_REPOSITORY", "peepon95/aicarousellproject").strip()
    if not token:
        raise RuntimeError(
            "Add GITHUB_DISPATCH_TOKEN so Telegram can start the carousel worker"
        )
    request = urllib.request.Request(
        f"https://api.github.com/repos/{repository}/dispatches",
        data=json.dumps({"event_type": event_type, "client_payload": payload}).encode(),
        method="POST",
        headers={
            "Accept": "application/vnd.github+json",
            "Authorization": f"Bearer {token}",
            "Content-Type": "application/json",
            "User-Agent": "ai-carousel-telegram-agent/1.0",
            "X-GitHub-Api-Version": "2022-11-28",
        },
    )
    try:
        with urllib.request.urlopen(request, timeout=30) as response:
            if response.status != 204:
                raise RuntimeError(f"GitHub worker returned HTTP {response.status}")
    except urllib.error.HTTPError as exc:
        detail = exc.read(700).decode("utf-8", "replace")
        raise RuntimeError(
            f"GitHub worker dispatch failed (HTTP {exc.code}): {detail or exc.reason}"
        ) from exc


def request_carousel(topic: str, chat_id: str | int, source_type: str = "auto") -> None:
    cleaned = _clean_topic(topic)
    if not cleaned:
        raise ValueError("Send a topic with at least a few words")
    lane = P.infer_source_type(cleaned, source_type)
    _dispatch("telegram_carousel", {
        "topic": cleaned,
        "source_type": lane,
        "chat_id": str(chat_id),
    })


def request_suggestion(chat_id: str | int) -> None:
    _dispatch("telegram_suggestion", {"chat_id": str(chat_id)})


def handle_update(update: dict) -> dict:
    callback = update.get("callback_query") or {}
    if callback:
        message = callback.get("message") or {}
        chat_id = (message.get("chat") or {}).get("id")
        callback_id = callback.get("id", "")
        if not chat_id or not _allowed_chat(chat_id):
            if callback_id:
                _best_effort(answer_callback, callback_id, "This bot is private.")
            return {"ignored": True}
        data = str(callback.get("data", ""))
        if callback_id:
            _best_effort(answer_callback, callback_id, "Got it")
        if data == "n":
            request_suggestion(chat_id)
            _best_effort(send_message, chat_id, "Finding a different idea for you now.")
            return {"action": "suggestion"}
        if data.startswith("b|"):
            _, code, topic = data.split("|", 2)
            request_carousel(topic, chat_id, CODE_TO_SOURCE.get(code, "auto"))
            _best_effort(
                send_message,
                chat_id,
                f"Approved: {topic}\n\nI am researching and building it now. "
                "The previews and ZIP will arrive here when ready.",
            )
            return {"action": "build", "topic": topic}
        return {"ignored": True}

    message = update.get("message") or {}
    chat_id = (message.get("chat") or {}).get("id")
    text = str(message.get("text", "")).strip()
    if not chat_id or not text or not _allowed_chat(chat_id):
        return {"ignored": True}
    if text.startswith("/start"):
        send_message(
            chat_id,
            "Welcome to your private carousel agent. Every day at 9 PM I will "
            "suggest one topic. Tap Approve and I will send the finished slides "
            "and ZIP here. You can also send any topic whenever you want.\n\n"
            f"Your Telegram chat ID is {chat_id}.",
        )
        return {"action": "start", "chat_id": str(chat_id)}
    if text.startswith("/help"):
        send_message(
            chat_id,
            "Send a topic such as:\n"
            "video essays for when you feel sad\n"
            "Substack articles instead of doomscrolling\n"
            "AI tools for planning a solo project",
        )
        return {"action": "help"}
    if text.startswith("/"):
        send_message(chat_id, "I do not know that command yet. Send /help or a topic.")
        return {"action": "unknown_command"}
    request_carousel(text, chat_id)
    _best_effort(
        send_message,
        chat_id,
        f"Topic received: {_clean_topic(text)}\n\nI am researching and building it now. "
        "The previews and ZIP will arrive here when ready.",
    )
    return {"action": "build", "topic": _clean_topic(text)}


def set_webhook(public_url: str) -> dict:
    secret = os.environ.get("TELEGRAM_WEBHOOK_SECRET", "").strip()
    if not secret:
        raise RuntimeError("Add TELEGRAM_WEBHOOK_SECRET before registering the webhook")
    return _telegram_api("setWebhook", {
        "url": public_url.rstrip("/") + "/telegram/webhook",
        "secret_token": secret,
        "allowed_updates": ["message", "callback_query"],
        "drop_pending_updates": False,
    })
