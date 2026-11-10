import contextlib
import io
import os
import sys
import tempfile
import unittest
from datetime import datetime

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import caption_check as cc  # noqa: E402

NOW = datetime(2026, 11, 10, 12, 0)
FUTURE = "2026-11-11 09:30"
GOOD = (
    '"My Video Title"\n'
    "Short line one\n"
    "Short line two\n"
    "Caption: This is the caption.\n"
    "Hashtags: #one #two #three\n"
)
SAMPLE = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                      "examples", "sample_post.txt")


def problems(text=GOOD, at=FUTURE, max_caption=cc.DEFAULT_MAX_CAPTION):
    return cc.validate(text, at, max_caption, now=NOW)[0]


class ParseTests(unittest.TestCase):
    def test_parses_all_sections(self):
        post = cc.parse_post(GOOD)
        self.assertEqual(post.title, '"My Video Title"')
        self.assertEqual(post.short_lines, ["Short line one", "Short line two"])
        self.assertEqual(post.caption, "This is the caption.")
        self.assertEqual(post.hashtags_raw, "#one #two #three")

    def test_multiline_caption_and_bom(self):
        text = '﻿"T"\nCaption: first\nsecond\nHashtags: #a #b #c'
        post = cc.parse_post(text)
        self.assertEqual(post.title, '"T"')
        self.assertEqual(post.caption, "first\nsecond")

    def test_labels_case_insensitive(self):
        post = cc.parse_post('"T"\ncaption: hi\nHASHTAGS: #a #b #c')
        self.assertEqual(post.caption, "hi")
        self.assertEqual(post.hashtags_raw, "#a #b #c")


