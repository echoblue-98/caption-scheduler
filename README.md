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

## Sending a post to n8n: `send_post.py`

`send_post.py` checks a post with `caption_check.py`, then sends it to your n8n webhook. It uses only the standard library.

### Setup

1. Copy `.env.example` to `.env` in the repo root.
2. In `.env`, set `N8N_WEBHOOK_URL` to your n8n webhook URL and `N8N_SECRET` to the shared secret your workflow expects.

`.env` is ignored by git, so your real values stay on your computer. Never put real values in `.env.example`.

### Running it

```sh
python send_post.py examples/sample_post.txt --at "2026-12-01 18:30" --video "https://example.com/clip.mp4"
```

| Option | Meaning |
| --- | --- |
| `--at "YYYY-MM-DD HH:MM"` | Required. The post time, in your computer's local time. The script converts it to UTC. |
| `--video URL` | Required. A public `http://` or `https://` URL of the video. |
| `--dry-run` | Shows the payload and target URL without sending anything. The secret is shown as `****`. |

What the script does:

1. It checks the post with the same rules as `caption_check.py`. If the post fails, it lists the problems, sends nothing and exits with code `1`.
2. It reads `N8N_WEBHOOK_URL` and `N8N_SECRET` from `.env`. If either is missing, it tells you which one and exits with code `1`.
3. It sends a JSON `POST` to the webhook with the header `X-Webhook-Secret: <N8N_SECRET>`. It waits up to 15 seconds for an answer.
4. If the webhook answers with a 2xx status, it prints the reply and exits with code `0`. If the network fails or the webhook answers with any other status, it prints the status code and response body, then exits with code `1`.

The secret is never printed.

### Payload

```json
{
  "title": "Three Pasta Hacks You Need",
  "caption": "Save this for your next busy weeknight! ...",
  "hashtags": ["#pasta", "#cookinghacks", "#easyrecipes", "#dinnerideas", "#foodtok"],
  "text": "Three Pasta Hacks You Need\n\nSave this for your next busy weeknight! ...\n\n#pasta #cookinghacks #easyrecipes #dinnerideas #foodtok",
  "video_url": "https://example.com/clip.mp4",
  "scheduled_time_utc": "2026-12-01T23:30:00Z"
}
```

- `title` has the surrounding double quotes removed.
- `text` is the full text TikTok should show: the title, the caption and the hashtags, separated by blank lines. The short lines are not included.
- `scheduled_time_utc` is `--at` converted from local time to UTC. The example above is for US Eastern time.

## Running the tests

```sh
python -m unittest discover -s tests -v
```
