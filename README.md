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

**4. Add it to your group**, then **promote it to admin**. This is not optional:

- it needs the admin list to draw the 👑 crowns, and
- Telegram's *privacy mode* is on by default, which means a non-admin bot only
  receives commands, replies to itself and mentions — never ordinary chatter.
  Without admin, members are never indexed and `/rank @handle` keeps failing
  for people who have obviously been talking.

Admin bots receive every message regardless of the privacy setting. If you'd
rather not make it an admin, turn privacy off instead: @BotFather →
`/setprivacy` → your bot → **Disable**, then **remove and re-add the bot to the
group** — the setting only applies on re-join.

The bot logs a warning at startup when privacy mode would starve the index, so
check the deploy log if `@handle` lookups aren't finding anyone.

---

## Commands

### Everyone

| Command | What it does |
|---|---|
| `/leaderboard` | The ranked board, paged, with week / month / all-time views |
| `/leaderboard week` | Same board over a time window (`week`, `month`, `alltime`) |
| `/myrank` | Your rank card |
| `/rank` | Your own card; reply to a member for theirs |
| `/rank @user` | Someone else's card by handle |
| `/top3` | Podium image of the top three, with a VIEW ALL button |
| `/history` | Your recent entries and who awarded them |
| `/achievements` | Badge card; reply or `@tag` for someone else's |
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

Members with no ledger entry have no card to draw, so `/rank` roasts them
instead — second person for yourself, third person for anyone else. Someone
legitimately sitting on $0 has an entry and still gets their card; the pool
lives in [`rankbot/roasts.py`](rankbot/roasts.py).

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

### Ties

Standings use standard competition ranking: equal balances share a rank and the
next distinct balance skips the ones consumed (1, 2, 2, 4). The board and the
rank card read from the same function, so a tie never shows two different
numbers in two places.

---

## The rank card

`/myrank` and `/rank` render a portrait card. Every figure on it is derived at
request time — nothing about the card is stored or hardcoded.

| Field | Where it comes from |
|---|---|
| Rank / total | `standings()`, competition-ranked |
| Total cash | Current season balance |
| Green delta | Net cash movement in the rank-change window; hidden when zero |
| Level & title | `levels.py`, from lifetime XP |
| XP bar | `levels.progress_for_xp()` |
| Rank change | Real historical rank from the ledger; `—` when there is no earlier rank |
| Percentile | `ceil(rank / total × 100)`, floored at 1 |
| Joined | First ledger entry, else when the member was first indexed |
| Crown | Rank 1 or a chat admin; everyone else gets their level in the badge |
| Portrait | Telegram profile photo, cached; a gold initial when there is none |

### XP and levels

XP is **not** a second currency to keep in sync. It is the lifetime sum of
every positive ledger entry, read straight off the data that already exists:

```sql
SELECT SUM(delta) FROM ledger WHERE user_id = ? AND delta > 0 AND voided_by IS NULL
```

That makes it monotonic by construction — deducting cash or starting a new
season lowers a balance but never a level — and it needed no new storage.

The curve lives in [`rankbot/levels.py`](rankbot/levels.py):

```python
cumulative_xp_for_level(level)   # total XP to reach a level
xp_required_for_level(level)     # cost of that one level
level_for_xp(xp)                 # inverse, by bisection
progress_for_xp(xp)              # everything the bar needs
```

`level_for_xp` bisects the ladder rather than inverting the formula
algebraically, so retuning `XP_LINEAR` / `XP_QUADRATIC` — or replacing the
curve entirely — needs no matching maths. Titles are the `TITLES` list in the
same module: `(minimum_level, name)` pairs, edit freely.

By default the bar measures progress *within* the current level, so it empties
on every level-up and the two numbers under it are exactly the pair the
percentage is computed from. Set `XP_BAR_CUMULATIVE=1` for lifetime XP against
the next level's full requirement instead.

## The top-three podium

`/top3` renders a podium: second on the left, first raised in the centre under
a laurel wreath and crown, third on the right. Ties keep their shared rank, so
two members level on points both stand on gold.

The laurel is drawn as polygons in `primitives.laurel_wreath()` rather than
taken from a font — arrow and ornament glyph coverage is inconsistent, and a
missing glyph would render as a blank box.

The drawn "VIEW ALL" pill is backed by a real inline button that swaps the
message for the full leaderboard, so it isn't decoration. Like the board, an
unchanged podium is re-sent by `file_id` rather than re-rendered.

---

### Rank change

