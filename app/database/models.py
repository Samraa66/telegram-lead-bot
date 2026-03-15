"""
SQLAlchemy models for lead tracking.

- User: one row per Telegram user (user_id is primary key to prevent duplicates).
- Message: one row per message sent to the bot, linked to user_id.
"""

from datetime import datetime
from sqlalchemy import Column, Integer, String, Text, DateTime, ForeignKey
from sqlalchemy.orm import relationship
from sqlalchemy.ext.declarative import declarative_base

Base = declarative_base()


class User(Base):
    """
    Telegram user who has interacted with the bot.
    Primary key is Telegram's user id to prevent duplicate users.
    """

    __tablename__ = "users"

    id = Column(Integer, primary_key=True)  # Telegram user id
    username = Column(String(255), nullable=True)
    source = Column(String(255), nullable=True)  # campaign from start param, e.g. "vip"
    first_seen = Column(DateTime, default=datetime.utcnow)
    last_seen = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    messages = relationship("Message", back_populates="user")


class Message(Base):
    """
    A single message sent to the bot by a user.
    Used to count messages and analyze engagement per campaign.
    """

    __tablename__ = "messages"

    id = Column(Integer, primary_key=True, autoincrement=True)
    user_id = Column(Integer, ForeignKey("users.id"), nullable=False)
    message_text = Column(Text, nullable=True)
    timestamp = Column(DateTime, default=datetime.utcnow)

    user = relationship("User", back_populates="messages")
