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

from sqlalchemy import BigInteger, Boolean, Column, Date, DateTime, Float, ForeignKey, Integer, String, Text, UniqueConstraint
from sqlalchemy.orm import relationship
from sqlalchemy.ext.declarative import declarative_base

Base = declarative_base()


class Organization(Base):
    """
    Top-level client isolation boundary.
    Every workspace belongs to one org; no data crosses org boundaries.
    """

    __tablename__ = "organizations"

    id = Column(Integer, primary_key=True, autoincrement=True)
    name = Column(String(255), nullable=False)
    created_at = Column(DateTime, default=datetime.utcnow)


class Contact(Base):
    """
    A Telegram user tracked as a CRM contact.
    Primary key is the Telegram user ID to prevent duplicates.
    workspace_id scopes contacts per tenant — same Telegram user can only exist in one workspace.
    """

    __tablename__ = "contacts"

    id = Column(BigInteger, primary_key=True)  # Telegram user id (64-bit)
    workspace_id = Column(Integer, nullable=False, default=1)
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

    # Phase 5: computed daily by scheduler — active | at_risk | churned | high_value
    activity_status = Column(String(20), nullable=True)

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
    workspace_id = Column(Integer, nullable=False, default=1)
    stage = Column(Integer, nullable=False)
    sequence_num = Column(Integer, nullable=False)
    message_text = Column(Text, nullable=False)
    created_at = Column(DateTime, default=datetime.utcnow)


# ---------------------------------------------------------------------------
# Settings tables (workspace-scoped, SaaS-ready)
# ---------------------------------------------------------------------------

class Workspace(Base):
    """
    One row per workspace (tenant scope).

    Hierarchy:
      org_id               — client isolation; all workspaces in an org share data rules
      parent_workspace_id  — immediate parent (null = org root)
      root_workspace_id    — always the org root workspace id (O(1) subtree queries)
      workspace_role       — "owner" (root) | "affiliate" (child)

    A second client gets a new Organization + a new root Workspace (org_id differs).
    Affiliates of affiliates are just deeper children in the same org tree.
    """

    __tablename__ = "workspaces"

    id = Column(Integer, primary_key=True, autoincrement=True)
    name = Column(String(255), nullable=False)
    created_at = Column(DateTime, default=datetime.utcnow)
    # Org hierarchy
    org_id = Column(Integer, nullable=True, default=1)
    parent_workspace_id = Column(Integer, nullable=True)   # null = org root
    root_workspace_id = Column(Integer, nullable=True)     # always points to tree root
    workspace_role = Column(String(50), nullable=True, default="owner")  # owner | affiliate
    # Meta credentials — saved via Settings UI, override .env values
    meta_access_token = Column(Text, nullable=True)
    meta_ad_account_id = Column(String(100), nullable=True)
    meta_pixel_id = Column(String(100), nullable=True)
    landing_page_url = Column(Text, nullable=True)
    # Signal forwarding config — override .env values when set
    source_channel_id = Column(String(64), nullable=True)
    destination_channel_ids = Column(Text, nullable=True)  # comma-separated static destinations
    # Telegram bot credentials per workspace
    bot_token = Column(Text, nullable=True)
    webhook_secret = Column(String(255), nullable=True)
    # Telethon operator session — StringSession serialized string
    telethon_session = Column(Text, nullable=True)
    # Affiliate onboarding — flipped to True once wizard is completed
    onboarding_complete = Column(Boolean, default=False)


class StageKeyword(Base):
    """
    Keyword phrases that trigger pipeline stage advances.
    Replaces the hardcoded STAGE_KEYWORDS list in pipeline.py.
    """

    __tablename__ = "stage_keywords"
    __table_args__ = (UniqueConstraint("workspace_id", "keyword", name="uq_workspace_keyword"),)

    id = Column(Integer, primary_key=True, autoincrement=True)
    workspace_id = Column(Integer, nullable=False, default=1)
    keyword = Column(String(500), nullable=False)
    target_stage = Column(Integer, nullable=False)
    is_active = Column(Boolean, default=True, nullable=False)
    created_at = Column(DateTime, default=datetime.utcnow)