Derived from the ledger rather than stored as a `previous_rank` snapshot:
`ranks_as_of(chat, scope, cutoff)` replays balances as they stood at any
timestamp. It cannot drift out of sync with the scores, needs no extra writes,
and a member with no entries before the cutoff correctly shows `—` rather than
an invented movement. The window is `RANK_CHANGE_WINDOW_HOURS` (default 24).

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
| `BACKEND_GROUP_ID` | — | Admin group. Set with the next one to share one board. |
| `FRONTEND_GROUP_ID` | — | Public group. Read-only for scores. |
| `ANNOUNCE_IN_FRONTEND` | `1` | Send unlock announcements to the public group. |
| `EXTRA_GROUP_IDS` | — | Comma-separated chat ids that keep their own independent board even while two-group mode is on. |
| `PAGE_SIZE` | `15` | Rows per leaderboard page. |
| `CURRENCY_SYMBOL` | `$` | Printed before amounts on the rendered cards. |
| `XP_LINEAR` | `500` | Linear term of the level curve. |
| `XP_QUADRATIC` | `50` | Quadratic term of the level curve. |
| `XP_BAR_CUMULATIVE` | `0` | `1` shows lifetime XP against the next level's total. |
| `RANK_CHANGE_WINDOW_HOURS` | `24` | How far back ↑/↓ movement looks. |
| `COOLDOWN_SECONDS` | `4` | Per-user cooldown on the image commands. |
| `RENDER_CONCURRENCY` | `3` | Simultaneous PIL renders. |
| `ADMIN_TTL` | `300` | Admin-list cache lifetime. Invalidated instantly on promote/demote anyway. |
| `AVATAR_TTL` | `3600` | Avatar cache lifetime. |
| `AVATAR_RETRY_SECONDS` | `90` | Backoff after a failed photo download, before retrying. |
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

## Achievements

**Cash**

| | Achievement | Reach |
|---|---|---|
| 💵 | First Bag | $1,000 |
| 💰 | Four Figures | $5,000 |
| 🤑 | High Roller | $10,000 |
| 💎 | Big Money | $25,000 |
| 🏦 | Money Maker | $50,000 |
| 👑 | Six Figures | $100,000 |
| 🐋 | Whale | $250,000 |
| 💠 | Mega Whale | $500,000 |
| 🏛️ | Millionaire | $1,000,000 |

**Rank**

| | Achievement | Requirement | Needs a board of |
|---|---|---|---|
| 🥉 | Top 10 | Reach the top 10 | 10+ |
| 🥈 | Top 5 | Reach the top 5 | 5+ |
| 🥇 | Podium | Reach the top 3 | 3+ |
| ⚔️ | Challenger | Reach #2 | 2+ |
| 👑 | Number One | Reach #1 | 2+ |
| 🏆 | Champion | Hold #1 for `CHAMPION_DAYS` (default 7) | 2+ |

Rank tiers require a board big enough for them to mean something — otherwise
every member of a four-person chat instantly earns Top 10 and Top 5, which is
noise rather than an achievement. Being #1 of one earns nothing at all.

Edit the `CASH_TIERS` and `RANK_TIERS` lists in
[`rankbot/achievements.py`](rankbot/achievements.py) to retune them. The `code`
on each tier is what gets stored, so emoji, wording, values and rarity can all
change freely — but never rename a code that has already been awarded, or those
unlocks are orphaned.

### How it works

An unlock is the one thing in this bot that is **recorded rather than derived**.
Everything else is a query over the ledger, but "have we already told the group
about this?" isn't in the ledger, and re-announcing every time a balance wobbles
across a threshold would be worse than storing one row. The table's primary key
is `(chat_id, user_id, code)`, which makes a double-announce impossible even if
two awards race.

**Champion** is the exception that needs no new state either: `held_rank_since()`
samples `ranks_as_of()` at daily checkpoints across the window, so a "holding"
streak is reconstructed from the ledger rather than tracked in a column that
could drift. A board younger than the window correctly fails — you can't have
held #1 for a week if the board is two days old.

Consequences worth knowing:

- One award can unlock several tiers at once, but only the **highest by rarity**
  is announced. `/setcash 400000` says "Whale", or "Number One" if it also took
  the top spot — reaching #1 is the story, the cash tier is a footnote. The rest
  are recorded and show up in `/achievements`.
- Badges are permanent. A deduction, an `/undo`, being overtaken, or a new season
  never takes one back, and re-earning it stays quiet.
- After any award the **top of the board is swept**, not just whoever an admin
  targeted: a rank can improve because someone above was reset or overtaken by a
  third party. Those awards are made **silently** — when a board grows past a
  tier's size requirement every member in it qualifies at the same instant, and
  announcing that is a wall of identical lines rather than news. Only the member
  an admin actually acted on gets a message.
- Champion is checked by a **daily job**, since no write would ever trigger a
  milestone that comes true purely with the passage of time. It is the only
  thing that job announces.

---

## Profile photos

Not every member will show a photo, and there are two different reasons:

- **They have none, or Telegram won't share it.** Profile photo privacy is a
  per-user setting; `getUserProfilePhotos` simply returns nothing for those
  members. The bot draws a gold initial instead. Nothing to fix.
