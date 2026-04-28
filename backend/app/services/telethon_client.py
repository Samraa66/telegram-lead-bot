"""
Telethon MTProto client — one client per workspace.

On startup `start_all_telethon_clients` spins up:
  - workspace 1: prefers operator.session file (legacy), falls back to DB StringSession
  - workspace N: StringSession stored in workspaces.telethon_session

Public API:
  send_as_operator(chat_id, text, workspace_id=1)       async
  send_as_operator_sync(chat_id, text, workspace_id=1)  sync, thread-safe
  get_client(workspace_id=1)                            returns running client or None
  start_workspace_client(workspace_id, session_str, api_id, api_hash)
  stop_workspace_client(workspace_id)
  start_all_telethon_clients(api_id, api_hash)
  stop_all_telethon_clients()
"""

from __future__ import annotations

import asyncio
import logging
import os
from datetime import datetime, timedelta
from typing import Optional

from telethon import TelegramClient, events
from telethon.sessions import StringSession
from telethon.tl.types import User

from app.database import SessionLocal
from app.database.models import Contact, Message, Workspace
from app.services.forwarding import copy_signal_for_org
from app.services.classifier import classify_contact
from app.services.scheduler import cancel_follow_ups

logger = logging.getLogger(__name__)

# workspace_id → client
_clients: dict[int, TelegramClient] = {}
# shared event loop (set once on startup)
_loop: Optional[asyncio.AbstractEventLoop] = None
# workspace_ids with a running client
_running: set[int] = set()


# ---------------------------------------------------------------------------
# Handler factories — closures capture workspace_id
# ---------------------------------------------------------------------------

def _make_outgoing_handler(workspace_id: int):
    async def _on_outgoing_message(event) -> None:
        if not event.is_private:
            return
        peer = await event.get_chat()
        if not isinstance(peer, User):
            return

        contact_id: int = peer.id
        text: str = event.message.text or ""
        now = datetime.utcnow()

        db = SessionLocal()
        try:
            contact = db.query(Contact).filter(
                Contact.id == contact_id,
                Contact.workspace_id == workspace_id,
            ).first()
            if not contact:
                return

            recent_cutoff = now - timedelta(seconds=30)
            already_saved = (
                db.query(Message)
                .filter(
                    Message.user_id == contact_id,
                    Message.direction == "outbound",
                    Message.content == text,
                    Message.timestamp >= recent_cutoff,
                )
                .first()
            )
            if already_saved:
                logger.debug("Outgoing dedup skip for contact_id=%s ws=%s", contact_id, workspace_id)
                return

            from app.handlers.outbound import handle_outbound
            handle_outbound(db, contact_id, text)
            logger.info("Outgoing message processed: contact_id=%s ws=%s", contact_id, workspace_id)
        except Exception:
            logger.exception("Error processing outgoing message contact_id=%s ws=%s", contact_id, workspace_id)
            db.rollback()
        finally:
            db.close()

    return _on_outgoing_message


