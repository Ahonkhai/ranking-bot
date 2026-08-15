# 🏆 Telegram Ranking Bot

Per-chat leaderboards where admins award points, rendered as metallic rank
cards and boards. Balances are derived from an append-only ledger, so every
entry is recoverable, auditable and undoable.

---

## Setup

**1. Get a token** — message [@BotFather](https://t.me/BotFather), send
`/newbot`, copy the token.

**2. Install**

```bash
pip install -r requirements.txt
```

**3. Run**

```bash
BOT_TOKEN="your_token_here" python bot.py
```

**4. Add it to your group** as a member, then promote it to **admin** so it can
read the admin list (for the 👑 crowns) and see messages (for member indexing).

---

## Commands

### Everyone

| Command | What it does |
|---|---|
| `/leaderboard` | The ranked board, paged, with week / month / all-time views |
| `/leaderboard week` | Same board over a time window (`week`, `month`, `alltime`) |
| `/myrank` | Your rank card |
| `/rank @user` | Someone else's card |
| `/top3` | Quick text shoutout |
| `/history` | Your recent entries and who awarded them |
| `/give 500 @user` | Send some of your own points (set `ALLOW_TRANSFERS=0` to disable) |
| `/stats` | Season summary |

### Admins

| Command | What it does |
|---|---|
| `/addcash 500 @user` | Add to a member |
| `/removecash 500 @user` | Deduct, flooring at 0 |
| `/setcash 5000 @user` | Set an exact amount |
| `/resetmember @user` | Zero someone out |
| `/undo` | Reverse the last entry in the chat |
| `/newseason` | Close the season, start the next, keep all history |
| `/resetboard` | Choose a season reset or a permanent wipe |
| `/adoptlegacy` | One-shot import of an old `data.json` into this chat |

Every command works as a **reply** to the member's message, which is the most
reliable way to name someone — handles change, replies don't. Amounts accept
`5000`, `5,000`, `5k`, `2.5k` and `1m`.

---

## How scores are stored

A balance is never written down. It is `SUM(delta)` over that member's
non-voided rows in the `ledger` table, so:

- nothing overwrites anything, and a bad write can't destroy an earlier one;
- `/undo` flags rows rather than deleting them, and the reversal itself is
  recorded;
- `/history`, week/month boards, seasons and the "peak balance" chip are all
  queries over data that was already there.

`/setcash 400` on someone holding 1000 is stored as a `-600` entry, not as an
overwrite.

### Migrating from the old `data.json`

The legacy format had no chat id, so the target chat has to be named:

```bash
python -m rankbot.migrate --chat -1001234567890 --dry-run   # preview
python -m rankbot.migrate --chat -1001234567890
```

Or run `/adoptlegacy` as an admin in the group the scores belong to. Either
way it refuses to run twice against a chat that already has entries.

---

## Configuration

All optional except the token.

| Variable | Default | Meaning |
|---|---|---|
| `BOT_TOKEN` | — | **Required.** |
| `DB_PATH` | `data.db` | SQLite file. Put it on a mounted volume in production. |
| `DATA_FILE` | `data.json` | Legacy file, only read by the import. |
| `PAGE_SIZE` | `15` | Rows per leaderboard page. |
| `ALLOW_TRANSFERS` | `1` | Enables `/give`. |
| `COOLDOWN_SECONDS` | `4` | Per-user cooldown on the image commands. |
| `RENDER_CONCURRENCY` | `3` | Simultaneous PIL renders. |
| `ADMIN_TTL` | `300` | Admin-list cache lifetime. Invalidated instantly on promote/demote anyway. |
| `AVATAR_TTL` | `3600` | Avatar cache lifetime. |
| `BACKUP_INTERVAL_HOURS` | `6` | Snapshot cadence. |
| `BACKUP_KEEP` | `24` | Snapshots retained on disk. |
| `BACKUP_CHANNEL_ID` | — | Send snapshots and a daily digest here. Set this — an on-disk backup dies with the machine. |
| `DECAY_PERCENT` | `0` | Weekly bleed for inactive members. `0` disables it. |
| `DECAY_IDLE_DAYS` | `14` | How long counts as inactive. |
| `DROP_PENDING_UPDATES` | `0` | `1` discards commands sent while the bot was down. |
| `LOG_LEVEL` | `INFO` | |
| `SENTRY_DSN` | — | Enables Sentry if `sentry-sdk` is installed. |
| `ALLOW_MULTIPLE_INSTANCES` | `0` | Bypasses the single-instance lock. Don't. |

---

## Docker

```bash
docker build -t ranking-bot .
docker run -d --name ranking-bot \
  -e BOT_TOKEN="your_token_here" \
  -v ranking_data:/data \
  ranking-bot
```

The volume holds `/data/rankbot.db` and `/data/backups/`.

---

## Development

```bash
pip install -r requirements-dev.txt
python -m pytest tests/ -q
```

Layout:

```
bot.py              entrypoint
rankbot/
  config.py         every environment variable
  db.py             connection + schema
  store.py          ledger operations — balances, seasons, undo, transfers
  migrate.py        data.json import
  identity.py       target resolution and HTML escaping
  caches.py         admin / avatar / board-image caches
  avatars.py        profile photo fetching
  jobs.py           backups, digest, decay
  app.py            handler registration and startup
  render/           palette, primitives, avatar, card, board
  handlers/         common, public, admin, boards, passive
tests/
```