- **The download failed.** Transient, and now handled: the failure is cached
  for `AVATAR_RETRY_SECONDS` (90s) rather than as "this member has no photo"
  for the full `AVATAR_TTL` hour, and a board or podium rendered while a photo
  was missing is **not** written to the `file_id` cache — otherwise one blip
  freezes the initials into that image for hours after the problem clears.

If someone's photo is persistently missing while others load, it's the first
reason. `rankbot.avatars` logs failures at INFO with the exception type, so
the deploy log distinguishes them.

---

## Two-group mode

One private community split across an admin group and a public one, over a
single set of scores.

```
BACKEND_GROUP_ID=-100123456789     # admins manage scores here
FRONTEND_GROUP_ID=-100987654321    # members view them here
```

Set both and:

- **Both groups resolve to one board.** `config.board_for()` maps either chat
  id to the backend's, so there is exactly one ledger, one ranking, one set of
  achievements. An edit in the admin group is visible in the public group on
  the next command — no sync, because there is nothing to sync.
- **Score-changing commands are refused outside the admin group.** The location
  check runs *before* the existing admin authorization, never instead of it, so
  being an admin of the public group confers nothing.
- **Unconfigured groups are turned away** with "This bot isn't configured for
  this group", so the board can't be read or written from anywhere else.
- **Unlock announcements go to the public group**, since that's where they're
  news. Set `ANNOUNCE_IN_FRONTEND=0` to keep them where the command was typed.
- **Cached board images are invalidated for both chats** on any write. Without
  that, an admin edit would leave the public group showing the old picture.

Leave both unset and nothing changes: every chat keeps its own independent
board, exactly as before.

### Adding a second, unrelated group

Turning on two-group mode locks out every other chat by default — "This bot
isn't configured for this group" — since an unrecognised group being read or
written to is more often a mistake than an intentional third community.

To add a group with its **own separate board**, not connected to the
backend/frontend pair, list it in `EXTRA_GROUP_IDS`:

```
EXTRA_GROUP_IDS=-100333333333               # one extra group
EXTRA_GROUP_IDS=-100333333333,-100444444444 # or several
```

That chat behaves exactly like a single-group deployment: its own admins can
run every command there, scores stay local to it, and nothing about it is
merged with or visible from the backend/frontend board. Use `/chatid` in it
to confirm it's recognised.

### Switching it on later

If the bot has already been running in both chats they will have separate
scores. The first boot after configuring them merges the frontend's rows into
the shared board — ledger entries interleave by timestamp, achievements already
held win, and the earlier `joined_at` is kept so appearing in the second group
never looks like a newer arrival. It is idempotent, so later boots do nothing.

---

## Persistence

**The database must live on a mounted volume or every redeploy starts from an
empty board.** This is the single most common way to lose a leaderboard, and
nothing about it raises an error — SQLite happily writes to the container
filesystem right up until the container is replaced.

On **Railway**, volumes are created from the project canvas, not from the
service's Settings tab (there is no Volumes section there): right-click the
service card → *Attach Volume*, or Ctrl/Cmd+K → `volume`, or the `+ Create`
button → *Volume*. Then pick the service and give it a mount path.

The mount path does not matter — the bot reads `RAILWAY_VOLUME_MOUNT_PATH` and
puts `rankbot.db` there automatically, overriding whatever `DB_PATH` says.
Confirm it worked by checking the service's Variables tab for
`RAILWAY_VOLUME_MOUNT_PATH`. Without a volume the bot logs a loud warning at
every boot.

On **plain Docker**: `-v ranking_data:/data`, matching `DB_PATH`.

The startup line tells you which you got:

```
database ready at /data/rankbot.db (schema v2, persistent volume /data, existing)
database ready at /data/rankbot.db (schema v2, local filesystem, newly created)
```

The second one is the one that loses your scores.

---

## Docker

```bash
docker build -t ranking-bot .
docker run -d --name ranking-bot \
  -e BOT_TOKEN="your_token_here" \
  -v ranking_data:/data \
  ranking-bot
```

The mount holds `/data/rankbot.db` and `/data/backups/`.

The Dockerfile deliberately has no `VOLUME` instruction — Railway's Metal
builder rejects it and fails the build. Mount `/data` explicitly instead: a
Railway Volume with mount path `/data`, or `-v` as above.

The container starts as root so the entrypoint can take ownership of that
mount, then drops to an unprivileged user. Attaching a volume that already has
data means it arrives root-owned, and a build-time `USER` would be locked out
of it.

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
  db.py             connection + schema (versioned, self-migrating)
  store.py          ledger operations — balances, ranks, seasons, undo, transfers
  levels.py         XP curve, levels, member titles
  cards.py          assembles a RankCard value object for the renderer
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

The renderer receives a finished `RankCard` and looks nothing up itself, so
two members requesting at once cannot bleed data onto each other's card —
there is a test that renders from a thread pool and asserts exactly that.
