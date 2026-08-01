import io
import json
import os
import tempfile
import unittest
from unittest.mock import patch

from fastapi.testclient import TestClient
from PIL import Image, ImageDraw

from webapp import app as app_module
from webapp import pipeline
from webapp import telegram_agent
from webapp import telegram_worker


class SourceLaneTests(unittest.TestCase):
    @patch.object(telegram_worker.T, "send_document")
    @patch.object(telegram_worker.T, "send_photo")
    @patch.object(telegram_worker.T, "send_message")
    @patch.object(telegram_worker.P, "build_carousel")
    @patch.object(telegram_worker.P, "generate_topic_carousel")
    def test_telegram_worker_sends_previews_and_zip(
            self, generate, build, send_message, send_photo, send_document):
        generate.return_value = {
            "cover_hook": "Video essays for a hard day",
            "recommended_canvas": "story_9_16",
            "candidates": [
                {"name": f"Essay {index}",
                 "url": f"https://youtube.com/watch?v=abc1234567{index}"}
                for index in range(4)
            ],
        }
        with tempfile.TemporaryDirectory() as output:
            for name in ("cover.png", "detail.png"):
                with open(os.path.join(output, name), "wb") as image:
                    image.write(b"fake png")
            build.return_value = {"slides": ["cover.png", "detail.png"]}
            with patch.object(telegram_worker.P, "OUT", output):
                result = telegram_worker.build_and_send(
                    "video essays for a hard day", "12345", "youtube_video")

        self.assertEqual(send_photo.call_count, 2)
        send_document.assert_called_once()
        self.assertTrue(send_document.call_args.args[1].endswith(".zip"))
        self.assertEqual(len(result["slides"]), 2)
        self.assertGreaterEqual(send_message.call_count, 2)
        self.assertEqual(len(build.call_args.args[0]), 4)

    def test_telegram_approval_payload_fits_platform_limit(self):
        payload = telegram_agent._callback_data(
            "Substack articles instead of doomscrolling and losing the evening",
            "substack_article",
        )
        self.assertLessEqual(len(payload.encode("utf-8")), 64)
        self.assertTrue(payload.startswith("b|s|"))

    @patch.object(telegram_agent, "send_message")
    @patch.object(telegram_agent, "request_carousel")
    def test_telegram_topic_message_dispatches_carousel(self, request, send):
        update = {"message": {
            "chat": {"id": 12345},
            "text": "video essays for when you feel sad",
        }}
        with patch.dict(os.environ, {"TELEGRAM_ALLOWED_CHAT_ID": "12345"}):
            result = telegram_agent.handle_update(update)
        request.assert_called_once_with(
            "video essays for when you feel sad", 12345)
        send.assert_called_once()
        self.assertEqual(result["action"], "build")

    @patch.object(telegram_agent, "send_message")
    @patch.object(telegram_agent, "answer_callback")
    @patch.object(telegram_agent, "request_carousel")
    def test_telegram_approval_uses_locked_source_lane(
            self, request, answer, send):
        update = {"callback_query": {
            "id": "callback-1",
            "data": "b|s|Substack articles instead of doomscrolling",
            "message": {"chat": {"id": 12345}},
        }}
        with patch.dict(os.environ, {"TELEGRAM_ALLOWED_CHAT_ID": "12345"}):
            result = telegram_agent.handle_update(update)
        answer.assert_called_once_with("callback-1", "Got it")
        request.assert_called_once_with(
            "Substack articles instead of doomscrolling",
            12345,
            "substack_article",
        )
        send.assert_called_once()
        self.assertEqual(result["action"], "build")

    def test_background_research_recovers_from_a_poll_timeout(self):
        queued = io.BytesIO(json.dumps({
            "id": "resp_test", "status": "queued",
        }).encode())
        completed = io.BytesIO(json.dumps({
            "id": "resp_test",
            "status": "completed",
            "output_text": json.dumps({"cover_hook": "Recovered"}),
        }).encode())
        settings = {
            "OPENAI_API_KEY": "test-key",
            "OPENAI_BACKGROUND_MODE": "true",
            "OPENAI_TIMEOUT_SECONDS": "60",
            "OPENAI_MAX_RETRIES": "2",
        }
        with patch.object(pipeline, "load_dotenv"), \
                patch.dict(os.environ, settings, clear=False), \
                patch.object(
                    pipeline.urllib.request, "urlopen",
                    side_effect=[queued, TimeoutError("read timed out"), completed],
                ) as urlopen, \
                patch.object(pipeline.time, "sleep"):
            result = pipeline._openai_json("research this topic")

        self.assertEqual(result["cover_hook"], "Recovered")
        self.assertEqual(urlopen.call_count, 3)
        requests = [call.args[0] for call in urlopen.call_args_list]
        self.assertEqual(sum(request.data is not None for request in requests), 1)

    def test_plain_language_selects_a_strict_lane(self):
        cases = {
            "video essays to watch when you feel lost": "youtube_video",
            "best YouTube channels for design": "youtube_channel",
            "Substacks I read instead of scrolling": "substack_article",
            "GitHub projects you can run locally": "github_repo",
            "projects you can run on your own laptop": "github_repo",
            "AI tools for research": "tool_website",
        }
        for query, expected in cases.items():
            self.assertEqual(pipeline.infer_source_type(query), expected)
        self.assertEqual(
            pipeline.infer_source_type("things worth saving", "mixed_sources"),
            "mixed_sources",
        )

    def test_urls_cannot_cross_source_lanes(self):
        urls = {
            "https://youtube.com/watch?v=abc12345678": "youtube_video",
            "https://youtube.com/@veritasium": "youtube_channel",
            "https://example.substack.com/p/a-good-essay": "substack_article",
            "https://github.com/owner/repo": "github_repo",
            "https://lovable.dev": "tool_website",
        }
        for url, expected in urls.items():
            self.assertEqual(pipeline.source_type_for_url(url), expected)
            self.assertTrue(pipeline.source_matches(url, expected))
        self.assertFalse(pipeline.source_matches(
            "https://github.com/owner/repo", "youtube_video"))
        self.assertTrue(pipeline.source_matches(
            "https://github.com/owner/repo", "mixed_sources"))

    def test_model_punctuation_is_cleaned(self):
        self.assertEqual(
            pipeline.clean_editorial_text("Try this — it works – today"),
            "Try this, it works, today",
        )

    def test_cover_is_topic_led_and_single_by_default(self):
        self.assertEqual(
            pipeline.clean_cover_hook("Part 1 of 2: 8 video essays to watch"),
            "video essays to watch",
        )
        groups = pipeline._series_groups([
            {"name": "First", "part": 1},
            {"name": "Second", "part": 2},
        ])
        self.assertEqual(len(groups), 1)
        self.assertTrue(all(item["part"] == 1 for item in groups[0]))

    @patch.object(pipeline.C, "_source_metadata", return_value={
        "title": "Complete thumbnail",
        "description": "Creator",
        "image": "https://i.ytimg.com/vi/abc12345678/hqdefault.jpg",
    })
    @patch.object(pipeline.C, "_remote_image")
    def test_youtube_preview_preserves_full_sixteen_by_nine_frame(
            self, remote_image, _metadata):
        frame = Image.new("RGB", (1600, 900), (20, 180, 80))
        drawing = ImageDraw.Draw(frame)
        drawing.rectangle((0, 0, 1599, 99), fill=(220, 20, 20))
        drawing.rectangle((0, 800, 1599, 899), fill=(20, 40, 220))
        remote_image.return_value = frame
        with tempfile.TemporaryDirectory() as output:
            with patch.object(pipeline.C, "SHOT", output):
                path = pipeline.C.build_resource_preview(
                    "Video", "https://youtube.com/watch?v=abc12345678", "",
                    out="preview.png", require_image=True)
                preview = Image.open(path).convert("RGB")
        self.assertEqual(preview.size, (1200, 900))
        # YouTube thumbnails now touch the card edges with no cream border.
        self.assertGreater(preview.getpixel((8, 8))[0], 150)
        self.assertGreater(preview.getpixel((600, 50))[0], 150)
        self.assertGreater(preview.getpixel((600, 650))[2], 150)

    @patch.object(pipeline, "_url_is_valid", return_value=True)
    @patch.object(pipeline, "_openai_json")
    def test_generated_mismatches_are_discarded(self, generate, _valid):
        generate.return_value = {
            "carousel_type": "resource_list",
            "cover_hook": "things worth watching",
            "slides": [
                {
                    "name": "A video essay",
                    "url": "https://youtube.com/watch?v=abc12345678",
                    "desc": "A thoughtful essay.",
                    "why": "Watch it when you need perspective.",
                },
                {
                    "name": "Wrong lane",
                    "url": "https://github.com/owner/repo",
                    "desc": "A repository.",
                    "why": "It does not belong here.",
                },
            ],
        }
        with self.assertRaisesRegex(RuntimeError, "four distinct videos"):
            pipeline.generate_topic_carousel(
                "things worth watching", source_type="youtube_video")
        self.assertEqual(generate.call_count, 2)

    @patch.object(pipeline, "_url_is_valid", return_value=True)
    @patch.object(pipeline, "_openai_json")
    def test_youtube_roundup_always_returns_four_distinct_videos(
            self, generate, _valid):
        generate.return_value = {
            "carousel_type": "resource_list",
            "cover_hook": "Video essays for a hard day",
            "slides": [{
                "name": f"Essay {index}",
                "url": f"https://youtube.com/watch?v=abc1234567{index}",
                "desc": "A thoughtful video essay.",
                "why": "Watch it for a new perspective.",
            } for index in range(6)],
        }
        result = pipeline.generate_topic_carousel(
            "video essays for a hard day", count=8, source_type="youtube_video")
        self.assertEqual(len(result["candidates"]), 4)
        self.assertEqual(
            len({item["url"] for item in result["candidates"]}), 4)
        self.assertTrue(all(
            item["source_type"] == "youtube_video"
            for item in result["candidates"]
        ))

    @patch.object(pipeline, "_url_is_valid", return_value=True)
    @patch.object(pipeline, "_openai_json")
    def test_mixed_research_requires_multiple_source_families(self, generate, _valid):
        generate.return_value = {
            "carousel_type": "resource_list",
            "cover_hook": "Things worth saving",
            "slides": [{
                "name": "Only one platform",
                "url": "https://youtube.com/watch?v=abc12345678",
                "desc": "A video.",
                "why": "Useful context.",
            }],
        }
        with self.assertRaisesRegex(RuntimeError, "only one source family"):
            pipeline.generate_topic_carousel(
                "things worth saving", source_type="mixed_sources")

    @patch.object(pipeline, "_github_run_evidence")
    @patch.object(pipeline, "pull_github", return_value=[])
    @patch.object(pipeline, "_url_is_valid", return_value=True)
    @patch.object(pipeline, "_openai_json")
    def test_runnable_projects_require_readme_command(
            self, generate, _valid, _github, run_evidence):
        generate.return_value = {
            "carousel_type": "resource_list",
            "cover_hook": "Projects I would actually run",
            "slides": [
                {
                    "name": "Runnable",
                    "url": "https://github.com/owner/runnable",
                    "desc": "A local application.",
                    "why": "Use it on your own machine.",
                },
                {
                    "name": "Unproven",
                    "url": "https://github.com/owner/unproven",
                    "desc": "A repository with no run instructions.",
                    "why": "It should not pass the filter.",
                },
            ],
        }
        run_evidence.side_effect = lambda url: (
            "npm run dev" if url.endswith("/runnable") else "")

        result = pipeline.generate_topic_carousel(
            "GitHub projects you can run locally", source_type="github_repo")

        self.assertEqual(len(result["candidates"]), 1)
        self.assertEqual(result["candidates"][0]["evidence"], "npm run dev")
        self.assertEqual(result["recommended_canvas"], "editorial_3_4")

    @patch.object(pipeline, "_openai_json")
    @patch.object(pipeline, "_video_transcript", return_value=("spoken lesson " * 20, "captions"))
    @patch.object(pipeline, "_url_is_valid", return_value=True)
    def test_youtube_breakdown_reuses_verified_source_card(
            self, _valid, _transcript, generate):
        generate.return_value = {
            "cover_hook": "A video worth keeping",
            "slides": [{
                "name": "The first lesson",
                "desc": "A useful idea.",
                "why": "Apply it today.",
                "needs_screenshot": False,
                "visual_url": "",
            }],
        }
        url = "https://www.youtube.com/watch?v=abc12345678"

        result = pipeline.generate_video_carousel(url)

        slide = result["candidates"][0]
        self.assertTrue(slide["needs_screenshot"])
        self.assertEqual(slide["visual_url"], url)
        self.assertEqual(slide["source_type"], "youtube_video")

    @patch.object(pipeline.C, "configure_canvas")
    @patch.object(pipeline.C, "build_cta", return_value="/tmp/cta.png")
    @patch.object(pipeline.C, "build_editorial_source", return_value="/tmp/detail.png")
    @patch.object(pipeline.C, "build_cover", return_value="/tmp/cover.png")
    @patch.object(pipeline.C, "build_resource_preview", return_value="/tmp/youtube.png")
    @patch.object(pipeline, "capture")
    @patch.object(pipeline, "fetch_backgrounds", return_value=[
        ("/tmp/cover.jpg", "cover credit"),
        ("/tmp/detail.jpg", "detail credit"),
    ])
    def test_build_locks_one_background_and_avoids_youtube_browser_capture(
            self, background, capture, preview, cover, editorial, cta, _canvas):
        url = "https://www.youtube.com/watch?v=abc12345678"
        resources = [
            {
                "name": "Lesson one", "url": url, "visual_url": "",
                "desc": "First idea", "why": "Use it", "needs_screenshot": False,
                "source_type": "video_source", "part": 1,
            },
            {
                "name": "Lesson two", "url": url, "visual_url": url,
                "desc": "Second idea", "why": "Use it", "needs_screenshot": True,
                "source_type": "youtube_video", "part": 1,
            },
        ]

        with tempfile.TemporaryDirectory() as output:
            with patch.object(pipeline, "OUT", output):
                pipeline.build_carousel(resources, bg_query="quiet beach")

        background.assert_called_once_with("quiet beach", 2)
        capture.assert_not_called()
        self.assertEqual(preview.call_count, 2)
        self.assertTrue(all(call.kwargs["require_image"] for call in preview.call_args_list))
        self.assertEqual(cover.call_args.args[0], "cover.jpg")
        self.assertTrue(all(call.args[0] == "detail.jpg"
                            for call in editorial.call_args_list))
        self.assertEqual(cta.call_args.args[0], "detail.jpg")


