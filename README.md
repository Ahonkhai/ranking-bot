# 🏆 Telegram Ranking Bot

A group ranking bot where admins control member scores. Generates visual rank cards and leaderboards.

**Each group gets its own independent board.** Add the same bot to as many groups as you like — scores, leaderboards and `/resetboard` are all scoped to the group they're used in, so groups never share or overwrite each other's data.

**Or link a private control group to a public display group.** Edit the rankings in a back-office group and just *show* the leaderboard in the public group — see [Linked groups](#linked-groups-control--display) below.

---

## Setup

### 1. Get a Bot Token
- Message [@BotFather](https://t.me/BotFather) on Telegram
- Send `/newbot` and follow the prompts
- Copy the token you receive

### 2. Install dependencies
```bash
pip install -r requirements.txt
```

### 3. Run
```bash
BOT_TOKEN="your_token_here" python bot.py
```

Or set it permanently in your environment / a `.env` file.

### 4. Add the bot to your group(s)
- Add the bot as a **member** of your group
- Promote it to **admin** so it can fetch the admin list (needed to show 👑 crowns on leaderboard)
- Repeat for any other group — each one starts with a fresh, separate board

---

## Commands

### Member commands
| Command | What it does |
|---------|-------------|
| `/leaderboard` | Shows the full ranked list as an image (admins shown with 👑 at top) |
| `/myrank` | Sends your personal rank card with a progress bar |
| `/rank` | Reply to any member's message to see their rank card |
| `/top3` | Quick text shoutout of the top 3 members |

### Admin-only commands
| Command | What it does |
|---------|-------------|
| `/setcash <amount>` | Reply to a member — sets their score to an exact number |
| `/addcash <amount>` | Reply to a member — adds to their score |
| `/removecash <amount>` | Reply to a member — deducts from their score (floors at 0) |
| `/resetmember` | Reply to a member — zeros out their score |
| `/resetboard` | Wipes all data (asks for confirmation first) |
| `/link` | Get a pairing code so another group can mirror this board |
| `/link <code>` | Make **this** group a view-only mirror of the coded board |
| `/unlink` | Stop mirroring — this group returns to its own board |

---

## Linked groups (control + display)

Want to keep the messy admin work private and only show a clean leaderboard to
everyone? Link a **control group** (where you edit) to one or more **display
groups** (where members just view). They all share one board.

**Setup (both must have the bot added + promoted to admin):**

1. In your **control group** (e.g. your private back group), run `/link`.
   The bot replies with a 6-character pairing code.
2. In your **display group** (e.g. the new public group), run `/link <code>`
   within 10 minutes.

That's it. Now:

- `/setcash`, `/addcash`, etc. work **only in the control group**.
- The display group shows the same `/leaderboard`, `/myrank`, `/rank`, `/top3`
  live — but edit commands there are blocked, so nobody changes scores in public.
- Run `/unlink` in the display group any time to give it back its own board.

One control group can feed several display groups. A group can't mirror itself,
and a group that already has mirrors can't become a mirror.

---

## Data
Scores are stored in `data.json` in the same directory, keyed by group:

```json
{
  "chats": {
    "-1001234567890": { "users": { "<user_id>": { "name": "@handle", "cash": 5000 } } }
  }
}
```

Back this file up if needed.

### Upgrading from a single-group version
Older versions stored one shared board as a flat `{"users": {...}}`. On first run the bot
migrates that automatically. To attach the old scores to your existing group, set
`LEGACY_CHAT_ID` to that group's numeric chat id before starting:

```bash
LEGACY_CHAT_ID="-1001234567890" BOT_TOKEN="..." python bot.py
```

Without it, the old board is preserved under the key `"legacy"` (nothing is lost) and each
group simply starts fresh.

---

## Customisation
At the top of `bot.py`:
```python
CURRENCY = "💰"   # change to any emoji or symbol
```
