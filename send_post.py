#!/usr/bin/env python3
"""Send a checked TikTok post to the n8n webhook.

Usage:
    python send_post.py POST_FILE --at "YYYY-MM-DD HH:MM" --video URL [--dry-run]

The post is validated with caption_check first; nothing is sent if it fails.
N8N_WEBHOOK_URL and N8N_SECRET are read from the .env file next to this script.

Exit codes: 0 = sent (or dry run OK), 1 = problem, 2 = bad command-line usage.
Standard library only.
"""

from __future__ import annotations

import argparse
import json
import os
import sys
import urllib.error
import urllib.request
from datetime import datetime, timezone

import caption_check as cc

REPO_ROOT = os.path.dirname(os.path.abspath(__file__))
DEFAULT_ENV_PATH = os.path.join(REPO_ROOT, ".env")
REQUIRED_KEYS = ("N8N_WEBHOOK_URL", "N8N_SECRET")
TIMEOUT_SECONDS = 15
UTC_FORMAT = "%Y-%m-%dT%H:%M:%SZ"
MASK = "****"


class SendError(Exception):
    """A problem to show the user in plain language (exit code 1)."""


def parse_env(text: str) -> dict[str, str]:
    """Parse simple KEY=VALUE lines. Blank lines and # comments are skipped.

    An optional leading "export " and matching surrounding quotes are removed.
    """
    values: dict[str, str] = {}
    for raw in text.lstrip("﻿").splitlines():
        line = raw.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        if line.startswith("export "):
            line = line[len("export "):].lstrip()
        key, _, value = line.partition("=")
        key, value = key.strip(), value.strip()
        if len(value) >= 2 and value[0] == value[-1] and value[0] in "\"'":
            value = value[1:-1]
        if key:
            values[key] = value
    return values


def load_config(env_path: str = DEFAULT_ENV_PATH) -> dict[str, str]:
    """Return the webhook URL and secret from .env, or raise SendError."""
    try:
        with open(env_path, encoding="utf-8") as f:
            values = parse_env(f.read())
    except FileNotFoundError:
        raise SendError(
            f"No .env file found at {env_path}. Copy .env.example to .env "
            "and fill in N8N_WEBHOOK_URL and N8N_SECRET.") from None
    missing = [k for k in REQUIRED_KEYS if not values.get(k)]
    if missing:
        raise SendError(
            f"{' and '.join(missing)} {'is' if len(missing) == 1 else 'are'} "
            f"missing or empty in {env_path}. Add "
            f"{'it' if len(missing) == 1 else 'them'} and try again.")
    url = values["N8N_WEBHOOK_URL"]
    if not url.lower().startswith(("http://", "https://")):
        raise SendError("N8N_WEBHOOK_URL in .env must start with http:// or "
                        "https://.")
    return {k: values[k] for k in REQUIRED_KEYS}


def local_to_utc(at: str) -> str:
    """Treat "YYYY-MM-DD HH:MM" as this computer's local time; return UTC."""
    local = datetime.strptime(at.strip(), cc.TIME_FORMAT)
    # astimezone() on a naive datetime assumes local time (works on Windows).
    return local.astimezone(timezone.utc).strftime(UTC_FORMAT)


def strip_title_quotes(title: str) -> str:
    if len(title) >= 2 and title.startswith('"') and title.endswith('"'):
        return title[1:-1].strip()
    return title


def build_payload(post: cc.Post, video_url: str, scheduled_utc: str) -> dict:
    """Build the JSON body for n8n from a post that already passed checks."""
    title = strip_title_quotes(post.title or "")
    caption = post.caption or ""
    hashtags = cc.split_hashtags(post.hashtags_raw or "")
    text = "\n\n".join(part for part in (title, caption, " ".join(hashtags))
                       if part)
    return {
        "title": title,
        "caption": caption,
        "hashtags": hashtags,
        "text": text,
        "video_url": video_url,
        "scheduled_time_utc": scheduled_utc,
    }


def redact(text: str, secret: str) -> str:
    return text.replace(secret, MASK) if secret else text


def send(url: str, secret: str, payload: dict,
         timeout: float = TIMEOUT_SECONDS) -> tuple[int, str]:
    """POST the payload. Returns (status, body) or raises SendError."""
    data = json.dumps(payload).encode("utf-8")
    request = urllib.request.Request(
        url, data=data, method="POST",
        headers={"Content-Type": "application/json",
                 "X-Webhook-Secret": secret})
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:
            body = response.read().decode("utf-8", errors="replace")
            status = response.status
    except urllib.error.HTTPError as e:
        body = e.read().decode("utf-8", errors="replace")
        raise SendError(
            f"The webhook answered with an error: HTTP {e.code} {e.reason}.\n"
            f"Response body: {body or '(empty)'}") from None
    except urllib.error.URLError as e:
        raise SendError(
            f"Could not reach the webhook: {e.reason}. Check "
            "N8N_WEBHOOK_URL in .env and that n8n is running.") from None
    except TimeoutError:
        raise SendError(
            f"The webhook did not answer within {timeout:g} seconds. Check "
            "that n8n is running and try again.") from None
    if not 200 <= status < 300:
        raise SendError(
            f"The webhook answered with an error: HTTP {status}.\n"
            f"Response body: {body or '(empty)'}")
    return status, body


def main(argv: list[str] | None = None, env_path: str = DEFAULT_ENV_PATH,
         now: datetime | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Check a TikTok post and send it to the n8n webhook.")
    parser.add_argument("post_file", help="path to the post text file")
    parser.add_argument("--at", required=True, metavar="'YYYY-MM-DD HH:MM'",
                        help="when the post will go live, in local time")
    parser.add_argument("--video", required=True, metavar="URL",
                        help="public URL of the video file")
    parser.add_argument("--dry-run", action="store_true",
                        help="print the payload and target without sending")
    args = parser.parse_args(argv)

    # 1. Validate the post before anything else.
    try:
        with open(args.post_file, encoding="utf-8") as f:
            text = f.read()
    except FileNotFoundError:
        print(cc.format_problems([f"The file {args.post_file} was not found."]))
        return 1
    except UnicodeDecodeError:
        print(cc.format_problems([f"The file {args.post_file} is not UTF-8 "
                                  "text. Save it as UTF-8 and try again."]))
        return 1

    problems, post, _ = cc.validate(text, args.at, now=now)
    if not args.video.lower().startswith(("http://", "https://")):
        problems.append("The --video value must be a URL starting with "
                        "http:// or https://.")
    if problems:
        print(cc.format_problems(problems))
        print("Nothing was sent.")
        return 1

    secret = ""
    try:
        # 2. Read the webhook settings.
        config = load_config(env_path)
        url, secret = config["N8N_WEBHOOK_URL"], config["N8N_SECRET"]

        # 3-4. Convert the time and build the payload.
        payload = build_payload(post, args.video, local_to_utc(args.at))

        # 7. Dry run: show what would be sent, never the secret.
        if args.dry_run:
            print("DRY RUN: nothing was sent.")
            print(f"Target URL: {redact(url, secret)}")
            print(f"Header:     X-Webhook-Secret: {MASK}")
            print("Payload:")
            print(redact(json.dumps(payload, indent=2, ensure_ascii=False),
                         secret))
            return 0

        # 5-6. Send it.
        status, body = send(url, secret, payload)
    except SendError as e:
        print(f"ERROR: {redact(str(e), secret)}")
        return 1

    print(f"Sent. The webhook answered with HTTP {status}.")
    print(f"Reply: {redact(body, secret) or '(empty)'}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
