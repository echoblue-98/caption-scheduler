#!/usr/bin/env python3
"""Validate a TikTok post file before it gets scheduled.

Usage:
    python caption_check.py POST_FILE --at "YYYY-MM-DD HH:MM" [--max-caption N]

Post file format:
    "Title in double quotes"
    short caption line
    another short caption line
    Caption: the main caption text
    Hashtags: #one #two #three

Exit codes: 0 = PASS, 1 = problems found, 2 = bad command-line usage.
Standard library only; no network calls.
"""

from __future__ import annotations

import argparse
import re
import sys
from dataclasses import dataclass, field
from datetime import datetime

DEFAULT_MAX_CAPTION = 2200
MIN_HASHTAGS = 3
MAX_HASHTAGS = 8
TIME_FORMAT = "%Y-%m-%d %H:%M"
SMART_QUOTES = "“”„‟"
PARENS = "()（）"  # ASCII and full-width parentheses


@dataclass
class Post:
    title: str | None = None
    short_lines: list[str] = field(default_factory=list)
    caption: str | None = None
    hashtags_raw: str | None = None


def _lines(text: str) -> list[str]:
    return text.lstrip("﻿").splitlines()


def parse_post(text: str) -> Post:
    """Split the post text into title, short lines, caption and hashtags.

    Anything after "Caption:" (until "Hashtags:") belongs to the caption, so a
    multi-line caption works. Section labels are case-insensitive.
    """
    lines = [ln.strip() for ln in _lines(text)]
    while lines and not lines[0]:
        lines.pop(0)

    post = Post()
    if not lines:
        return post
    post.title = lines[0]

    section = "short"
    caption_parts: list[str] = []
    hashtag_parts: list[str] = []
    for line in lines[1:]:
        lower = line.lower()
        if lower.startswith("caption:"):
            section = "caption"
            caption_parts.append(line[len("caption:"):].strip())
        elif lower.startswith("hashtags:"):
            section = "hashtags"
            hashtag_parts.append(line[len("hashtags:"):].strip())
        elif section == "short":
            if line:
                post.short_lines.append(line)
        elif section == "caption":
            caption_parts.append(line)
        else:
            hashtag_parts.append(line)

    caption = "\n".join(caption_parts).strip()
    hashtags = " ".join(hashtag_parts).strip()
    post.caption = caption or None
    post.hashtags_raw = hashtags or None
    return post


def split_hashtags(raw: str) -> list[str]:
    """Hashtags may be separated by spaces and/or commas."""
    return [tok for tok in re.split(r"[\s,]+", raw) if tok]


def check_title(post: Post) -> list[str]:
    title = post.title
    if not title:
        return ["The post is empty. Line 1 should be the title in double quotes."]
    if title.lower().startswith(("caption:", "hashtags:")):
        label = title.split(":")[0]
        return [f"Line 1 should be the title in double quotes, but it is the "
                f"{label} line. Add the title above it."]
    if title[0] in SMART_QUOTES or title[-1] in SMART_QUOTES:
        return ['The title uses curly "smart" quotes. Use plain straight '
                'double quotes (") instead.']
    if len(title) < 2 or not (title.startswith('"') and title.endswith('"')):
        return ['The title on line 1 must be wrapped in double quotes, '
                'like "My Video Title".']
    if not title[1:-1].strip():
        return ["The title on line 1 is empty. Put some text between the quotes."]
    return []


def check_sections(post: Post) -> list[str]:
    problems = []
    if post.caption is None:
        problems.append('The "Caption:" line is missing or empty.')
    if post.hashtags_raw is None:
        problems.append('The "Hashtags:" line is missing or empty.')
    return problems


def check_parentheses(text: str) -> list[str]:
    bad_lines = [
        str(i)
        for i, line in enumerate(_lines(text), start=1)
        if any(ch in line for ch in PARENS)
    ]
    if not bad_lines:
        return []
    which = "line" if len(bad_lines) == 1 else "lines"
    return [f"Parentheses are not allowed. Remove them from {which} "
            f"{', '.join(bad_lines)}."]


