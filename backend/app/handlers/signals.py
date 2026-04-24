"""
Signal mirroring handler: process channel posts from the Signal Feed.

Listens for channel_post and edited_channel_post; only processes messages
from SOURCE_CHANNEL_ID and copies them to all VIP destination channels.
"""

import logging
from typing import Optional, Tuple

from app.services.forwarding import (
    copy_signal_to_all_destinations,
    get_all_destination_channels,
    get_effective_source_channel_id,
)

logger = logging.getLogger(__name__)


def _get_channel_post(update: dict) -> Optional[dict]:
    """Return channel_post or edited_channel_post from update, or None."""
    post = update.get("channel_post")
    if post is not None:
        return post
    edited = update.get("edited_channel_post")
    if edited is not None:
        logger.debug("Edited channel post received; processing as signal")
        return edited
    return None


def _get_chat_id_and_message_id(post: dict) -> Tuple[Optional[str], Optional[int]]:
    """Extract chat_id and message_id from a channel post. chat_id as string for API."""
    if not post:
        return None, None
    chat = post.get("chat", {})
    chat_id = chat.get("id")
    message_id = post.get("message_id")
    if chat_id is None or message_id is None:
        return None, None
    return str(chat_id), message_id


def process_signal_update(update: dict) -> bool:
    """
    Process channel_post or edited_channel_post from the Signal Feed.
    Only acts if post.chat.id == SOURCE_CHANNEL_ID. Copies message to all
    DESTINATION_CHANNEL_IDS. Handles empty messages and edits without crashing.
    Returns True if the update was from the source channel (and we attempted copy).
    """
    post = _get_channel_post(update)
    if not post:
        return False

    chat_id, message_id = _get_chat_id_and_message_id(post)
    if chat_id is None or message_id is None:
        logger.debug("Channel post missing chat_id or message_id; skipping")
        return False

    source_channel_id = get_effective_source_channel_id()
    if not source_channel_id or str(chat_id) != str(source_channel_id):
        logger.debug("Ignoring channel post from %s (not Signal Feed %s)", chat_id, source_channel_id)
        return False

    all_destinations = get_all_destination_channels()
    logger.info(
        "Received signal from Signal Feed (channel_id=%s, message_id=%s) → forwarding to %d channel(s)",
        chat_id, message_id, len(all_destinations),
    )

    if not all_destinations:
        logger.warning("No destination channels configured; signal not copied")
        return True

    copy_signal_to_all_destinations(
        source_channel_id=chat_id,
        message_id=message_id,
        destination_channel_ids=all_destinations,
    )
    return True
