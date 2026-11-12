import contextlib
import io
import json
import os
import sys
import tempfile
import unittest
import urllib.error
from datetime import datetime, timezone
from unittest import mock

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import caption_check as cc  # noqa: E402
import send_post as sp  # noqa: E402

NOW = datetime(2026, 11, 10, 12, 0)
FUTURE = "2026-12-01 18:30"
VIDEO = "https://example.com/clip.mp4"
SECRET = "s3cr3t-value-do-not-print"
WEBHOOK = "https://n8n.example.com/webhook/abc"
GOOD = (
    '"My Video Title"\n'
    "Short line one\n"
    "Caption: This is the caption.\n"
    "Hashtags: #one, #two #three\n"
)


class TempFiles(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)

    def write(self, name, text):
        path = os.path.join(self.tmp.name, name)
        with open(path, "w", encoding="utf-8") as f:
            f.write(text)
        return path

    def run_main(self, argv, env_path):
        out = io.StringIO()
        with contextlib.redirect_stdout(out):
            code = sp.main(argv, env_path=env_path, now=NOW)
        return code, out.getvalue()


class TimeConversionTests(unittest.TestCase):
    def test_format(self):
        result = sp.local_to_utc(FUTURE)
        self.assertRegex(result, r"^\d{4}-\d\d-\d\dT\d\d:\d\d:00Z$")

    def test_round_trips_to_local_time(self):
        result = sp.local_to_utc(FUTURE)
        utc = datetime.strptime(result, sp.UTC_FORMAT).replace(tzinfo=timezone.utc)
        local = utc.astimezone().replace(tzinfo=None)
        self.assertEqual(local, datetime(2026, 12, 1, 18, 30))

    def test_matches_local_offset(self):
        local = datetime(2026, 7, 4, 9, 15)
        offset = local.astimezone().utcoffset()
        expected = (local - offset).strftime(sp.UTC_FORMAT)
        self.assertEqual(sp.local_to_utc("2026-07-04 09:15"), expected)

    def test_invalid_time(self):
        with self.assertRaises(ValueError):
            sp.local_to_utc("2026-13-01 18:30")


class PayloadTests(unittest.TestCase):
    def test_build_payload(self):
        post = cc.parse_post(GOOD)
        payload = sp.build_payload(post, VIDEO, "2026-12-02T00:30:00Z")
        self.assertEqual(payload, {
            "title": "My Video Title",
            "caption": "This is the caption.",
            "hashtags": ["#one", "#two", "#three"],
            "text": "My Video Title\n\nThis is the caption.\n\n#one #two #three",
            "video_url": VIDEO,
            "scheduled_time_utc": "2026-12-02T00:30:00Z",
        })

    def test_payload_is_json_serializable(self):
        post = cc.parse_post(GOOD)
        json.dumps(sp.build_payload(post, VIDEO, "2026-12-02T00:30:00Z"))


class EnvTests(TempFiles):
    def test_parse_env(self):
        values = sp.parse_env(
            "# comment\n\nexport N8N_WEBHOOK_URL = 'https://x/y'\n"
            'N8N_SECRET="abc=def"\nnot a pair\n')
        self.assertEqual(values, {"N8N_WEBHOOK_URL": "https://x/y",
                                  "N8N_SECRET": "abc=def"})

    def test_missing_env_file(self):
        with self.assertRaises(sp.SendError) as ctx:
            sp.load_config(os.path.join(self.tmp.name, "nope.env"))
        self.assertIn("No .env file", str(ctx.exception))

    def test_missing_secret(self):
        env = self.write(".env", f"N8N_WEBHOOK_URL={WEBHOOK}\n")
        with self.assertRaises(sp.SendError) as ctx:
            sp.load_config(env)
        self.assertIn("N8N_SECRET is missing", str(ctx.exception))

    def test_missing_both(self):
        env = self.write(".env", "N8N_SECRET=\n")
        with self.assertRaises(sp.SendError) as ctx:
            sp.load_config(env)
        self.assertIn("N8N_WEBHOOK_URL and N8N_SECRET are missing",
                      str(ctx.exception))

    def test_main_exits_1_on_missing_values(self):
        post = self.write("post.txt", GOOD)
        env = self.write(".env", f"N8N_WEBHOOK_URL={WEBHOOK}\n")
        with mock.patch("urllib.request.urlopen") as urlopen:
            code, out = self.run_main(
                [post, "--at", FUTURE, "--video", VIDEO, "--dry-run"], env)
        self.assertEqual(code, 1)
        self.assertIn("N8N_SECRET", out)
        urlopen.assert_not_called()