class StageLabel(Base):
    """Display label for each pipeline stage (1–8), editable per workspace."""

    __tablename__ = "stage_labels"
    __table_args__ = (UniqueConstraint("workspace_id", "stage_num", name="uq_workspace_stage"),)

    id = Column(Integer, primary_key=True, autoincrement=True)
    workspace_id = Column(Integer, nullable=False, default=1)
    stage_num = Column(Integer, nullable=False)
    label = Column(String(255), nullable=False)


class QuickReply(Base):
    """CRM drawer quick-reply buttons, one row per button, scoped to a stage."""

    __tablename__ = "quick_replies"

    id = Column(Integer, primary_key=True, autoincrement=True)
    workspace_id = Column(Integer, nullable=False, default=1)
    stage_num = Column(Integer, nullable=False)
    label = Column(String(255), nullable=False)
    text = Column(Text, nullable=False)
    sort_order = Column(Integer, nullable=False, default=0)
    is_active = Column(Boolean, default=True, nullable=False)
    created_at = Column(DateTime, default=datetime.utcnow)


class TeamMember(Base):
    """
    DB-backed team accounts (operator / vip_manager / admin).
    Replaces the single static .env credentials for each role.
    .env credentials remain as a fallback override for the developer account.

    auth_type:
      "password"  — username + password_hash, legacy path
      "telegram"  — verified via Telegram Login Widget; telegram_id populated on first login
    """

    __tablename__ = "team_members"

    id = Column(Integer, primary_key=True, autoincrement=True)
    workspace_id = Column(Integer, nullable=False, default=1)
    display_name = Column(String(255), nullable=False)
    username = Column(String(100), unique=True, nullable=False)
    password_hash = Column(String(255), nullable=False)
    # operator | vip_manager | admin  (developer stays in .env only)
    role = Column(String(50), nullable=False)
    is_active = Column(Boolean, default=True, nullable=False)
    created_at = Column(DateTime, default=datetime.utcnow)
    # Telegram login fields (added for SaaS auth)
    auth_type = Column(String(20), nullable=False, default="password")
    telegram_id = Column(BigInteger, nullable=True, unique=True)


class Campaign(Base):
    """
    Campaign registry: one row per tracked Meta ad campaign.
    source_tag is used as the Telegram /start parameter so leads are attributed.
    meta_campaign_id is the Meta campaign ID — optional, used to link to AdCampaign rows.
    """

    __tablename__ = "campaigns"

    id = Column(Integer, primary_key=True, autoincrement=True)
    workspace_id = Column(Integer, nullable=False, default=1)
    source_tag = Column(String(100), unique=True, nullable=False)
    name = Column(String(500), nullable=False)
    meta_campaign_id = Column(String(255), nullable=True)
    created_at = Column(DateTime, default=datetime.utcnow)
    is_active = Column(Boolean, default=True, nullable=False)


class AdCampaign(Base):
    """
    Daily Meta ad campaign performance snapshot.
    One row per (campaign_id, date). Populated by the daily Meta Marketing API pull.
    `leads` and `deposits` are contacts attributed via contact.source == campaign_id.
    """

    __tablename__ = "ad_campaigns"
    __table_args__ = (UniqueConstraint("campaign_id", "date", name="uq_campaign_date"),)

    id = Column(Integer, primary_key=True, autoincrement=True)
    campaign_id = Column(String(255), nullable=False)
    campaign_name = Column(String(500), nullable=True)
    date = Column(Date, nullable=False)
    spend = Column(Float, nullable=False, default=0.0)        # EUR spend reported by Meta
    impressions = Column(Integer, nullable=False, default=0)
    clicks = Column(Integer, nullable=False, default=0)
    leads = Column(Integer, nullable=False, default=0)        # contacts.source == campaign_id on this date
    deposits = Column(Integer, nullable=False, default=0)     # stage_7 reached with source == campaign_id
    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)