class WebContractTests(unittest.TestCase):
    def setUp(self):
        self.client = TestClient(app_module.app)

    def test_home_exposes_new_workflows(self):
        html = self.client.get("/").text
        for label in (
            "YouTube videos only",
            "Substack articles only",
            "Mixed public sources via OpenAI research",
            "Upload recording",
            "3:4 editorial",
        ):
            self.assertIn(label, html)

    def test_telegram_webhook_rejects_missing_secret(self):
        with patch.dict(os.environ, {"TELEGRAM_WEBHOOK_SECRET": "private-secret"}):
            response = self.client.post("/telegram/webhook", json={})
        self.assertEqual(response.status_code, 401)

    @patch.object(telegram_agent, "handle_update", return_value={"action": "start"})
    def test_telegram_webhook_accepts_verified_update(self, handle):
        with patch.dict(os.environ, {"TELEGRAM_WEBHOOK_SECRET": "private-secret"}):
            response = self.client.post(
                "/telegram/webhook",
                json={"update_id": 1},
                headers={"x-telegram-bot-api-secret-token": "private-secret"},
            )
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["action"], "start")
        handle.assert_called_once_with({"update_id": 1})

    @patch.object(telegram_agent, "send_message")
    @patch.object(telegram_agent, "handle_update", side_effect=RuntimeError(
        "worker is not configured"))
    def test_telegram_webhook_acknowledges_worker_failure(self, handle, send):
        update = {"update_id": 2, "message": {
            "chat": {"id": 12345}, "text": "Build this topic",
        }}
        with patch.dict(os.environ, {"TELEGRAM_WEBHOOK_SECRET": "private-secret"}):
            response = self.client.post(
                "/telegram/webhook",
                json=update,
                headers={"x-telegram-bot-api-secret-token": "private-secret"},
            )
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json(), {"ok": False, "handled": True})
        handle.assert_called_once_with(update)
        send.assert_called_once()

    @patch.object(telegram_agent, "send_daily_suggestion", return_value={
        "topic": "AI tools for calmer work", "source_type": "tool_website",
    })
    def test_daily_telegram_route_requires_cron_secret(self, suggest):
        with patch.dict(os.environ, {"CRON_SECRET": "cron-secret"}):
            denied = self.client.get("/telegram/daily")
            allowed = self.client.get(
                "/telegram/daily",
                headers={"authorization": "Bearer cron-secret"},
            )
        self.assertEqual(denied.status_code, 401)
        self.assertEqual(allowed.status_code, 200)
        self.assertEqual(allowed.json()["topic"], "AI tools for calmer work")
        suggest.assert_called_once()

    @patch.object(pipeline, "generate_topic_carousel")
    def test_pull_forwards_source_lane(self, generate):
        generate.return_value = {
            "candidates": [], "cover_hook": "Essays", "part_count": 1,
        }
        response = self.client.post("/pull", json={
            "mode": "topic",
            "query": "essays",
            "source_type": "substack_article",
        })
        self.assertEqual(response.status_code, 200)
        generate.assert_called_once_with(
            "essays", count=8, source_type="substack_article")

    @patch.object(pipeline, "generate_uploaded_video_carousel")
    def test_upload_is_analyzed_and_deleted(self, generate):
        generate.return_value = {
            "candidates": [], "cover_hook": "Recording", "part_count": 1,
        }
        response = self.client.post(
            "/upload-video",
            content=b"owned recording",
            headers={"x-filename": "screen.mp4", "content-type": "video/mp4"},
        )
        self.assertEqual(response.status_code, 200)
        uploaded_path = generate.call_args.args[0]
        self.assertFalse(os.path.exists(uploaded_path))


if __name__ == "__main__":
    unittest.main()