def check_caption_length(post: Post, max_len: int) -> list[str]:
    if post.caption is None:
        return []
    length = len(post.caption)
    if length > max_len:
        return [f"The caption is {length} characters long. The limit is "
                f"{max_len}, so cut at least {length - max_len} characters."]
    return []


def check_hashtags(post: Post) -> list[str]:
    if post.hashtags_raw is None:
        return []
    tags = split_hashtags(post.hashtags_raw)
    problems = []
    bad = [t for t in tags if not t.startswith("#") or len(t) < 2 or "#" in t[1:]]
    if bad:
        problems.append(
            "Each hashtag must start with # and contain no spaces. These look "
            f"wrong: {', '.join(bad)}. A word without # usually means a space "
            "slipped into a hashtag."
        )
    else:
        count = len(tags)
        if not MIN_HASHTAGS <= count <= MAX_HASHTAGS:
            problems.append(
                f"Use {MIN_HASHTAGS} to {MAX_HASHTAGS} hashtags. "
                f"This post has {count}."
            )
    return problems


def check_post_time(at: str, now: datetime) -> tuple[list[str], datetime | None]:
    try:
        when = datetime.strptime(at.strip(), TIME_FORMAT)
    except ValueError:
        return ([f'The post time "{at}" is not a valid date and time. Use the '
                 'format YYYY-MM-DD HH:MM, for example "2026-12-01 18:30".'],
                None)
    if when <= now:
        return ([f"The post time {when.strftime(TIME_FORMAT)} is not in the "
                 "future. Pick a later time."], when)
    return [], when


def validate(text: str, at: str, max_caption: int = DEFAULT_MAX_CAPTION,
             now: datetime | None = None) -> tuple[list[str], Post, datetime | None]:
    """Run every check. Returns (problems, parsed post, parsed post time)."""
    now = now or datetime.now()
    post = parse_post(text)
    problems: list[str] = []
    problems += check_title(post)
    problems += check_sections(post)
    problems += check_parentheses(text)
    problems += check_caption_length(post, max_caption)
    problems += check_hashtags(post)
    time_problems, when = check_post_time(at, now)
    problems += time_problems
    return problems, post, when


def format_summary(post: Post, when: datetime, max_caption: int) -> str:
    tags = split_hashtags(post.hashtags_raw or "")
    return "\n".join([
        "PASS",
        f"  Title:       {post.title}",
        f"  Short lines: {len(post.short_lines)}",
        f"  Caption:     {len(post.caption or '')}/{max_caption} characters",
        f"  Hashtags:    {len(tags)} - {' '.join(tags)}",
        f"  Post time:   {when.strftime(TIME_FORMAT)}",
    ])


def format_problems(problems: list[str]) -> str:
    noun = "problem" if len(problems) == 1 else "problems"
    out = [f"FAIL: {len(problems)} {noun} found"]
    out += [f"{i}. {p}" for i, p in enumerate(problems, start=1)]
    return "\n".join(out)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Check a TikTok post file before scheduling it.")
    parser.add_argument("post_file", help="path to the post text file")
    parser.add_argument("--at", required=True, metavar="'YYYY-MM-DD HH:MM'",
                        help="when the post will go live, in local time")
    parser.add_argument("--max-caption", type=int, default=DEFAULT_MAX_CAPTION,
                        metavar="N",
                        help=f"maximum caption length in characters "
                             f"(default {DEFAULT_MAX_CAPTION})")
    args = parser.parse_args(argv)
    if args.max_caption < 1:
        parser.error("--max-caption must be a positive number")

    try:
        with open(args.post_file, encoding="utf-8") as f:
            text = f.read()
    except FileNotFoundError:
        print(format_problems([f"The file {args.post_file} was not found."]))
        return 1
    except UnicodeDecodeError:
        print(format_problems([f"The file {args.post_file} is not UTF-8 text. "
                               "Save it as UTF-8 and try again."]))
        return 1

    problems, post, when = validate(text, args.at, args.max_caption)
    if problems:
        print(format_problems(problems))
        return 1
    print(format_summary(post, when, args.max_caption))
    return 0


if __name__ == "__main__":
    sys.exit(main())
