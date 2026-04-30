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

from sqlalchemy import BigInteger, Boolean, Column, Date, DateTime, Float, ForeignKey, Index, Integer, Numeric, String, Text, UniqueConstraint
from sqlalchemy.orm import relationship
from sqlalchemy.ext.declarative import declarative_base

from app.database.types import EncryptedText

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
    source = Column(String(255), nullable=True)  # legacy — being deprecated; mirror of source_tag
    source_tag = Column(String(255), nullable=True)  # campaign tag (replaces source); written by /start parser today, by invite-link claim flow in Spec B
    entry_path = Column(String(64), nullable=True)   # controlled vocab — 'legacy_pre_attribution', 'landing_page', 'public_channel', 'affiliate', 'direct', 'unknown'

    first_seen = Column(DateTime, default=datetime.utcnow)
    last_seen = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    # VARCHAR not ENUM: new_lead | warm_lead | vip | affiliate | noise
    classification = Column(String(50), nullable=True)

    current_stage = Column(Integer, nullable=True, default=1)
    stage_entered_at = Column(DateTime, nullable=True)

    notes = Column(Text, nullable=True)

    deposit_confirmed = Column(Boolean, nullable=False, default=False)
    deposit_date = Column(Date, nullable=True)
    # New deposit semantics — supersede deposit_confirmed/deposit_date.
    # Old columns kept until phase-1 backfill confirms parity, then removed in phase 4.
    current_stage_id = Column(Integer, ForeignKey("pipeline_stages.id"), nullable=True)
    deposit_status = Column(String(20), nullable=False, default="none")  # none|pending|deposited
    deposited_at = Column(DateTime, nullable=True)
    deposit_amount = Column(Numeric(precision=18, scale=4), nullable=True)
    deposit_currency = Column(String(8), nullable=True)
    deposit_source = Column(String(20), nullable=True)  # manual|email|api
    puprime_client_id = Column(String(255), nullable=True, index=True)

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
    from_stage_id = Column(Integer, ForeignKey("pipeline_stages.id"), nullable=True)
    to_stage_id = Column(Integer, ForeignKey("pipeline_stages.id"), nullable=True)
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
    stage_id = Column(Integer, ForeignKey("pipeline_stages.id"), nullable=True)
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
    stage_id = Column(Integer, ForeignKey("pipeline_stages.id"), nullable=True)
    hours_offset = Column(Float, nullable=False, default=24.0)
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
    # Meta credentials — saved via Settings UI, override .env values.
    # Access token is encrypted at rest (Fernet); the rest are non-sensitive IDs.
    meta_access_token = Column(EncryptedText, nullable=True)
    meta_ad_account_id = Column(String(100), nullable=True)
    meta_pixel_id = Column(String(100), nullable=True)
    landing_page_url = Column(Text, nullable=True)
    # Signal forwarding config — override .env values when set
    source_channel_id = Column(String(64), nullable=True)
    destination_channel_ids = Column(Text, nullable=True)  # comma-separated static destinations
    # Telegram bot credentials per workspace — encrypted at rest
    bot_token = Column(EncryptedText, nullable=True)
    webhook_secret = Column(EncryptedText, nullable=True)
    # Telethon operator session — StringSession, encrypted at rest
    telethon_session = Column(EncryptedText, nullable=True)
    # Affiliate onboarding — flipped to True once wizard is completed
    onboarding_complete = Column(Boolean, default=False)
    # Org metadata (filled during signup / onboarding)
    niche = Column(String(255), nullable=True)
    language = Column(String(16), nullable=True)
    timezone = Column(String(64), nullable=True)
    country = Column(String(64), nullable=True)
    main_channel_url = Column(Text, nullable=True)
    sales_telegram_username = Column(String(255), nullable=True)
    # Pipeline pointers — null until pipeline stages are created
    deposited_stage_id = Column(Integer, ForeignKey("pipeline_stages.id"), nullable=True)
    member_stage_id = Column(Integer, ForeignKey("pipeline_stages.id"), nullable=True)
    conversion_stage_id = Column(Integer, ForeignKey("pipeline_stages.id"), nullable=True)
    # JSON-encoded list of substrings — if any appear in a contact's first/last name,
    # the contact is auto-promoted to member_stage_id at first sight (replaces the
    # hardcoded 'vip' substring check in handlers/leads.py:_vip_stage_from_name).
    vip_marker_phrases = Column(Text, nullable=True)  # JSON: ["vip", "premium", ...]
    # HMAC secret for POST /webhook/deposit-events
    deposit_webhook_secret = Column(EncryptedText, nullable=True)
    # Last "Sync Telegram history" run summary (timestamp + JSON-encoded counts)
    last_backfill_at = Column(DateTime, nullable=True)
    last_backfill_summary = Column(Text, nullable=True)  # JSON: {contacts_created, messages_replayed, skipped}
    # Last time the signal-forwarding pipeline successfully copied a signal to at
    # least one destination. Read by services/health.py:check_signal_forwarding
    # for the observed-success bypass.
    last_signal_forwarded_at = Column(DateTime, nullable=True)
    # Numeric channel ID for the public channel used in per-campaign invite-link
    # attribution (Spec B). Lazily resolved from main_channel_url by
    # services/attribution.py:resolve_attribution_channel on first use.
    attribution_channel_id = Column(BigInteger, nullable=True)


