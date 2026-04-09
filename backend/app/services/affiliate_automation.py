"""
Affiliate onboarding automation.

send_affiliate_welcome()  — called after a new affiliate is created.
                            Resolves their @username via Telethon and sends a
                            welcome DM with their referral link + setup steps.

sync_channel_member_counts() — hourly scheduler job.
                               Calls getChatMemberCount for every linked affiliate
                               channel and updates free/vip/tutorial member counts.
"""

from __future__ import annotations

import asyncio
import logging
import urllib.request
import urllib.parse
import json
from typing import Optional

from app.config import BOT_TOKEN, BOT_USERNAME, DRY_RUN_SEND
from app.database import SessionLocal
from app.database.models import Affiliate

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Telegram Bot API helpers
# ---------------------------------------------------------------------------

def _bot_get(method: str, params: dict) -> dict:
    """GET request to the Telegram Bot API."""
    if not BOT_TOKEN:
        return {}
    query = urllib.parse.urlencode(params)
    url = f"https://api.telegram.org/bot{BOT_TOKEN}/{method}?{query}"
    try:
        with urllib.request.urlopen(url, timeout=10) as r:
            return json.loads(r.read())
    except Exception as e:
        logger.error("Bot API %s failed: %s", method, e)
        return {}


def get_chat_member_count(chat_id: str) -> Optional[int]:
    """Return member count for a channel/group, or None on failure."""
    resp = _bot_get("getChatMemberCount", {"chat_id": chat_id})
    if resp.get("ok"):
        return resp.get("result")
    return None


# ---------------------------------------------------------------------------
# Welcome DM
# ---------------------------------------------------------------------------

WELCOME_TEMPLATE = """\
Hey {name}! Welcome to the affiliate program.

Your dashboard login:
🔗 {dashboard_url}
👤 Username: {login_username}
🔑 Password: {login_password}

Log in to track your leads, deposits, commissions, and update your setup checklist.

━━━━━━━━━━━━━━━━━━━━

Your referral link:
{referral_link}

Every lead who clicks this link and messages us is automatically attributed to you. Share it everywhere.

━━━━━━━━━━━━━━━━━━━━
STEP 1 — Secondary phone (eSIM)
━━━━━━━━━━━━━━━━━━━━
Get a second phone number or eSIM to keep your affiliate Telegram account separate from your personal one.

━━━━━━━━━━━━━━━━━━━━
STEP 2 — Free Channel (public)
━━━━━━━━━━━━━━━━━━━━
Create a PUBLIC Telegram channel. This is where you convert all traffic from ads, Instagram, influencers, etc.

Daily content to post:
• 9am good morning message
• VIP member profit screenshots (real results from inside VIP)
• Lifestyle / trading content
• Welcome new VIP members by name (show they deposited and are already earning)
• Create scarcity — make people feel they are missing out on a private community

Goal: get people to click your CTA button and write to you in private.

━━━━━━━━━━━━━━━━━━━━
STEP 3 — CTA Button in your Free Channel
━━━━━━━━━━━━━━━━━━━━
You need Telegram Business (~€8/month). Here is the exact setup:

1. Subscribe to Telegram Business → go to "Chat Link" → create your personal chat link → copy it
2. Open @BotFather → /newbot → choose a name (must end in "bot") → save the token
3. In your Free Channel → Settings → Administrators → add your new bot
4. Also add @ChannelHelperBot as administrator
5. Open @ChannelHelperBot → Menu → Create a Post
6. Write your post text → tap Forward → Add Button
   Button text: "Click here"
   Button link: [paste your Telegram Business chat link]
7. Send the post → pin it at the top of your channel

When people click the button they land directly in your DM.

━━━━━━━━━━━━━━━━━━━━
STEP 4 — Buy Members & Views (crescitaly.com)
━━━━━━━━━━━━━━━━━━━━
Your channel MUST stay PUBLIC for this to work.

1. Register at crescitaly.com (login with Google)
2. Load €20–30
3. Search "Members" → buy "Telegram Members Super AK" → target 2,000 members (~€1.27/1000)
   Paste your channel's public invite link → order
4. Search "Views" → buy "Telegram Post Views" → select "Last 5 posts"
   Do this every time you post new content until you have real organic engagement

Important: keep buying views for each batch of messages you send every day. Without views your channel looks dead even with high member counts.

━━━━━━━━━━━━━━━━━━━━
STEP 5 — Tutorial Channel (public)
━━━━━━━━━━━━━━━━━━━━
Create a PUBLIC Telegram channel with trading tutorial content for beginners.
• Disable content saving (Settings → Restrict Saving)
• Copy our tutorial lessons one by one (we will give you access)
• At the very end of the tutorial, add a button/link that leads to your VIP channel access request

You send this to leads after they register on the platform, deposit, and unlock the bonus.

━━━━━━━━━━━━━━━━━━━━
STEP 6 — VIP Channel (private)
━━━━━━━━━━━━━━━━━━━━
Create a PRIVATE Telegram channel.

Signal forwarding is automatic — once you share your VIP channel ID in the dashboard, all trading signals will be forwarded to your channel in real time. You do not need to manage or copy anything.

━━━━━━━━━━━━━━━━━━━━
STEP 7 — PU Prime IB Profile
━━━━━━━━━━━━━━━━━━━━
Create your Introducing Broker account on PU Prime and share your IB ID in the dashboard. This is how your commissions are tracked.

━━━━━━━━━━━━━━━━━━━━
STEP 8 — Ads
━━━━━━━━━━━━━━━━━━━━
Once your channels are set up, launch your Meta ads. Your funnel:
Ads → Free Channel → CTA button → DM → Qualify → Tutorial → VIP

Track everything in the dashboard. We will give you access.

Update your progress in the CRM dashboard any time. Message us if you get stuck on any step.
"""


