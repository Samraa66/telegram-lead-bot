"""
SQLAlchemy models for the Smart Lead CRM.

Tables:
- contacts          : Telegram users / leads (renamed from `users`)
- messages          : inbound/outbound messages (user_id column kept for compat)
- stage_history     : stage transition log
- follow_up_queue   : scheduled follow-up jobs
- follow_up_templates: message templates per stage + sequence number

User = Contact alias kept so existing code that imports User continues to work.
"""

from datetime import date, datetime

from sqlalchemy import BigInteger, Boolean, Column, Date, DateTime, ForeignKey, Integer, String, Text
from sqlalchemy.orm import relationship
from sqlalchemy.ext.declarative import declarative_base

Base = declarative_base()


class Contact(Base):
    """
    A Telegram user tracked as a CRM contact.
    Primary key is the Telegram user ID to prevent duplicates.
    """

    __tablename__ = "contacts"

    id = Column(BigInteger, primary_key=True)  # Telegram user id (64-bit)
    username = Column(String(255), nullable=True)
    first_name = Column(String(255), nullable=True)
    last_name = Column(String(255), nullable=True)
    source = Column(String(255), nullable=True)  # campaign tag from /start param

    first_seen = Column(DateTime, default=datetime.utcnow)
    last_seen = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    # VARCHAR not ENUM: new_lead | warm_lead | vip | affiliate | noise
    classification = Column(String(50), nullable=True)

    current_stage = Column(Integer, nullable=True, default=1)
    stage_entered_at = Column(DateTime, nullable=True)

    notes = Column(Text, nullable=True)

    deposit_confirmed = Column(Boolean, nullable=False, default=False)
    deposit_date = Column(Date, nullable=True)

    is_affiliate = Column(Boolean, nullable=False, default=False)
    escalated = Column(Boolean, nullable=False, default=False)
    escalated_at = Column(DateTime, nullable=True)

    messages = relationship("Message", back_populates="contact")
    stage_history = relationship("StageHistory", back_populates="contact")
    follow_ups = relationship("FollowUpQueue", back_populates="contact")


# Backward compatibility: existing code that does `from app.database.models import User` still works.
User = Contact


class Message(Base):
    """
    Inbound/outbound chat message tied to a contact.

    The DB column is named 'user_id' for backward compatibility with existing rows
    and the pipeline.py code that creates Message(user_id=...).
    """

    __tablename__ = "messages"

    id = Column(Integer, primary_key=True, autoincrement=True)
    # DB column kept as 'user_id' — existing rows and FK constraints stay valid after
    # the users→contacts table rename.
    user_id = Column(BigInteger, ForeignKey("contacts.id"), nullable=False)

    # Kept for backward compatibility with existing analytics code
    message_text = Column(Text, nullable=True)

    direction = Column(String(20), nullable=True)   # inbound / outbound
    content = Column(Text, nullable=True)
    sender = Column(String(50), nullable=True)       # system / operator

    timestamp = Column(DateTime, default=datetime.utcnow)

    contact = relationship("Contact", back_populates="messages")


class StageHistory(Base):
    """Records every stage transition for a contact."""

    __tablename__ = "stage_history"

    id = Column(Integer, primary_key=True, autoincrement=True)
    contact_id = Column(BigInteger, ForeignKey("contacts.id"), nullable=False)

    from_stage = Column(Integer, nullable=True)
    to_stage = Column(Integer, nullable=False)
    moved_at = Column(DateTime, default=datetime.utcnow, nullable=False)
    moved_by = Column(String(20), nullable=False, default="system")  # system / manual / talal
    trigger_keyword = Column(String(255), nullable=True)

    contact = relationship("Contact", back_populates="stage_history")


class FollowUpQueue(Base):
    """
    A scheduled follow-up message for a contact at a specific stage/sequence.
    status: pending | fired | cancelled | cold  (VARCHAR, not ENUM)
    """

    __tablename__ = "follow_up_queue"

    id = Column(Integer, primary_key=True, autoincrement=True)
    contact_id = Column(BigInteger, ForeignKey("contacts.id"), nullable=False)

    stage = Column(Integer, nullable=False)
    sequence_num = Column(Integer, nullable=False)  # position in the follow-up sequence
    scheduled_at = Column(DateTime, nullable=False)
    fired_at = Column(DateTime, nullable=True)

    status = Column(String(20), nullable=False, default="pending")
    template_key = Column(String(50), nullable=True)

    contact = relationship("Contact", back_populates="follow_ups")


class FollowUpTemplate(Base):
    """Placeholder message texts per stage and sequence number."""

    __tablename__ = "follow_up_templates"

    id = Column(Integer, primary_key=True, autoincrement=True)
    stage = Column(Integer, nullable=False)
    sequence_num = Column(Integer, nullable=False)
    message_text = Column(Text, nullable=False)
    created_at = Column(DateTime, default=datetime.utcnow)