class PipelineStage(Base):
    """
    Per-workspace pipeline stage definition. Replaces hardcoded 1..8 stages.

    Flags:
      is_deposit_stage    — landing here marks the contact as deposited
      is_member_stage     — landing here marks the contact as a paying member (VIP)
      is_conversion_stage — used by analytics for "converted" cohort metrics

    end_action drives scheduler behavior after the last follow-up in this stage:
      "cold"     — stop following up
      "revert"   — move contact back to revert_to_stage_id
      "weekly"   — keep following up every 168h
      "monthly"  — keep following up every 720h
    """

    __tablename__ = "pipeline_stages"
    __table_args__ = (UniqueConstraint("workspace_id", "position", name="uq_workspace_position"),)

    id = Column(Integer, primary_key=True, autoincrement=True)
    workspace_id = Column(Integer, nullable=False, index=True)
    position = Column(Integer, nullable=False)
    name = Column(String(255), nullable=False)
    description = Column(Text, nullable=True)
    color = Column(String(32), nullable=True)
    is_member_stage = Column(Boolean, default=False, nullable=False)
    is_deposit_stage = Column(Boolean, default=False, nullable=False)
    is_conversion_stage = Column(Boolean, default=False, nullable=False)
    end_action = Column(String(20), nullable=False, default="cold")
    revert_to_stage_id = Column(Integer, ForeignKey("pipeline_stages.id"), nullable=True)
    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)


class DepositEvent(Base):
    """
    Append-only log of deposit events. Created by process_deposit_event() from
    any input source (manual button, email webhook, future PuPrime API).
    Idempotency_key dedupes — same key from same provider is a no-op.
    """

    __tablename__ = "deposit_events"
    __table_args__ = (
        UniqueConstraint("workspace_id", "provider", "idempotency_key",
                         name="uq_deposit_idempotency"),
    )

    id = Column(Integer, primary_key=True, autoincrement=True)
    workspace_id = Column(Integer, nullable=False, index=True)
    contact_id = Column(BigInteger, ForeignKey("contacts.id"), nullable=False, index=True)
    provider = Column(String(50), nullable=False)              # manual | puprime | other
    provider_client_id = Column(String(255), nullable=True)    # e.g. PuPrime account #
    amount = Column(Numeric(precision=18, scale=4), nullable=True)
    currency = Column(String(8), nullable=True)
    occurred_at = Column(DateTime, default=datetime.utcnow, nullable=False)
    source = Column(String(20), nullable=False)                # manual | email_parser | api
    idempotency_key = Column(String(255), nullable=False)
    raw_payload = Column(Text, nullable=True)
    created_at = Column(DateTime, default=datetime.utcnow, nullable=False)


class Account(Base):
    """
    User accounts with email-based login. Distinct from:
      TeamMember — workspace-internal team accounts (operator/vip_manager/admin)
      Affiliate  — affiliate-specific record with referral_tag and channel checklist
      static env users (developer/admin) — kept for backward compat

    role: "admin" (org owner / workspace owner) or "affiliate".
    org_role: "org_owner" | "workspace_owner" | "member" — written into the JWT.
    """

    __tablename__ = "accounts"

    id = Column(Integer, primary_key=True, autoincrement=True)
    workspace_id = Column(Integer, nullable=False, index=True)
    org_id = Column(Integer, nullable=False, index=True)
    email = Column(String(255), nullable=False, unique=True, index=True)
    full_name = Column(String(255), nullable=False)
    password_hash = Column(String(255), nullable=False)
    role = Column(String(50), nullable=False)              # admin | affiliate
    org_role = Column(String(50), nullable=False, default="member")  # org_owner | workspace_owner | member
    affiliate_id = Column(Integer, ForeignKey("affiliates.id"), nullable=True)
    email_verified = Column(Boolean, default=False, nullable=False)
    is_active = Column(Boolean, default=True, nullable=False)
    created_at = Column(DateTime, default=datetime.utcnow, nullable=False)
    last_login_at = Column(DateTime, nullable=True)