def send_affiliate_welcome(affiliate_id: int) -> None:
    """
    Resolve the affiliate's @username via Telethon and send them a welcome DM.
    Falls back gracefully if Telethon is not running or username is not set.
    """
    db = SessionLocal()
    try:
        affiliate = db.query(Affiliate).filter(Affiliate.id == affiliate_id).first()
        if not affiliate or not affiliate.username:
            logger.info("Affiliate %s has no username — skipping welcome DM", affiliate_id)
            return

        referral_link = (
            f"https://t.me/{BOT_USERNAME}?start={affiliate.referral_tag}"
            if BOT_USERNAME
            else f"referral tag: {affiliate.referral_tag}"
        )
        from app.config import WEBHOOK_URL
        # Derive dashboard URL from WEBHOOK_URL (strip /webhook path) or fallback
        dashboard_url = WEBHOOK_URL.replace("/webhook", "") if WEBHOOK_URL else "https://your-dashboard.com"

        text = WELCOME_TEMPLATE.format(
            name=affiliate.name,
            dashboard_url=dashboard_url,
            login_username=affiliate.login_username or "—",
            login_password="(see your credentials card)",
            referral_link=referral_link,
        )

        if DRY_RUN_SEND:
            logger.info(
                "DRY_RUN_SEND: would send welcome DM to @%s (affiliate_id=%s)",
                affiliate.username, affiliate_id,
            )
            return

        # Try Telethon first (sends as operator — more trusted, no need for user to start bot)
        try:
            from app.services.telethon_client import get_client
            client = get_client()
            if client:
                username = affiliate.username.lstrip("@")

                async def _send():
                    try:
                        entity = await client.get_entity(username)
                        await client.send_message(entity, text)
                        logger.info(
                            "Welcome DM sent to @%s (affiliate_id=%s) via Telethon",
                            username, affiliate_id,
                        )
                    except Exception as e:
                        logger.warning(
                            "Telethon welcome DM failed for @%s: %s", username, e
                        )

                loop = asyncio.get_event_loop()
                if loop.is_running():
                    asyncio.ensure_future(_send())
                else:
                    loop.run_until_complete(_send())
                return
        except Exception:
            pass

        logger.warning(
            "Telethon not available — welcome DM not sent to @%s (affiliate_id=%s)",
            affiliate.username, affiliate_id,
        )
    finally:
        db.close()


# ---------------------------------------------------------------------------
# Channel member count sync (hourly scheduler job)
# ---------------------------------------------------------------------------

def sync_channel_member_counts() -> None:
    """
    Poll getChatMemberCount for every affiliate channel that has an ID set,
    then update the member count fields in the DB.
    """
    db = SessionLocal()
    try:
        affiliates = db.query(Affiliate).filter(Affiliate.is_active.is_(True)).all()
        updated = 0

        for aff in affiliates:
            changed = False

            if aff.free_channel_id:
                count = get_chat_member_count(aff.free_channel_id)
                if count is not None and count != aff.free_channel_members:
                    aff.free_channel_members = count
                    changed = True

            if aff.vip_channel_id:
                count = get_chat_member_count(aff.vip_channel_id)
                if count is not None and count != aff.vip_channel_members:
                    aff.vip_channel_members = count
                    changed = True

            if aff.tutorial_channel_id:
                count = get_chat_member_count(aff.tutorial_channel_id)
                if count is not None and count != aff.tutorial_channel_members:
                    aff.tutorial_channel_members = count
                    changed = True

            if changed:
                updated += 1

        if updated:
            db.commit()
            logger.info("Channel member counts synced for %d affiliate(s)", updated)
        else:
            logger.debug("Channel member sync: no changes")
    except Exception:
        logger.exception("sync_channel_member_counts failed")
        db.rollback()
    finally:
        db.close()
