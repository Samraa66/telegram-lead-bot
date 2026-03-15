# Telegram Lead Tracking & Signal Mirroring Bot

Production-ready Telegram bot that:

1. **Lead tracking** — Tracks users who message the bot (e.g. from campaign links), stores analytics (user_id, username, message_text, timestamp, source).
2. **Signal mirroring** — Copies messages from a single **Signal Feed** channel to multiple **VIP** channels in real time. The trader only has access to the Signal Feed; VIP channels receive copies without showing the source.

The app uses **webhooks** (no polling), FastAPI, and PostgreSQL (SQLite for local dev).

## Project structure

```
project/
  app/
    main.py              # FastAPI app, webhook routing
    config.py            # Env configuration
    bot.py               # Telegram API helpers (e.g. send_message)
    handlers/
      leads.py           # Private chat messages → lead tracking
      signals.py        # Channel posts → copy to VIP channels
    services/
      analytics.py       # Lead stats queries
      forwarding.py     # copy_message to VIP channels
    database/
      models.py         # User, Message models
      __init__.py       # Engine, session, init_db, get_db
  .env
  requirements.txt
  README.md
  scripts/
    send_message.py     # Send a message via the bot
```

## 1. Install dependencies

```bash
cd /path/to/Telegram_bot
python -m venv venv
source venv/bin/activate   # Windows: venv\Scripts\activate
pip install -r requirements.txt
```

## 2. Configure the bot

Copy `.env.example` to `.env` and set:

| Variable | Description |
|----------|-------------|
| `BOT_TOKEN` | From [@BotFather](https://t.me/BotFather). |
| `WEBHOOK_URL` | Public base URL of your app (e.g. `https://your-domain.com`). Must be HTTPS for production. |
| `WEBHOOK_SECRET` | Optional. If set, the webhook endpoint rejects requests whose `X-Telegram-Bot-Api-Secret-Token` header does not match. |
| `DATABASE_URL` | PostgreSQL URL in production; leave empty for SQLite (`leadbot.db` in project root). |
| `SOURCE_CHANNEL_ID` | Signal Feed channel ID (e.g. `-1001111111111`). Only posts from this channel are mirrored. |
| `DESTINATION_CHANNEL_IDS` | Comma-separated VIP channel IDs (e.g. `-10022222222,-10033333333`). Signals are copied here. |

### Finding Telegram channel IDs

- Add [@userinfobot](https://t.me/userinfobot) or [@getidsbot](https://t.me/getidsbot) to the channel and send a message; the bot may show the chat ID.
- Or: add your bot as admin, post in the channel, and check the `chat.id` in the webhook payload (e.g. from logs or a test endpoint).
- Channel IDs are usually negative and look like `-100xxxxxxxxxx`.

### Adding the bot as admin

For **signal mirroring** the bot must be able to read from the source channel and post to destination channels:

1. Add the bot to the **Signal Feed** channel as an administrator (at least “Post messages” or “Read messages” depending on how you get updates; for channel posts the bot must be in the channel and the channel must be linked to the bot or the bot admin so it receives `channel_post` updates).
2. Add the bot to each **VIP** channel as an administrator with permission to **post messages**.

To receive `channel_post` updates from a channel, the bot must be added to that channel. Telegram sends updates when someone posts in the channel.

## 3. Run locally

```bash
uvicorn app.main:app --host 0.0.0.0 --port 8000
```

For webhooks you need a public URL. Example with ngrok:

```bash
ngrok http 8000
# Set WEBHOOK_URL to the https URL (e.g. https://abc123.ngrok.io)
```

## 4. Set the webhook

Point Telegram to your webhook URL:

```text
https://api.telegram.org/bot<BOT_TOKEN>/setWebhook?url=<WEBHOOK_URL>/webhook
```

Example:

```text
https://api.telegram.org/bot123456:ABC-DEF/setWebhook?url=https://your-domain.com/webhook
```

If you use `WEBHOOK_SECRET`, pass it when setting the webhook so Telegram sends it back in each request:

```text
https://api.telegram.org/bot<BOT_TOKEN>/setWebhook?url=<WEBHOOK_URL>/webhook&secret_token=<WEBHOOK_SECRET>
```

The app checks the `X-Telegram-Bot-Api-Secret-Token` header and rejects mismatches.

To remove the webhook:

```text
https://api.telegram.org/bot<BOT_TOKEN>/deleteWebhook
```

## 5. Deploy on a VPS

1. Install Python 3, PostgreSQL (if used), and Nginx (or another reverse proxy).
2. Clone the repo and install dependencies in a virtualenv.
3. Set all environment variables (e.g. in `.env` or systemd unit).
4. Run with Gunicorn + Uvicorn:

   ```bash
   gunicorn app.main:app -w 1 -k uvicorn.workers.UvicornWorker -b 0.0.0.0:8000
   ```

5. Put Nginx in front with SSL (e.g. Let’s Encrypt) and proxy to `http://127.0.0.1:8000`.
6. Set `WEBHOOK_URL` to your public HTTPS base URL and call the `setWebhook` URL above.

## Behavior

### Lead tracking

- User opens `https://t.me/<BOT>?start=vip` → bot receives `/start vip`, stores user and source, replies with the welcome message.
- User sends any other message → bot stores message (user_id, username, message_text, timestamp, campaign from user), replies “Thanks, your request was sent.”

### Signal mirroring

- Trader posts in the **Signal Feed** channel (text, photo with caption, video, document, etc.).
- Bot receives `channel_post` (or `edited_channel_post`).
- If `channel_post.chat.id == SOURCE_CHANNEL_ID`, the bot **copies** the message to each channel in `DESTINATION_CHANNEL_IDS` using Telegram’s `copy_message` (so VIP channels do not show the original source).
- If one destination fails, the bot logs the error and continues to the next.

## API endpoints

| Method | Path | Description |
|--------|------|-------------|
| POST | `/webhook` | Telegram updates; validates secret; routes to leads or signals. |
| GET | `/stats/today` | Users and messages count for today. |
| GET | `/stats/by-source` | Lead count per campaign source. |
| GET | `/stats/messages-per-day` | Message count per day (optional `days`, default 30). |
| GET | `/health` | Health check. |

## Sending a message via the bot

```bash
python scripts/send_message.py <chat_id> "Your message"
```

Requires `BOT_TOKEN` in `.env` or environment.

## Logging

The app logs:

- Incoming lead messages (user_id).
- Signal posts detected from the Signal Feed.
- Success copying to each VIP channel.
- Errors when copying to a channel (one failure does not stop others).

## Database schema (lead tracking)

- **users**: `id` (Telegram user id, PK), `username`, `source`, `first_seen`, `last_seen`
- **messages**: `id`, `user_id`, `message_text`, `timestamp`

Duplicate users are avoided by using Telegram `user_id` as the primary key.