def _make_inbound_handler(workspace_id: int):
    async def _on_new_message(event) -> None:
        if not event.is_private:
            return

        sender = await event.get_sender()
        if not isinstance(sender, User) or sender.bot:
            return

        user_id: int = sender.id
        username: Optional[str] = sender.username
        first_name: Optional[str] = sender.first_name
        last_name: Optional[str] = sender.last_name
        text: str = event.message.text or ""
        now = datetime.utcnow()

        source: Optional[str] = None
        if text.startswith("/start"):
            parts = text.split(maxsplit=1)
            if len(parts) == 2 and parts[1].strip():
                source = parts[1].strip()

        db = SessionLocal()
        try:
            contact = db.query(Contact).filter(
                Contact.id == user_id,
                Contact.workspace_id == workspace_id,
            ).first()

            if not contact:
                contact = Contact(
                    id=user_id,
                    workspace_id=workspace_id,
                    username=username,
                    first_name=first_name,
                    last_name=last_name,
                    source=source,
                    classification="new_lead",
                    current_stage=1,
                    stage_entered_at=now,
                    first_seen=now,
                    last_seen=now,
                )
                db.add(contact)
                db.flush()
                logger.info("New lead: user_id=%s ws=%s source=%s", user_id, workspace_id, source)
                try:
                    from app.services.scheduler import schedule_follow_ups
                    schedule_follow_ups(user_id, 1, now)
                except Exception:
                    pass
            else:
                contact.username = username
                if first_name is not None:
                    contact.first_name = first_name
                if last_name is not None:
                    contact.last_name = last_name
                contact.last_seen = now
                if source and not contact.source:
                    contact.source = source
                contact.classification = classify_contact(
                    db, user_id, contact.source, existing=contact
                )

            db.add(Message(
                user_id=user_id,
                message_text=text,
                content=text,
                direction="inbound",
                sender="contact",
                timestamp=now,
            ))
            db.commit()
            cancel_follow_ups(user_id)
            logger.info("Inbound message: user_id=%s ws=%s stage=%s", user_id, workspace_id, contact.current_stage)

        except Exception:
            logger.exception("Error handling inbound message user_id=%s ws=%s", user_id, workspace_id)
            db.rollback()
        finally:
            db.close()

    return _on_new_message


# ---------------------------------------------------------------------------
# Signal handler — listens to the workspace's source channel and forwards
# ---------------------------------------------------------------------------

def _make_signal_handler(workspace_id: int):
    """
    Closure that fires on new messages in the workspace's source channel.
    Calls copy_signal_for_org which uses the workspace's own bot token
    and routes to that workspace's affiliates only.
    """
    async def handler(event):
        source_chat_id = str(event.chat_id)
        message_id = event.message.id

        db = SessionLocal()
        try:
            copy_signal_for_org(
                workspace_id=workspace_id,
                source_chat_id=source_chat_id,
                message_id=message_id,
                db=db,
            )
        except Exception as e:
            logger.exception(
                "Signal handler failed: ws=%s msg_id=%s: %s",
                workspace_id, message_id, e,
            )
        finally:
            db.close()

    return handler


# ---------------------------------------------------------------------------
# Outbound send
# ---------------------------------------------------------------------------

async def send_as_operator(chat_id: int, text: str, workspace_id: int = 1) -> bool:
    client = _clients.get(workspace_id)
    if client is None or workspace_id not in _running:
        logger.error("Telethon client not running for workspace_id=%s", workspace_id)
        return False
    try:
        if not client.is_connected():
            await client.connect()
        await client.send_message(chat_id, text)
        return True
    except Exception:
        logger.exception("Telethon send failed: chat_id=%s ws=%s", chat_id, workspace_id)
        return False


def send_as_operator_sync(chat_id: int, text: str, workspace_id: int = 1) -> bool:
    """Thread-safe sync wrapper — used by scheduler and member_activity."""
    if workspace_id not in _running or _loop is None:
        return False
    try:
        future = asyncio.run_coroutine_threadsafe(
            send_as_operator(chat_id, text, workspace_id), _loop
        )
        return future.result(timeout=15)
    except Exception:
        logger.exception("send_as_operator_sync failed: chat_id=%s ws=%s", chat_id, workspace_id)
        return False


def get_client(workspace_id: int = 1) -> Optional[TelegramClient]:
    return _clients.get(workspace_id) if workspace_id in _running else None


# ---------------------------------------------------------------------------
# Per-workspace lifecycle
# ---------------------------------------------------------------------------