class ValidateTests(unittest.TestCase):
    def test_good_post_passes(self):
        self.assertEqual(problems(), [])

    def test_sample_file_passes(self):
        with open(SAMPLE, encoding="utf-8") as f:
            self.assertEqual(problems(f.read()), [])

    # Title
    def test_title_without_quotes(self):
        p = problems(GOOD.replace('"My Video Title"', "My Video Title"))
        self.assertEqual(len(p), 1)
        self.assertIn("double quotes", p[0])

    def test_title_half_quoted(self):
        p = problems(GOOD.replace('"My Video Title"', '"My Video Title'))
        self.assertIn("double quotes", p[0])

    def test_title_smart_quotes(self):
        p = problems(GOOD.replace('"My Video Title"', "“My Video Title”"))
        self.assertIn("smart", p[0])

    def test_title_empty_quotes(self):
        p = problems(GOOD.replace('"My Video Title"', '""'))
        self.assertIn("empty", p[0])

    def test_title_missing_entirely(self):
        p = problems("Caption: hi\nHashtags: #a #b #c")
        self.assertTrue(any("Line 1 should be the title" in x for x in p))

    def test_empty_file(self):
        p = problems("")
        self.assertTrue(any("empty" in x for x in p))
        self.assertTrue(any("Caption" in x for x in p))
        self.assertTrue(any("Hashtags" in x for x in p))

    # Sections
    def test_missing_caption(self):
        p = problems(GOOD.replace("Caption: This is the caption.\n", ""))
        self.assertEqual(p, ['The "Caption:" line is missing or empty.'])

    def test_empty_caption(self):
        p = problems(GOOD.replace("Caption: This is the caption.", "Caption:"))
        self.assertEqual(p, ['The "Caption:" line is missing or empty.'])

    def test_missing_hashtags(self):
        p = problems(GOOD.replace("Hashtags: #one #two #three\n", ""))
        self.assertEqual(p, ['The "Hashtags:" line is missing or empty.'])

    # Parentheses
    def test_parentheses_reported_with_lines(self):
        text = GOOD.replace("Short line one", "Short (line) one").replace(
            "the caption.", "the caption :)")
        p = problems(text)
        self.assertEqual(len(p), 1)
        self.assertIn("lines 2, 4", p[0])

    def test_parenthesis_in_title(self):
        p = problems(GOOD.replace("My Video", "My (Video)"))
        self.assertIn("line 1", p[0])

    def test_fullwidth_parenthesis(self):
        p = problems(GOOD.replace("Short line one", "Short （one）"))
        self.assertIn("Parentheses", p[0])

    # Caption length
    def test_caption_at_limit_passes(self):
        text = GOOD.replace("This is the caption.", "x" * 50)
        self.assertEqual(problems(text, max_caption=50), [])

    def test_caption_over_limit(self):
        text = GOOD.replace("This is the caption.", "x" * 51)
        p = problems(text, max_caption=50)
        self.assertEqual(len(p), 1)
        self.assertIn("51 characters", p[0])

    def test_default_limit_is_2200(self):
        ok = GOOD.replace("This is the caption.", "x" * 2200)
        bad = GOOD.replace("This is the caption.", "x" * 2201)
        self.assertEqual(problems(ok), [])
        self.assertEqual(len(problems(bad)), 1)

    # Hashtags
    def _tags(self, tags):
        return problems(GOOD.replace("#one #two #three", tags))

    def test_hashtag_count_bounds(self):
        self.assertEqual(self._tags("#a #b #c"), [])
        self.assertEqual(self._tags(" ".join(f"#t{i}" for i in range(8))), [])
        self.assertIn("This post has 2", self._tags("#a #b")[0])
        self.assertIn("This post has 9",
                      self._tags(" ".join(f"#t{i}" for i in range(9)))[0])

    def test_hashtags_comma_separated(self):
        self.assertEqual(self._tags("#a, #b, #c"), [])

    def test_hashtag_without_hash(self):
        p = self._tags("#a b #c #d")
        self.assertEqual(len(p), 1)
        self.assertIn("b", p[0])

    def test_hashtag_with_space(self):
        p = self._tags("#cooking hacks #a #b")
        self.assertIn("hacks", p[0])

    def test_hashtags_run_together(self):
        p = self._tags("#a#b #c #d")
        self.assertIn("#a#b", p[0])

    def test_bare_hash(self):
        self.assertIn("#", self._tags("# #a #b #c")[0])

    # Post time
    def test_invalid_time_format(self):
        for bad in ["tomorrow", "2026-11-11", "11/11/2026 09:30", "2026-02-30 10:00",
                    "2026-11-11 25:00"]:
            p = problems(at=bad)
            self.assertEqual(len(p), 1, bad)
            self.assertIn("not a valid date", p[0])

    def test_time_in_past(self):
        p = problems(at="2026-11-10 11:59")
        self.assertIn("not in the future", p[0])

    def test_time_exactly_now_fails(self):
        self.assertEqual(len(problems(at="2026-11-10 12:00")), 1)

    def test_multiple_problems_all_reported(self):
        text = "Title\nCaption: (hi)\nHashtags: #a"
        p = problems(text, at="2020-01-01 00:00")
        self.assertEqual(len(p), 4)


class CliTests(unittest.TestCase):
    def run_cli(self, *args):
        out = io.StringIO()
        with contextlib.redirect_stdout(out):
            code = cc.main(list(args))
        return code, out.getvalue()

    def write(self, text):
        fd, path = tempfile.mkstemp(suffix=".txt")
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            f.write(text)
        self.addCleanup(os.remove, path)
        return path

    def test_pass_output(self):
        code, out = self.run_cli(self.write(GOOD), "--at", "2099-01-01 10:00")
        self.assertEqual(code, 0)
        self.assertTrue(out.startswith("PASS"))
        self.assertIn("3 - #one #two #three", out)

    def test_fail_output_numbered(self):
        code, out = self.run_cli(self.write("no quotes\nCaption: x"),
                                 "--at", "2099-01-01 10:00")
        self.assertEqual(code, 1)
        self.assertIn("FAIL: 2 problems found", out)
        self.assertIn("\n1. ", out)
        self.assertIn("\n2. ", out)

    def test_max_caption_flag(self):
        code, out = self.run_cli(self.write(GOOD), "--at", "2099-01-01 10:00",
                                 "--max-caption", "5")
        self.assertEqual(code, 1)
        self.assertIn("limit is 5", out)

    def test_missing_file(self):
        code, out = self.run_cli("does_not_exist.txt", "--at", "2099-01-01 10:00")
        self.assertEqual(code, 1)
        self.assertIn("not found", out)


if __name__ == "__main__":
    unittest.main()
