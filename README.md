# 🏆 Telegram Ranking Bot

A group ranking bot where admins control member scores. Generates visual rank cards and leaderboards.

**Each group gets its own independent board.** Add the same bot to as many groups as you like — scores, leaderboards and `/resetboard` are all scoped to the group they're used in, so groups never share or overwrite each other's data.

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
