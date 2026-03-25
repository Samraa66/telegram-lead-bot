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
  deploy/
    telegram-bot.service.example   # systemd unit for VPS
  scripts/
    send_message.py     # Send a message via the bot
    set_webhook.py      # Set/remove webhook (for local testing)
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
| `PORT` | Port for the server (default `8000`). Use with gunicorn: `-b 0.0.0.0:$PORT`. |

### Finding Telegram channel IDs

- Add [@userinfobot](https://t.me/userinfobot) or [@getidsbot](https://t.me/getidsbot) to the channel and send a message; the bot may show the chat ID.
- Or: add your bot as admin, post in the channel, and check the `chat.id` in the webhook payload (e.g. from logs or a test endpoint).
- Channel IDs are usually negative and look like `-100xxxxxxxxxx`.

### Adding the bot as admin

For **signal mirroring** the bot must be able to read from the source channel and post to destination channels:

1. Add the bot to the **Signal Feed** channel as an administrator (at least “Post messages” or “Read messages” depending on how you get updates; for channel posts the bot must be in the channel and the channel must be linked to the bot or the bot admin so it receives `channel_post` updates).
2. Add the bot to each **VIP** channel as an administrator with permission to **post messages**.

To receive `channel_post` updates from a channel, the bot must be added to that channel. Telegram sends updates when someone posts in the channel.

## 3. Test the bot locally (no VPS)

You can test **lead tracking** with only a tunnel (e.g. ngrok) and `BOT_TOKEN`. Signal mirroring needs channels configured too.

### Step 1 — Minimal `.env` for local testing

In your project folder, ensure `.env` has at least:

- **BOT_TOKEN** — from [@BotFather](https://t.me/BotFather) (required).
- **WEBHOOK_URL** — leave empty for now; you’ll set it to your ngrok URL in Step 3.
- **DATABASE_URL** — leave empty to use SQLite (`leadbot.db` in the project root).
- **SOURCE_CHANNEL_ID** / **DESTINATION_CHANNEL_IDS** — only needed to test signal mirroring; can stay empty to test leads only.

### Step 2 — Start the app

```bash
cd /path/to/Telegram_bot
source venv/bin/activate   # or: venv\Scripts\activate on Windows
uvicorn app.main:app --host 0.0.0.0 --port 8000
```

Leave this terminal open. You should see something like: `Application startup complete`.

### Step 3 — Expose your machine with ngrok

Telegram must send webhooks to a **public HTTPS** URL. Use [ngrok](https://ngrok.com/) (free tier is enough):

1. Install ngrok: `brew install ngrok` (macOS) or download from ngrok.com.
2. In a **second terminal** run:
   ```bash
   ngrok http 8000
   ```
3. Copy the **HTTPS** URL ngrok shows (e.g. `https://abc123.ngrok-free.app`). Do **not** add `/webhook` — the script adds it.

### Step 4 — Point Telegram to your app

In a third terminal (or after stopping the server temporarily), from the project folder:

```bash
source venv/bin/activate
python scripts/set_webhook.py https://YOUR-NGROK-URL.ngrok-free.app
```

Replace with your actual ngrok URL (no trailing slash). If you use `WEBHOOK_SECRET` in `.env`, the script sends it to Telegram automatically.

To remove the webhook later (e.g. before deploying to VPS):

```bash
python scripts/set_webhook.py --delete
```

### Step 5 — Test lead tracking

1. In Telegram, open your bot (search by username or use the link from BotFather).
2. Send **/start** — you should get the welcome message and see logs like: `Received lead message`, `Webhook received`.
3. Send any other message — you should get “Thanks, your request was sent.” and see `Lead recorded` in the logs.
4. Check that data was stored:
   ```bash
   curl http://localhost:8000/stats/today
   curl http://localhost:8000/health
   ```

### Step 6 — (Optional) Test signal mirroring

You need a **Signal Feed** channel and at least one **VIP** channel, with the bot added as admin in both.

1. Set `SOURCE_CHANNEL_ID` and `DESTINATION_CHANNEL_IDS` in `.env` (comma-separated IDs).
2. Restart the app (Step 2). Keep ngrok running and webhook set (same URL).
3. Post a message in the Signal Feed channel — it should be copied to the VIP channel(s). Logs: `Received signal from Signal Feed`, `Copied signal to VIP channel`.

---

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

## 5. Push to GitHub

1. **Create a new repository** on [GitHub](https://github.com/new). Do not initialize with a README (you already have one).

2. **Add the remote and push** (replace `YOUR_USERNAME` and `YOUR_REPO` with your GitHub username and repo name):

```bash
cd /path/to/Telegram_bot
git remote add origin https://github.com/YOUR_USERNAME/YOUR_REPO.git
git branch -M main
git push -u origin main
```

3. **Set secrets for deployment**: In your repo go to **Settings → Secrets and variables → Actions** (or use your host’s env/config) and add `BOT_TOKEN`, `WEBHOOK_URL`, `WEBHOOK_SECRET`, `DATABASE_URL`, `SOURCE_CHANNEL_ID`, `DESTINATION_CHANNEL_IDS` so they are not in the code.

## 6. Deploy on a VPS (Ubuntu)

**VPS already set up?** Use it directly — no ngrok. SSH into the server and do the following. Your **WEBHOOK_URL** is your VPS domain with HTTPS (e.g. `https://yourdomain.com`). Once the app is running and the webhook is set, anyone (e.g. your friend) can message the bot and it will work.

### Quick steps on the VPS

1. **Install** on the server: Python 3.9+, pip, venv; Nginx (or Caddy) with SSL for your domain. PostgreSQL optional (leave `DATABASE_URL` empty for SQLite).
2. **Clone and install** (use your repo URL):
   ```bash
   cd /opt && sudo git clone https://github.com/Samraa66/telegram-lead-bot.git telegram-bot && cd telegram-bot
   sudo chown -R $USER:$USER /opt/telegram-bot
   python3 -m venv venv && source venv/bin/activate
   pip install -r requirements.txt
   ```
3. **Configure** `.env`: `cp .env.example .env`, then set at least **BOT_TOKEN** and **WEBHOOK_URL** (your VPS HTTPS URL, e.g. `https://yourdomain.com`). Leave `DATABASE_URL` empty for SQLite.
4. **Run the app** (for testing you can run in the foreground; for production use systemd):
   ```bash
   gunicorn app.main:app -w 1 -k uvicorn.workers.UvicornWorker -b 0.0.0.0:8000
   ```
   If you use Nginx, point it to `http://127.0.0.1:8000` and ensure your domain has SSL (e.g. Let’s Encrypt).
5. **Set the webhook** (from your laptop or the VPS, replace with your real BOT_TOKEN and WEBHOOK_URL):
   ```bash
   python scripts/set_webhook.py https://yourdomain.com
   ```
   Or in a browser: `https://api.telegram.org/bot<BOT_TOKEN>/setWebhook?url=https://yourdomain.com/webhook`
6. **Test**: Have your friend (or you) open the bot in Telegram, send `/start` and a message. Check `curl https://yourdomain.com/health` and `curl https://yourdomain.com/stats/today`.

---

### Full deployment details

1. **Install** on the server: Python 3.9+, pip, venv; PostgreSQL (optional); Nginx or Caddy for SSL.
2. **Clone and install**: `cd /opt && sudo git clone <YOUR_REPO> telegram-bot && cd telegram-bot`, then `python3 -m venv venv && source venv/bin/activate && pip install -r requirements.txt`.
3. **Configure**: Copy `.env.example` to `.env` and set all variables (including optional `PORT`, default 8000).
4. **Run with Gunicorn** (bind to `0.0.0.0`; use `PORT` if set):

   ```bash
   gunicorn app.main:app -w 1 -k uvicorn.workers.UvicornWorker -b 0.0.0.0:${PORT:-8000}
   ```

5. Set Telegram webhook (see step 6); put Nginx in front with SSL (e.g. Let’s Encrypt) and proxy to `http://127.0.0.1:8000`.
6. **Set webhook**: `https://api.telegram.org/bot<BOT_TOKEN>/setWebhook?url=<WEBHOOK_URL>/webhook` (add `&secret_token=<WEBHOOK_SECRET>` if used).
7. **Optional systemd**: See `deploy/telegram-bot.service.example`; copy to `/etc/systemd/system/` and enable the service. **Reverse proxy**: Nginx/Caddy with SSL to `http://127.0.0.1:8000`; forward header `X-Telegram-Bot-Api-Secret-Token` if using `WEBHOOK_SECRET`.

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
| GET | `/health` | Health check; returns `{"status": "ok"}`. Required for monitoring. |

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

---

## Deployment verification

After deploying on a VPS:

1. **Health check**: `curl https://your-domain.com/health` → expect `{"status":"ok"}`.
2. **Webhook**: Send a message to the bot in Telegram; check logs for "Webhook received" and "Lead recorded" (or "Received lead message").
3. **Signal mirroring**: Post in the Signal Feed channel; check logs for "Received signal from Signal Feed" and "Copied signal to VIP channel".
4. **Stats**: `curl https://your-domain.com/stats/today` → expect `{"users_today": ..., "messages_today": ...}`.
5. **Webhook URL**: Ensure Telegram is pointing to `https://your-domain.com/webhook` (no trailing slash) and that Nginx forwards the request and the `X-Telegram-Bot-Api-Secret-Token` header if you use a secret.