class DryRunTests(TempFiles):
    def test_dry_run_prints_payload_and_hides_secret(self):
        post = self.write("post.txt", GOOD)
        env = self.write(".env",
                         f"N8N_WEBHOOK_URL={WEBHOOK}\nN8N_SECRET={SECRET}\n")
        with mock.patch("urllib.request.urlopen") as urlopen:
            code, out = self.run_main(
                [post, "--at", FUTURE, "--video", VIDEO, "--dry-run"], env)
        self.assertEqual(code, 0)
        urlopen.assert_not_called()
        self.assertIn("DRY RUN", out)
        self.assertIn(WEBHOOK, out)
        self.assertIn("X-Webhook-Secret: ****", out)
        self.assertNotIn(SECRET, out)
        payload = json.loads(out.split("Payload:\n", 1)[1])
        self.assertEqual(payload["scheduled_time_utc"], sp.local_to_utc(FUTURE))
        self.assertEqual(payload["video_url"], VIDEO)

    def test_invalid_post_is_not_sent(self):
        post = self.write("post.txt", GOOD.replace("Short line one",
                                                   "Short (line) one"))
        env = self.write(".env",
                         f"N8N_WEBHOOK_URL={WEBHOOK}\nN8N_SECRET={SECRET}\n")
        with mock.patch("urllib.request.urlopen") as urlopen:
            code, out = self.run_main([post, "--at", FUTURE, "--video", VIDEO],
                                      env)
        self.assertEqual(code, 1)
        self.assertIn("FAIL", out)
        self.assertIn("Nothing was sent", out)
        urlopen.assert_not_called()


class FakeResponse(io.BytesIO):
    def __init__(self, body, status=200):
        super().__init__(body)
        self.status = status

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False


class SendTests(TempFiles):
    def setUp(self):
        super().setUp()
        self.post = self.write("post.txt", GOOD)
        self.env = self.write(
            ".env", f"N8N_WEBHOOK_URL={WEBHOOK}\nN8N_SECRET={SECRET}\n")
        self.argv = [self.post, "--at", FUTURE, "--video", VIDEO]

    def test_success_sends_header_and_prints_reply(self):
        with mock.patch("urllib.request.urlopen",
                        return_value=FakeResponse(b'{"ok":true}')) as urlopen:
            code, out = self.run_main(self.argv, self.env)
        self.assertEqual(code, 0)
        self.assertIn('{"ok":true}', out)
        request = urlopen.call_args.args[0]
        self.assertEqual(urlopen.call_args.kwargs["timeout"], 15)
        self.assertEqual(request.get_method(), "POST")
        self.assertEqual(request.get_header("X-webhook-secret"), SECRET)
        self.assertEqual(json.loads(request.data)["title"], "My Video Title")

    def test_http_error(self):
        error = urllib.error.HTTPError(WEBHOOK, 403, "Forbidden", {},
                                       io.BytesIO(b"bad secret"))
        with mock.patch("urllib.request.urlopen", side_effect=error):
            code, out = self.run_main(self.argv, self.env)
        self.assertEqual(code, 1)
        self.assertIn("HTTP 403", out)
        self.assertIn("bad secret", out)

    def test_non_2xx_without_exception(self):
        with mock.patch("urllib.request.urlopen",
                        return_value=FakeResponse(b"moved", status=302)):
            code, out = self.run_main(self.argv, self.env)
        self.assertEqual(code, 1)
        self.assertIn("HTTP 302", out)

    def test_network_error(self):
        with mock.patch("urllib.request.urlopen",
                        side_effect=urllib.error.URLError("connection refused")):
            code, out = self.run_main(self.argv, self.env)
        self.assertEqual(code, 1)
        self.assertIn("Could not reach the webhook", out)

    def test_secret_never_printed_even_if_echoed(self):
        with mock.patch("urllib.request.urlopen",
                        return_value=FakeResponse(SECRET.encode())):
            code, out = self.run_main(self.argv, self.env)
        self.assertEqual(code, 0)
        self.assertNotIn(SECRET, out)


if __name__ == "__main__":
    unittest.main()
