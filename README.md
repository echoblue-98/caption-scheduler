# caption-scheduler
Schedule TikTok captions and hashtags through the Blotato API, using an n8n workflow.

## Checking a post before scheduling: `caption_check.py`

`caption_check.py` checks a post file before it gets scheduled. It needs Python 3.10 or newer and uses only the standard library. It makes no network calls and needs no API keys.

### Post file format

```text
"Three Pasta Hacks You Need"
Dinner in 10 minutes.
No fancy tools required.
Caption: Save this for your next busy weeknight! ...
Hashtags: #pasta #cookinghacks #easyrecipes #dinnerideas #foodtok
```

- **Line 1:** the title, in straight double quotes (`"`). Curly quotes like `“ ”` are rejected.
- **Next lines:** optional short caption lines.
- **`Caption:`**: the main caption. Lines after it, up to `Hashtags:`, count as part of the caption.
- **`Hashtags:`**: separate hashtags with spaces or commas.

The file must be saved as UTF-8. There's a full example in [`examples/sample_post.txt`](examples/sample_post.txt).

### Running it

```sh
python caption_check.py examples/sample_post.txt --at "2026-12-01 18:30"
```

| Option | Meaning |
| --- | --- |
| `--at "YYYY-MM-DD HH:MM"` | Required. The post time, in your computer's local time. It must be in the future. |
| `--max-caption N` | The longest the caption can be, in characters. Default: 2200. |

### Checks

1. The title is on line 1 and wrapped in double quotes.
2. The `Caption:` and `Hashtags:` sections are both present and not empty.
3. The post has no parentheses anywhere. This includes full-width `（ ）`.
4. The caption is at most `--max-caption` characters. Only the `Caption:` section counts. The title, short lines and hashtags don't.
5. The post has 3 to 8 hashtags. Each one starts with `#` and has no spaces in it.
6. The post time is a real date and time, and it's in the future.

### Output

If the post passes, you get a summary and exit code `0`:

```text
PASS
  Title:       "Three Pasta Hacks You Need"
  Short lines: 2
  Caption:     132/2200 characters
  Hashtags:    5 - #pasta #cookinghacks #easyrecipes #dinnerideas #foodtok
  Post time:   2026-12-01 18:30
```

If it fails, you get a numbered list of every problem and exit code `1`:

```text
FAIL: 2 problems found
1. Parentheses are not allowed. Remove them from line 2.
2. The post time 2020-01-01 10:00 is not in the future. Pick a later time.
```

If the command itself is wrong, for example `--at` is missing, you get exit code `2`.

### Running the tests

```sh
python -m unittest discover -s tests -v
```