class Affiliate(Base):
    """
    Registered affiliate partners. Each has a unique referral_tag used as the
    Telegram /start parameter so their referred leads are attributed automatically.
    Commission is tracked manually via lots_traded (PuPrime data not yet integrated).
    """

    __tablename__ = "affiliates"

    id = Column(Integer, primary_key=True, autoincrement=True)
    workspace_id = Column(Integer, nullable=False, default=1)
    name = Column(String(255), nullable=False)
    username = Column(String(255), nullable=True)        # Telegram handle (optional)
    referral_tag = Column(String(100), unique=True, nullable=False)  # /start param value
    commission_rate = Column(Float, nullable=False, default=15.0)    # USD per lot traded
    lots_traded = Column(Float, nullable=False, default=0.0)         # manually updated by admin
    is_active = Column(Boolean, default=True, nullable=False)
    created_at = Column(DateTime, default=datetime.utcnow)

    # Login credentials — the affiliate sets their own password via an invite link
    login_username = Column(String(100), unique=True, nullable=True)
    login_password_hash = Column(String(255), nullable=True)  # pbkdf2 salt$hash, null until invite accepted
    # One-time invite token — null once consumed (or never issued for legacy affiliates)
    invite_token = Column(String(64), unique=True, nullable=True, index=True)
    invite_expires_at = Column(DateTime, nullable=True)
    # Provisioned CRM workspace for this affiliate (null = not yet provisioned)
    affiliate_workspace_id = Column(Integer, nullable=True)

    # Onboarding checklist
    esim_done = Column(Boolean, default=False, nullable=False)
    free_channel_id = Column(String(100), nullable=True)
    free_channel_members = Column(Integer, default=0, nullable=False)
    bot_setup_done = Column(Boolean, default=False, nullable=False)
    vip_channel_id = Column(String(100), nullable=True)
    vip_channel_members = Column(Integer, default=0, nullable=False)
    tutorial_channel_id = Column(String(100), nullable=True)
    tutorial_channel_members = Column(Integer, default=0, nullable=False)
    sales_scripts_done = Column(Boolean, default=False, nullable=False)
    ib_profile_id = Column(String(255), nullable=True)
    ads_live = Column(Boolean, default=False, nullable=False)
    pixel_setup_done = Column(Boolean, default=False, nullable=False)


class PendingChannel(Base):
    """
    Telegram channels/groups the bot was added to but not yet linked to an affiliate.
    The operator links them from the dashboard.
    """

    __tablename__ = "pending_channels"

    id = Column(Integer, primary_key=True, autoincrement=True)
    chat_id = Column(String(50), unique=True, nullable=False)   # e.g. -1001234567890
    title = Column(String(500), nullable=True)
    detected_at = Column(DateTime, default=datetime.utcnow)
    # Workspace whose bot the channel was added to (null = legacy/unknown)
    workspace_id = Column(Integer, nullable=True)


class AdCreative(Base):
    """
    Daily Meta ad-level performance snapshot.
    One row per (ad_id, date). Enables best-performing creative analysis.
    """

    __tablename__ = "ad_creatives"
    __table_args__ = (UniqueConstraint("ad_id", "date", name="uq_ad_date"),)

    id = Column(Integer, primary_key=True, autoincrement=True)
    ad_id = Column(String(255), nullable=False)
    ad_name = Column(String(500), nullable=True)
    campaign_id = Column(String(255), nullable=False)
    campaign_name = Column(String(500), nullable=True)
    date = Column(Date, nullable=False)
    spend = Column(Float, nullable=False, default=0.0)
    impressions = Column(Integer, nullable=False, default=0)
    clicks = Column(Integer, nullable=False, default=0)
    leads = Column(Integer, nullable=False, default=0)
    deposits = Column(Integer, nullable=False, default=0)
    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)
