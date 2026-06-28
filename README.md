# nfl-news-bot

An automated NFL breaking-news bot built to run as a scheduled cloud routine.
On each run it reads a broad set of **NFL RSS feeds**, clusters items into
distinct stories, identifies genuinely new news, rewrites each in original
wording, and posts a short **text-only** update to the X account you own.

## News source: RSS feeds

News is sourced from public RSS feeds (free to read). The list aims for broad,
all-32-teams coverage: national outlets for headline news plus a team beat feed
("Wire" network) for every franchise, which is where granular camp/roster detail
shows up. The X API is used **only to post**, never to read news.

See [Feed list](#feed-list) below for the exact feeds, and `nflbot/feeds.py` to
edit them — individual feeds being unreachable or junk never sinks a run.

## What it does each run

1. Fetches all configured RSS feeds and collects items not seen before.
2. **Clusters items by story.** The same news appears across many feeds (ESPN,
   the team site, a beat blog may all carry it). These are grouped and treated
   as ONE story — a story is never posted twice just because two feeds carried
   it. Clustering is lexical (title-token similarity), so it's tunable, not
   perfect; refine `STORY_SIMILARITY_THRESHOLD` after watching it run.
3. For each distinct new story, `claude-haiku-4-5` (in one call) classifies it
   (real NFL news vs. opinion/list/ad/filler), assigns a **category** and a
   **significance score (1–10)**, and writes a short summary **in original
   wording** (it does not copy the outlet's phrasing).
4. Composes the post text only — no links, no images — in this format (including
   the blank line):

   ```
   🚨 SIGNING: [original-wording summary, #Team-tagged]

   [@handle]
   ```

   - **Topic prefix** by category: `🚨 TRADE:`, `🚨 SIGNING:`, `🚨 INJURY:`,
     `🚨 SUSPENSION:`, `🚨 ROSTER NEWS:`, `🚨 COACHING:`, or `🚨 NEWS:` (fallback).
   - **Team names → hashtagged nicknames** (e.g. "Pittsburgh Steelers" → `#Steelers`).
     Ambiguous bare cities ("New York", "Los Angeles") and lowercase words are
     left as plain text rather than guessed.
   - **Credit tags the outlet's X handle in brackets** (e.g. `[@espn]`,
     `[@PFRumors]`); an outlet with no known handle falls back to `[Outlet]`.
   - **Hard length limit (≤270, X-weighted):** the summary is written to fit, and
     if a composed post still exceeds the limit Haiku rewrites it shorter. A post
     that can't be made to fit is skipped — **never truncated/cut off**.
5. **Queues approved posts and releases them gradually.** Newsworthy stories are
   written to a persistent queue (in `state.json`); each run releases only 1–2
   posts, **most-significant first**, so posts stagger across the ~30-min runs
   instead of dumping at once. A story already queued (or already posted) is
   never re-queued. Stale queued items (>3h) are dropped (freshness guard).
6. **Caps output at 10 posts per day.** Releases count toward the cap; because
   the queue is drained best-first, the most important news goes out and
   low-value items age out of the queue under the cap.

### Security

Feed content (title + description) is treated strictly as **data to summarise
and credit, never as instructions**. The classification/scoring/summarising and
shortening prompts isolate feed text and explicitly refuse to follow, execute,
or repeat any instruction contained inside it.

---

## Credentials you need to provide

Set these as **environment variables** in your scheduled-routine settings (read
from the environment — never committed to the repo). In the included GitHub
Actions workflow they map to repository **Secrets** of the same name.

### X (Twitter) API — posting only

Posting uses OAuth 1.0a user-context auth. (Reading source timelines is no
longer needed, so the bearer token is gone.) Reading news is RSS, which needs no
credentials.

| Environment variable    | What it is                                  |
| ----------------------- | ------------------------------------------- |
| `X_API_KEY`             | API Key (a.k.a. Consumer Key)               |
| `X_API_SECRET`          | API Key Secret (Consumer Secret)            |
| `X_ACCESS_TOKEN`        | Access Token for the posting account        |
| `X_ACCESS_TOKEN_SECRET` | Access Token Secret for the posting account |

> Generate the Access Token / Secret **for the account you want to post from**,
> with the App set to **Read and write** before generating them.

### Anthropic API (classification + summarisation + ranking)

| Environment variable | What it is                                                   |
| -------------------- | ------------------------------------------------------------ |
| `ANTHROPIC_API_KEY`  | Anthropic API key                                            |
| `ANTHROPIC_MODEL`    | *(optional)* model id; defaults to `claude-haiku-4-5`.       |

### Optional tuning variables

| Variable                     | Default | Meaning                                          |
| ---------------------------- | ------- | ------------------------------------------------ |
| `MAX_ITEMS_PER_FEED`         | `25`    | Newest items considered per feed each run.       |
| `MAX_POSTS_PER_DAY`          | `10`    | Hard cap on posts per UTC calendar day.          |
| `RELEASE_PER_RUN`            | `2`     | Posts released from the queue per run (staggering). |
| `QUEUE_TTL_HOURS`            | `3`     | Drop queued posts older than this (freshness guard). |
| `MAX_TOTAL_CHARS`            | `270`   | Hard ceiling on total post length (X-weighted).  |
| `SUMMARY_TARGET_CHARS`       | `200`   | Summary length hint passed to Haiku.             |
| `STORY_SIMILARITY_THRESHOLD` | `0.4`   | Overlap-coefficient threshold for "same story".  |
| `DRY_RUN`                    | unset   | If `true`, logs what it would post but doesn't post. |
| `STATE_FILE`                 | `state.json` | Path of the committed de-duplication record. |

---

## De-duplication

Each cloud run starts fresh with no local memory, so what's already been handled
is persisted in `state.json`, which the routine commits back to the repo (see
`.github/workflows/nfl-news-bot.yml`). It now tracks:

1. **Seen feed items** — UIDs of raw feed entries already processed, so the same
   item is never reconsidered.
2. **Posted stories (keyed by story, not tweet ID)** — token fingerprints of
   stories already posted, compared with the same similarity used for
   clustering, so the same story isn't reposted on a later run even when a
   different feed carries it.
3. **Daily counter** — posts made per UTC day, enforcing the 10/day cap.

There's also an **own-timeline check**: before posting, the bot reads its own
recent posts and skips anything identical, so it stays correct even if the state
file is lost.

On the **first run**, the bot records the current backlog and posts nothing, so
it never dumps history.

---

## Feed list

Edit in `nflbot/feeds.py`. Only feeds confirmed to return live content are
listed — the bot runs against these.

**Nationals-only launch.** `FEEDS` is the national set confirmed working on the
latest verify run:

- ProFootballTalk, Yahoo Sports, Pro Football Rumors, CBS Sports NFL — confirmed working
- ESPN — kept in but **on watch**: it returned empty (HTTP 202) on the latest run
  though it has worked before. The bot skips empty feeds gracefully; drop it if it
  stays empty.

The USA TODAY "Wire" per-team feeds, NFL.com, and the Reddit/SI team-beat
candidates all returned no entries from the runner and are not included (dead
URLs dropped rather than left in). Per-team coverage can be added later once
working feeds are found.

### Adding / verifying feeds

Feed liveness can only be checked from an environment with real outbound network
(the Actions runner), so there's a diagnostic workflow for it:

1. Actions tab → **Verify feeds** → **Run workflow**.
2. It fetches each candidate in `scripts/verify_feeds.py` and prints a table:
   `STATUS | N | NEWEST | OUTLET | URL`.
3. Promote the feeds that return content into `FEEDS` in `nflbot/feeds.py`; drop
   the rest.

The candidate list probes several families of per-team beat source (USA TODAY
Wire variants, Reddit team subs, SI team sites) with sample teams, so one run
reveals which family works from the runner's IP — then expand the winner to all
32 teams.

---

## Running

Locally (with the env vars exported):

```bash
pip install -r requirements.txt
DRY_RUN=true python -m nflbot.bot   # see what it would post, without posting
python -m nflbot.bot                # real run
```

In the cloud: the included GitHub Actions workflow runs every 15 minutes,
executes `python -m nflbot.bot`, and commits the updated `state.json`. Add the
secrets listed above under **Settings → Secrets and variables → Actions**.
