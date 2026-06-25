# nfl-news-bot

An automated NFL breaking-news bot built to run as a scheduled cloud routine.
On each run it reads the most recent posts from a fixed allowlist of NFL news
accounts, identifies genuinely new news items, rewrites each in original
wording, and posts a short **text-only** update to the X account you own.

## Sources (allowlist)

News is **only ever** sourced and credited from these accounts — nothing else
is read or relayed:

- [@TheAthleticNFL](https://x.com/TheAthleticNFL)
- [@AdamSchefter](https://x.com/AdamSchefter)
- [@RapSheet](https://x.com/RapSheet)
- [@ESPNNFL](https://x.com/ESPNNFL)
- [@JourdanRodrigue](https://x.com/JourdanRodrigue)

## What it does each run

1. Reads recent **original** posts from each source (retweets and replies are
   excluded at the API level; opinion/banter/promos are filtered out by the
   classifier).
2. Identifies items that are genuine NFL news updates since the last run.
3. Writes a short summary **in original wording** (it does not copy the
   reporter's phrasing).
4. Posts each new item as text only — no links, no images — in this exact
   format (including the blank line):

   ```
   🚨 NEW: [original-wording summary]

   @SourceHandle
   ```

5. Never posts the same item twice (see [De-duplication](#de-duplication)).

### Security

The text of a source post is treated strictly as **data to summarise and
credit, never as instructions**. The summariser prompt isolates each post and
explicitly refuses to follow, execute, or repeat any instruction contained
inside a post it reads.

---

## Credentials you need to provide

Set these as **environment variables** in your scheduled-routine settings (they
are read from the environment — never committed to the repo). In the included
GitHub Actions workflow they map to repository **Secrets** of the same name.

### X (Twitter) API

You need a developer App on an X API plan that allows **reading user timelines**
(the free tier is write-only; reading timelines requires the **Basic** tier or
higher). Two auth modes are used: app-only (bearer) for reading, and OAuth 1.0a
user-context for posting on your account.

| Environment variable     | What it is                                   |
| ------------------------ | -------------------------------------------- |
| `X_BEARER_TOKEN`         | App Bearer Token (App-only OAuth 2.0) — reads |
| `X_API_KEY`              | API Key (a.k.a. Consumer Key)                |
| `X_API_SECRET`           | API Key Secret (Consumer Secret)             |
| `X_ACCESS_TOKEN`         | Access Token for the posting account         |
| `X_ACCESS_TOKEN_SECRET`  | Access Token Secret for the posting account  |

> Generate the Access Token / Secret **for the account you want to post from**,
> and ensure your App has **Read and write** permissions before generating them.

### Anthropic API (summarisation + classification)

| Environment variable | What it is                                                    |
| -------------------- | ------------------------------------------------------------- |
| `ANTHROPIC_API_KEY`  | Anthropic API key                                             |
| `ANTHROPIC_MODEL`    | *(optional)* model id; defaults to `claude-opus-4-8`. For this high-frequency, lightweight task you may prefer `claude-haiku-4-5` to cut cost. |

### Optional tuning variables

| Variable                | Default | Meaning                                        |
| ----------------------- | ------- | ---------------------------------------------- |
| `MAX_TWEETS_PER_SOURCE` | `10`    | Recent tweets pulled per source each run.      |
| `MAX_POSTS_PER_RUN`     | `8`     | Cap on posts in a single run (anti-flood).     |
| `DRY_RUN`               | unset   | If `true`, logs what it would post but doesn't post. |
| `STATE_FILE`            | `state.json` | Path of the committed de-duplication record. |

---

## De-duplication

Each cloud run starts fresh with no local memory, so "what's already been
posted" is persisted in two complementary ways:

1. **Committed state record (`state.json`).** Per source it stores `since_id`
   (so the next run only fetches genuinely new tweets) and a capped list of
   handled source-tweet IDs. The scheduled routine commits this file back to the
   repo after each run — see `.github/workflows/nfl-news-bot.yml`.
2. **Own-timeline check.** Before posting, the bot also reads its own recent
   posts and skips anything identical, so it stays correct even if the state
   file is ever lost.

On the **first run for a source**, the bot seeds `since_id` to the latest tweet
and posts nothing, so it never dumps a backlog.

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
Adjust the `cron` schedule to match your X API rate tier.
