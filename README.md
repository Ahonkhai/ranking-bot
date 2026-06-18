# 🏆 Telegram Ranking Bot

A group ranking bot where admins control member scores. Generates visual rank cards and leaderboards.

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

### 4. Add the bot to your group
- Add the bot as a **member** of your group
- Promote it to **admin** so it can fetch the admin list (needed to show 👑 crowns on leaderboard)

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
Scores are stored in `data.json` in the same directory. Back this file up if needed.

---

## Customisation
At the top of `bot.py`:
```python
CURRENCY = "💰"   # change to any emoji or symbol
```