class AffiliateInvite(Base):
    """
    Pre-creates an invite without creating an Affiliate row yet.
    On accept, the invite_token is consumed and Affiliate + Account + child
    Workspace are all created in one transaction.
    """

    __tablename__ = "affiliate_invites"

    id = Column(Integer, primary_key=True, autoincrement=True)
    workspace_id = Column(Integer, nullable=False, index=True)
    invited_by_account_id = Column(Integer, ForeignKey("accounts.id"), nullable=True)
    invite_token = Column(String(64), nullable=False, unique=True, index=True)
    email = Column(String(255), nullable=True)
    status = Column(String(20), nullable=False, default="pending")  # pending|accepted|expired
    expires_at = Column(DateTime, nullable=False)
    accepted_at = Column(DateTime, nullable=True)
    created_at = Column(DateTime, default=datetime.utcnow, nullable=False)


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
    target_stage_id = Column(Integer, ForeignKey("pipeline_stages.id"), nullable=True)
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
    stage_id = Column(Integer, ForeignKey("pipeline_stages.id"), nullable=True)
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



class AuditLog(Base):
    """
    Append-only record of security-relevant actions: logins, credential resets,
    affiliate creates/deletes, workspace switches, etc.
    Read by admins; never edited or pruned automatically.
    """

    __tablename__ = "audit_log"

    id = Column(Integer, primary_key=True, autoincrement=True)
    timestamp = Column(DateTime, default=datetime.utcnow, nullable=False, index=True)
    actor_username = Column(String(255), nullable=True)        # null for unauthenticated events
    actor_role = Column(String(50), nullable=True)
    workspace_id = Column(Integer, nullable=True, index=True)
    org_id = Column(Integer, nullable=True)
    action = Column(String(100), nullable=False, index=True)   # e.g. "login.success", "affiliate.delete"
    target_type = Column(String(50), nullable=True)            # e.g. "affiliate", "workspace", "team_member"
    target_id = Column(String(100), nullable=True)             # stringly-typed so int + telegram-id both fit
    detail = Column(Text, nullable=True)                       # short human-readable note
    ip_address = Column(String(64), nullable=True)


class AppMeta(Base):
    """Single-row-per-key store for one-time migration flags and similar bookkeeping."""

    __tablename__ = "app_meta"

    key = Column(String(64), primary_key=True)
    value = Column(Text, nullable=False)
    updated_at = Column(DateTime, default=datetime.utcnow, nullable=False)


class CampaignInviteLink(Base):
    """
    Per-(workspace, campaign, channel) Telegram invite link for attribution.
    One row per campaign+channel combination — minted lazily on the first
    /attribution/invite call, reused thereafter (idempotent).
    invite_link_hash stores the unique suffix after the '+' in t.me/+<hash>
    for fast reverse-lookup when a join event arrives.
    """

    __tablename__ = "campaign_invite_links"
    __table_args__ = (
        UniqueConstraint(
            "workspace_id", "campaign_id", "channel_id",
            name="uq_invite_per_campaign",
        ),
    )

    id = Column(Integer, primary_key=True)
    workspace_id = Column(Integer, ForeignKey("workspaces.id"), nullable=False, index=True)
    campaign_id = Column(Integer, ForeignKey("campaigns.id"), nullable=False)
    source_tag = Column(String(255), nullable=False, index=True)  # denormalised from campaigns.source_tag
    channel_id = Column(BigInteger, nullable=False)
    invite_link = Column(Text, nullable=False)              # full https://t.me/+abc123
    invite_link_hash = Column(String(64), nullable=False, index=True)  # suffix after the +
    created_at = Column(DateTime, nullable=False, default=datetime.utcnow)
    revoked_at = Column(DateTime, nullable=True)


class ChannelJoinEvent(Base):
    """
    Append-only log of channel-join events for attribution.
    A row is inserted by the Telethon ChatAction handler on every join we observe.
    Claimed when the user later DMs the bot — claimed_contact_id + claimed_at
    track the join-to-contact attribution mapping.

    Cleanup: services/attribution.py:cleanup_old_join_events deletes rows
    older than 90 days where claimed_contact_id IS NULL.
    """

    __tablename__ = "channel_join_events"

    id = Column(Integer, primary_key=True)
    workspace_id = Column(Integer, ForeignKey("workspaces.id"), nullable=False)
    telegram_user_id = Column(BigInteger, nullable=False)
    channel_id = Column(BigInteger, nullable=False)
    source_tag = Column(String(255), nullable=True)         # NULL for organic joins (recorded for analytics)
    invite_link_hash = Column(String(64), nullable=True)
    joined_at = Column(DateTime, nullable=False, default=datetime.utcnow)
    claimed_contact_id = Column(BigInteger, ForeignKey("contacts.id"), nullable=True)  # BigInteger matches contacts.id
    claimed_at = Column(DateTime, nullable=True)


# Index supporting last-touch lookup at claim time.
Index(
    "idx_join_events_user_lookup",
    ChannelJoinEvent.workspace_id,
    ChannelJoinEvent.telegram_user_id,
    ChannelJoinEvent.joined_at.desc(),
)
# Index supporting TTL cleanup query.
Index("idx_join_events_ttl", ChannelJoinEvent.joined_at)