async def start_workspace_client(
    workspace_id: int,
    session: str | None,  # StringSession string, or None to use session file (ws 1)
    api_id: int,
    api_hash: str,
) -> bool:
    """
    Start a Telethon client for one workspace.
    Returns True if the client started and is authorized.
    """
    global _loop
    if not api_id or not api_hash:
        logger.warning("No API credentials — skipping Telethon for ws=%s", workspace_id)
        return False

    if workspace_id in _running:
        logger.info("Telethon already running for ws=%s", workspace_id)
        return True

    # Resolve session source
    if session:
        telethon_session = StringSession(session)
    else:
        # Fallback: session file (workspace 1 legacy path)
        from app.config import SESSION_FILE
        if not os.path.exists(SESSION_FILE):
            logger.warning("Session file not found (%s). Run scripts/setup_telethon.py.", SESSION_FILE)
            return False
        telethon_session = SESSION_FILE

    _loop = asyncio.get_running_loop()
    client = TelegramClient(
        telethon_session, api_id, api_hash,
        auto_reconnect=True,
        retry_delay=5,
        connection_retries=10,
    )
    client.add_event_handler(_make_inbound_handler(workspace_id), events.NewMessage(incoming=True))
    client.add_event_handler(_make_outgoing_handler(workspace_id), events.NewMessage(outgoing=True))

    # Signal handler — only for org-owner workspaces with a source channel set.
    # Allows tenants to forward their own signal feed to their own affiliates.
    db = SessionLocal()
    try:
        ws = db.query(Workspace).filter(Workspace.id == workspace_id).first()
    finally:
        db.close()

    if ws and ws.workspace_role == "owner" and ws.source_channel_id:
        try:
            source_id_int = int(ws.source_channel_id)
        except (TypeError, ValueError):
            logger.warning(
                "ws=%s source_channel_id=%r is not a valid int; signal handler not registered",
                workspace_id, ws.source_channel_id,
            )
        else:
            client.add_event_handler(
                _make_signal_handler(workspace_id),
                events.NewMessage(chats=[source_id_int]),
            )
            logger.info(
                "Registered signal handler for ws=%s on source=%s",
                workspace_id, source_id_int,
            )

    await client.connect()
    if not await client.is_user_authorized():
        logger.warning("Telethon session not authorized for ws=%s", workspace_id)
        await client.disconnect()
        return False

    _clients[workspace_id] = client
    _running.add(workspace_id)

    me = await client.get_me()
    logger.info("Telethon started — ws=%s operator=%s (@%s)", workspace_id, me.first_name, me.username)
    return True


async def stop_workspace_client(workspace_id: int) -> None:
    _running.discard(workspace_id)
    client = _clients.pop(workspace_id, None)
    if client:
        await client.disconnect()
        logger.info("Telethon stopped for ws=%s", workspace_id)


# ---------------------------------------------------------------------------
# Startup / shutdown (called from main.py lifespan)
# ---------------------------------------------------------------------------

async def start_all_telethon_clients(api_id: int, api_hash: str) -> None:
    """Start clients for all workspaces that have a Telethon session configured."""
    if not api_id or not api_hash:
        logger.info("TELEGRAM_API_ID/HASH not set — Telethon disabled")
        return

    db = SessionLocal()
    try:
        from app.database.models import Workspace
        workspaces = db.query(Workspace).all()
    finally:
        db.close()

    for ws in workspaces:
        session_str = ws.telethon_session or (None if ws.id != 1 else None)
        # workspace 1: try session file first, then DB string
        if ws.id == 1:
            from app.config import SESSION_FILE
            if os.path.exists(SESSION_FILE):
                session_str = None  # signal to use file
            # else fall through to session_str from DB (may also be None → skip)

        if ws.id != 1 and not session_str:
            continue  # no session configured for this workspace

        await start_workspace_client(ws.id, session_str, api_id, api_hash)


async def stop_all_telethon_clients() -> None:
    for workspace_id in list(_running):
        await stop_workspace_client(workspace_id)


# ---------------------------------------------------------------------------
# Deprecated shims — keep callers working until they're updated
# ---------------------------------------------------------------------------

async def start_telethon(session_file: str, api_id: int, api_hash: str) -> None:
    """Deprecated: use start_all_telethon_clients instead."""
    await start_all_telethon_clients(api_id, api_hash)


async def stop_telethon() -> None:
    """Deprecated: use stop_all_telethon_clients instead."""
    await stop_all_telethon_clients()
