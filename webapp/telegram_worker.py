"""Durable carousel worker invoked by GitHub Actions."""

from __future__ import annotations

import argparse
import datetime
import os
import re
import tempfile
import zipfile
from pathlib import Path

from . import pipeline as P
from . import telegram_agent as T


def _safe_slug(value: str) -> str:
    slug = re.sub(r"[^a-z0-9]+", "-", value.lower()).strip("-")
    return slug[:48] or "carousel"


def build_and_send(topic: str, chat_id: str, source_type: str = "auto") -> dict:
    count = P._bounded_env_int("TELEGRAM_CAROUSEL_ITEMS", 5, 3, 8)
    T.send_message(chat_id, f"Research started for: {topic}")
    try:
        draft = P.generate_topic_carousel(topic, count=count, source_type=source_type)
        resources = draft["candidates"][:count]
        run_id = "telegram_" + datetime.datetime.now().strftime("%Y%m%d_%H%M%S")
        result = P.build_carousel(
            resources,
            bg_query=os.environ.get(
                "TELEGRAM_BACKGROUND_QUERY",
                "warm editorial interiors muted film aesthetic",
            ),
            cover_title=draft["cover_hook"],
            cover_hook=draft["cover_hook"],
            run_id=run_id,
            split_mode="single",
            comment_keyword=os.environ.get("TELEGRAM_COMMENT_KEYWORD", "GUIDE"),
            visual_style="editorial_reference",
            canvas_format=draft.get("recommended_canvas", "editorial_3_4"),
        )
        slide_paths = [
            Path(P.OUT, name) for name in result["slides"]
            if Path(P.OUT, name).is_file()
        ]
        if not slide_paths:
            raise RuntimeError("The carousel built without downloadable slides")
        for index, slide_path in enumerate(slide_paths):
            caption = draft["cover_hook"] if index == 0 else ""
            T.send_photo(chat_id, str(slide_path), caption)
        with tempfile.TemporaryDirectory(prefix="telegram-carousel-") as folder:
            zip_path = Path(folder, f"{_safe_slug(topic)}.zip")
            with zipfile.ZipFile(zip_path, "w", zipfile.ZIP_DEFLATED) as archive:
                for slide_path in slide_paths:
                    archive.write(slide_path, arcname=slide_path.name)
            T.send_document(
                chat_id,
                str(zip_path),
                "Carousel ZIP. Open it in Telegram and save it to Files on your phone.",
            )
        T.send_message(
            chat_id,
            "Done. The slides are above and the ZIP contains every full-resolution image.",
        )
        return {"slides": [path.name for path in slide_paths], "topic": topic}
    except Exception as exc:
        T.send_message(
            chat_id,
            f"I could not finish this carousel: {exc}\n\nSend the topic again or make it more specific.",
        )
        raise


def main() -> None:
    parser = argparse.ArgumentParser(description="Telegram carousel worker")
    subparsers = parser.add_subparsers(dest="command", required=True)

    suggest = subparsers.add_parser("suggest")
    suggest.add_argument("--chat-id", default=os.environ.get("TELEGRAM_CHAT_ID", ""))

    build = subparsers.add_parser("build")
    build.add_argument("--topic", required=True)
    build.add_argument("--chat-id", required=True)
    build.add_argument("--source-type", default="auto")

    webhook = subparsers.add_parser("setup-webhook")
    webhook.add_argument("--url", required=True)

    args = parser.parse_args()
    if args.command == "suggest":
        T.send_daily_suggestion(args.chat_id)
    elif args.command == "build":
        build_and_send(args.topic, args.chat_id, args.source_type)
    elif args.command == "setup-webhook":
        T.set_webhook(args.url)
        print("Telegram webhook registered")


if __name__ == "__main__":
    main()
