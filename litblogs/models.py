# models.py
from datetime import UTC, datetime
from enum import Enum

from sqlalchemy import (
    CHAR,
    BigInteger,
    Boolean,
    CheckConstraint,
    Column,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
    UniqueConstraint,
    and_,
    func,
)
from sqlalchemy import Enum as SQLAlchemyEnum
from sqlalchemy.orm import relationship

from base import Base


def _utc_now_naive() -> datetime:
    return datetime.now(UTC).replace(tzinfo=None)


def _utc_now_aware() -> datetime:
    return datetime.now(UTC)


class UserRole(str, Enum):
    STUDENT = "STUDENT"
    TEACHER = "TEACHER"
    ADMIN = "ADMIN"

class User(Base):
    __tablename__ = "users"
    id = Column(Integer, primary_key=True, index=True)
    username = Column(String(50), unique=True, index=True, nullable=False)
    email = Column(String(100), unique=True, index=True, nullable=False)
    password = Column(String(255), nullable=False)
    first_name = Column(String(50))
    last_name = Column(String(50))
    role = Column(SQLAlchemyEnum(UserRole), nullable=False, default=UserRole.STUDENT)
    is_admin = Column(Boolean, default=False)
    created_at = Column(DateTime(timezone=True), server_default=func.now())
    disabled_at = Column(DateTime(timezone=True), nullable=True, index=True)
    bio = Column(String(500), nullable=True)
    profile_image = Column(String(255), nullable=True)
    cover_image = Column(String(255), nullable=True)
    avatar_id = Column(String(50), nullable=True)
    avatar_color = Column(String(50), nullable=True)
    __table_args__ = (
        CheckConstraint(
            "email COLLATE \"C\" = "
            "translate(btrim(email), "
            "'ABCDEFGHIJKLMNOPQRSTUVWXYZ', "
            "'abcdefghijklmnopqrstuvwxyz') COLLATE \"C\"",
            name="ck_users_email_canonical",
        ).ddl_if(dialect="postgresql"),
        CheckConstraint(
            "octet_length(email) = char_length(email)",
            name="ck_users_email_ascii",
        ).ddl_if(dialect="postgresql"),
        CheckConstraint(
            "email !~ '[[:space:]]'",
            name="ck_users_email_no_whitespace",
        ).ddl_if(dialect="postgresql"),
        CheckConstraint(
            "email !~ '[[:cntrl:]]'",
            name="ck_users_email_no_controls",
        ).ddl_if(dialect="postgresql"),
        Index(
            "uq_users_email_normalized",
            email,
            unique=True,
            postgresql_ops={"email": "varchar_pattern_ops"},
        ).ddl_if(dialect="postgresql"),
    )
    # For students: the classes they're enrolled in
    enrolled_classes = relationship("ClassEnrollment", back_populates="student")
    blogs = relationship("Blog", back_populates="owner")
    likes = relationship("PostLike", back_populates="user", cascade="all, delete-orphan")
    comments = relationship("Comment", back_populates="user", cascade="all, delete-orphan")
    settings = relationship("UserSettings", back_populates="user", uselist=False, cascade="all, delete-orphan")
    comment_likes = relationship("CommentLike", back_populates="user", cascade="all, delete-orphan")
    assignment_submissions = relationship("AssignmentSubmission", back_populates="student", cascade="all, delete-orphan")
    assignment_drafts = relationship("AssignmentDraft", back_populates="student", cascade="all, delete-orphan")
    assignment_submission_replies = relationship("AssignmentSubmissionReply", back_populates="user", cascade="all, delete-orphan")
    saved_posts = relationship("SavedPost", back_populates="user", cascade="all, delete-orphan")
    push_subscriptions = relationship("PushSubscription", back_populates="user", cascade="all, delete-orphan")
    federated_identities = relationship(
        "FederatedIdentity",
        back_populates="user",
        cascade="all, delete-orphan",
    )
    assignment_reminder_notifications = relationship(
        "AssignmentReminderNotification",
        back_populates="user",
        cascade="all, delete-orphan",
    )
    browser_sessions = relationship(
        "BrowserSession",
        back_populates="user",
        cascade="all, delete-orphan",
    )
    upload_assets = relationship(
        "UploadAsset",
        back_populates="owner",
        passive_deletes=True,
    )


class BrowserSession(Base):
    __tablename__ = "browser_sessions"

    id = Column(Integer, primary_key=True)
    jti_digest = Column(String(64), nullable=False)
    user_id = Column(
        Integer,
        ForeignKey(
            "users.id",
            ondelete="CASCADE",
            name="fk_browser_session_user",
        ),
        nullable=False,
        index=True,
    )
    created_at = Column(
        DateTime(timezone=True),
        default=_utc_now_naive,
        server_default=func.now(),
        nullable=False,
    )
    expires_at = Column(DateTime(timezone=True), nullable=False, index=True)
    revoked_at = Column(DateTime(timezone=True), nullable=True)

    user = relationship("User", back_populates="browser_sessions")

    __table_args__ = (
        UniqueConstraint(
            "jti_digest",
            name="uq_browser_session_jti_digest",
        ),
        CheckConstraint(
            "length(jti_digest) = 64",
            name="ck_browser_session_jti_digest",
        ),
        CheckConstraint(
            "jti_digest ~ '^[0-9a-f]{64}$'",
            name="ck_browser_session_jti_digest_lower_hex",
        ).ddl_if(dialect="postgresql"),
        Index(
            "ix_browser_sessions_user_recency",
            "user_id",
            "created_at",
            "id",
        ),
    )


class TeacherInvitation(Base):
    __tablename__ = "teacher_invitations"

    id = Column(Integer, primary_key=True)
    token_digest = Column(String(64), nullable=False)
    email_digest = Column(String(64), nullable=False, index=True)
    created_at = Column(
        DateTime(timezone=True),
        default=_utc_now_naive,
        server_default=func.now(),
        nullable=False,
    )
    expires_at = Column(DateTime(timezone=True), nullable=False, index=True)
    consumed_at = Column(DateTime(timezone=True), nullable=True)
    revoked_at = Column(DateTime(timezone=True), nullable=True)
    created_by = Column(String(100), nullable=False)

    __table_args__ = (
        UniqueConstraint(
            "token_digest",
            name="uq_teacher_invitation_token_digest",
        ),
        CheckConstraint(
            "length(token_digest) = 64",
            name="ck_teacher_invitation_token_digest",
        ),
        CheckConstraint(
            "token_digest ~ '^[0-9a-f]{64}$'",
            name="ck_teacher_invitation_token_digest_lower_hex",
        ).ddl_if(dialect="postgresql"),
        CheckConstraint(
            "length(email_digest) = 64",
            name="ck_teacher_invitation_email_digest",
        ),
        CheckConstraint(
            "email_digest ~ '^[0-9a-f]{64}$'",
            name="ck_teacher_invitation_email_digest_lower_hex",
        ).ddl_if(dialect="postgresql"),
        CheckConstraint(
            "length(created_by) BETWEEN 1 AND 100",
            name="ck_teacher_invitation_created_by",
        ),
        CheckConstraint(
            "created_by ~ '^[A-Za-z0-9][A-Za-z0-9._:@/-]{0,99}$'",
            name="ck_teacher_invitation_created_by_format",
        ).ddl_if(dialect="postgresql"),
        Index(
            "uq_teacher_invitation_active_email",
            "email_digest",
            unique=True,
            sqlite_where=and_(consumed_at.is_(None), revoked_at.is_(None)),
            postgresql_where=and_(consumed_at.is_(None), revoked_at.is_(None)),
        ),
    )


class OperatorAuditEvent(Base):
    __tablename__ = "operator_audit_events"

    id = Column(Integer, primary_key=True)
    actor_identifier = Column(String(100), nullable=False, index=True)
    action = Column(String(64), nullable=False, index=True)
    outcome = Column(String(16), nullable=False)
    resource_digest = Column(String(64), nullable=False, index=True)
    created_at = Column(
        DateTime(timezone=True),
        default=_utc_now_naive,
        server_default=func.now(),
        nullable=False,
        index=True,
    )

    __table_args__ = (
        CheckConstraint(
            "length(actor_identifier) BETWEEN 1 AND 100",
            name="ck_operator_audit_actor_identifier",
        ),
        CheckConstraint(
            "actor_identifier ~ '^[A-Za-z0-9][A-Za-z0-9._:@/-]{0,99}$'",
            name="ck_operator_audit_actor_identifier_format",
        ).ddl_if(dialect="postgresql"),
        CheckConstraint(
            "action IN ("
            "'TEACHER_INVITATION_CREATED', "
            "'TEACHER_INVITATION_REVOKED', "
            "'ACCOUNT_DISABLED', "
            "'ACCOUNT_ENABLED'"
            ")",
            name="ck_operator_audit_action",
        ),
        CheckConstraint(
            "outcome IN ('SUCCEEDED', 'NOT_FOUND', 'CONFLICT')",
            name="ck_operator_audit_outcome",
        ),
        CheckConstraint(
            "length(resource_digest) = 64",
            name="ck_operator_audit_resource_digest",
        ),
        CheckConstraint(
            "resource_digest ~ '^[0-9a-f]{64}$'",
            name="ck_operator_audit_resource_digest_lower_hex",
        ).ddl_if(dialect="postgresql"),
    )

class UserSettings(Base):
    __tablename__ = "user_settings"

    id = Column(Integer, primary_key=True, index=True)
    user_id = Column(Integer, ForeignKey("users.id", ondelete="CASCADE"), unique=True, nullable=False, index=True)
    dark_mode = Column(Boolean, default=False, nullable=False)
    reduced_motion = Column(Boolean, default=False, nullable=False)
    email_notifications = Column(Boolean, default=True, nullable=False)
    assignment_reminders = Column(Boolean, default=True, nullable=False)
    auto_play_videos = Column(Boolean, default=False, nullable=False)
    compact_feed = Column(Boolean, default=False, nullable=False)
    remember_drafts = Column(Boolean, default=True, nullable=False)
    show_profile_to_classmates = Column(Boolean, default=True, nullable=False)
    editor_font_size = Column(String(16), default="medium", nullable=False)
    updated_at = Column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=False)

    user = relationship("User", back_populates="settings")

class PushSubscription(Base):
    __tablename__ = "push_subscriptions"

    id = Column(Integer, primary_key=True, index=True)
    user_id = Column(Integer, ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True)
    endpoint = Column(String(1024), unique=True, nullable=False)
    p256dh = Column(String(255), nullable=False)
    auth = Column(String(255), nullable=False)
    created_at = Column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    updated_at = Column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=False)

    user = relationship("User", back_populates="push_subscriptions")


class AssignmentReminderNotification(Base):
    __tablename__ = "assignment_reminder_notifications"

    id = Column(Integer, primary_key=True, index=True)
    user_id = Column(Integer, ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True)
    assignment_id = Column(Integer, ForeignKey("assignments.id", ondelete="CASCADE"), nullable=False, index=True)
    sent_at = Column(DateTime(timezone=True), server_default=func.now(), nullable=False)

    user = relationship("User", back_populates="assignment_reminder_notifications")
    assignment = relationship("Assignment")

    __table_args__ = (
        UniqueConstraint("user_id", "assignment_id", name="uq_assignment_reminder_notification"),
    )


class FederatedIdentity(Base):
    __tablename__ = "federated_identities"

    id = Column(Integer, primary_key=True)
    provider = Column(String(16), nullable=False)
    issuer = Column(String(255), nullable=False)
    subject = Column(String(255), nullable=False)
    user_id = Column(
        Integer,
        ForeignKey("users.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    created_at = Column(DateTime(timezone=True), server_default=func.now(), nullable=False)

    user = relationship("User", back_populates="federated_identities")

    __table_args__ = (
        CheckConstraint(
            "provider IN ('google', 'microsoft')",
            name="ck_federated_identity_provider",
        ),
        UniqueConstraint(
            "provider",
            "issuer",
            "subject",
            name="uq_federated_identity_subject",
        ),
        UniqueConstraint(
            "provider",
            "user_id",
            name="uq_federated_identity_provider_user",
        ),
    )

class Teacher(Base):
    __tablename__ = "teachers"
    id = Column(Integer, primary_key=True, index=True)
    name = Column(String)
    email = Column(String(100), unique=True, index=True, nullable=False)
    hashed_password = Column(String)
    user_id = Column(Integer, ForeignKey("users.id"), nullable=False)
    user = relationship("User", backref="teacher_profile")
    classes = relationship("Class", back_populates="teacher")

    __table_args__ = (
        UniqueConstraint("user_id", name="uq_teachers_user_id"),
        CheckConstraint(
            "email COLLATE \"C\" = "
            "translate(btrim(email), "
            "'ABCDEFGHIJKLMNOPQRSTUVWXYZ', "
            "'abcdefghijklmnopqrstuvwxyz') COLLATE \"C\"",
            name="ck_teachers_email_canonical",
        ).ddl_if(dialect="postgresql"),
        CheckConstraint(
            "octet_length(email) = char_length(email)",
            name="ck_teachers_email_ascii",
        ).ddl_if(dialect="postgresql"),
        CheckConstraint(
            "email !~ '[[:space:]]'",
            name="ck_teachers_email_no_whitespace",
        ).ddl_if(dialect="postgresql"),
        CheckConstraint(
            "email !~ '[[:cntrl:]]'",
            name="ck_teachers_email_no_controls",
        ).ddl_if(dialect="postgresql"),
    )

class Class(Base):
    __tablename__ = "classes"
    id = Column(Integer, primary_key=True, index=True)
    name = Column(String(100), nullable=False)
    description = Column(Text, nullable=True)
    access_code = Column(String(6), unique=True, nullable=False, index=True)
    created_at = Column(DateTime(timezone=True), server_default=func.now())
    teacher_id = Column(Integer, ForeignKey("teachers.id"))
    teacher = relationship("Teacher", back_populates="classes")
    students = relationship("ClassEnrollment", back_populates="class_")
    blogs = relationship("Blog", back_populates="class_")
    assignments = relationship("Assignment", back_populates="class_", cascade="all, delete-orphan")
    status = Column(String, default="active")  # 'active', 'archived', or 'deleted'
    posts_visibility = Column(String, default="class")  # 'class' or 'private'

class Assignment(Base):
    __tablename__ = "assignments"
    id = Column(Integer, primary_key=True, index=True)
    class_id = Column(Integer, ForeignKey("classes.id"), nullable=False)
    title = Column(String(200), nullable=False)
    description = Column(Text, nullable=True)
    due_date = Column(DateTime(timezone=True), nullable=False)
    created_at = Column(DateTime(timezone=True), server_default=func.now())
    created_by = Column(Integer, ForeignKey("users.id"), nullable=False)
    allow_late = Column(Boolean, default=True)
    visibility = Column(String, default="class")  # 'class' or 'private'

    class_ = relationship("Class", back_populates="assignments")
    submissions = relationship("AssignmentSubmission", back_populates="assignment", cascade="all, delete-orphan")
    drafts = relationship("AssignmentDraft", back_populates="assignment", cascade="all, delete-orphan")

class AssignmentDraft(Base):
    __tablename__ = "assignment_drafts"
    id = Column(Integer, primary_key=True, index=True)
    assignment_id = Column(Integer, ForeignKey("assignments.id", ondelete="CASCADE"), nullable=False)
    student_id = Column(Integer, ForeignKey("users.id", ondelete="CASCADE"), nullable=False)
    content = Column(Text, nullable=True)
    revision = Column(Integer, default=0, server_default="0", nullable=False)
    updated_at = Column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=False)

    assignment = relationship("Assignment", back_populates="drafts")
    student = relationship("User", back_populates="assignment_drafts")

    __table_args__ = (
        UniqueConstraint('assignment_id', 'student_id', name='unique_assignment_draft'),
        CheckConstraint(
            "revision >= 0 AND revision <= 2147483647",
            name="assignment_drafts_revision_range",
        ),
    )

class AssignmentSubmission(Base):
    __tablename__ = "assignment_submissions"
    id = Column(Integer, primary_key=True, index=True)
    assignment_id = Column(Integer, ForeignKey("assignments.id"), nullable=False)
    student_id = Column(Integer, ForeignKey("users.id"), nullable=False)
    submitted_at = Column(DateTime(timezone=True), server_default=func.now())
    content = Column(Text, nullable=True)
    is_late = Column(Boolean, default=False)
    
    # AI Detection fields
    ai_percentage = Column(Integer, nullable=True)
    ai_highlighted_html = Column(Text, nullable=True)
    ai_sentence_analysis = Column(Text, nullable=True)

    assignment = relationship("Assignment", back_populates="submissions")
    student = relationship("User", back_populates="assignment_submissions")
    replies = relationship("AssignmentSubmissionReply", back_populates="submission", cascade="all, delete-orphan")

    __table_args__ = (
        UniqueConstraint('assignment_id', 'student_id', name='unique_assignment_submission'),
    )

class AssignmentSubmissionReply(Base):
    __tablename__ = "assignment_submission_replies"
    id = Column(Integer, primary_key=True, index=True)
    submission_id = Column(Integer, ForeignKey("assignment_submissions.id", ondelete="CASCADE"), nullable=False)
    user_id = Column(Integer, ForeignKey("users.id", ondelete="CASCADE"), nullable=False)
    content = Column(Text, nullable=False)
    created_at = Column(DateTime(timezone=True), server_default=func.now())
    updated_at = Column(DateTime(timezone=True), onupdate=func.now(), nullable=True)

    submission = relationship("AssignmentSubmission", back_populates="replies")
    user = relationship("User", back_populates="assignment_submission_replies")

class ClassEnrollment(Base):
    __tablename__ = "class_enrollments"
    id = Column(Integer, primary_key=True, index=True)
    student_id = Column(Integer, ForeignKey("users.id"), nullable=False)
    class_id = Column(Integer, ForeignKey("classes.id"), nullable=False)
    enrolled_at = Column(DateTime(timezone=True), server_default=func.now())
    notes = Column(Text, nullable=True)
    student = relationship("User", back_populates="enrolled_classes")
    class_ = relationship("Class", back_populates="students")

    __table_args__ = (
        UniqueConstraint('student_id', 'class_id', name='unique_class_enrollment'),
    )

class Blog(Base):
    __tablename__ = "blogs"
    id = Column(Integer, primary_key=True, index=True)
    title = Column(String(255), index=True, nullable=False)
    content = Column(Text, nullable=False)
    created_at = Column(DateTime(timezone=True), server_default=func.now())
    owner_id = Column(Integer, ForeignKey("users.id"), nullable=False)
    class_id = Column(Integer, ForeignKey("classes.id"), nullable=False)
    
    # AI Detection fields
    ai_percentage = Column(Integer, nullable=True)
    ai_highlighted_html = Column(Text, nullable=True)
    ai_sentence_analysis = Column(Text, nullable=True)
    
    owner = relationship("User", back_populates="blogs")
    class_ = relationship("Class", back_populates="blogs")
    likes = relationship("PostLike", back_populates="post", cascade="all, delete-orphan")
    comments = relationship("Comment", back_populates="blog")
    saved_by = relationship("SavedPost", back_populates="post", cascade="all, delete-orphan")
    upload_assets = relationship(
        "UploadAsset",
        back_populates="blog",
        passive_deletes=True,
    )


class UploadAsset(Base):
    __tablename__ = "upload_assets"

    id = Column(BigInteger().with_variant(Integer, "sqlite"), primary_key=True)
    storage_key = Column(String(255), nullable=False, unique=True)
    owner_user_id = Column(
        Integer,
        ForeignKey(
            "users.id",
            ondelete="SET NULL",
            name="fk_upload_assets_owner_user",
        ),
        nullable=True,
    )
    blog_id = Column(
        Integer,
        ForeignKey(
            "blogs.id",
            ondelete="SET NULL",
            name="fk_upload_assets_blog",
        ),
        nullable=True,
    )
    purpose = Column(String(20), nullable=False)
    state = Column(String(20), nullable=False)
    original_filename = Column(String(255), nullable=True)
    media_type = Column(String(127), nullable=False)
    size_bytes = Column(BigInteger, nullable=False)
    sha256_digest = Column(CHAR(64), nullable=False)
    created_at = Column(
        DateTime(timezone=True),
        default=_utc_now_aware,
        server_default=func.now(),
        nullable=False,
    )
    expires_at = Column(DateTime(timezone=True), nullable=True)
    bound_at = Column(DateTime(timezone=True), nullable=True)
    delete_after = Column(DateTime(timezone=True), nullable=True)
    deleted_at = Column(DateTime(timezone=True), nullable=True)
    scan_completed_at = Column(DateTime(timezone=True), nullable=True)

    owner = relationship("User", back_populates="upload_assets")
    blog = relationship("Blog", back_populates="upload_assets")

    __table_args__ = (
        CheckConstraint(
            "purpose IN ('POST', 'PROFILE_IMAGE', 'COVER_IMAGE')",
            name="ck_upload_assets_purpose",
        ),
        CheckConstraint(
            "state IN ('PENDING', 'ACTIVE', 'DELETE_PENDING', 'DELETED')",
            name="ck_upload_assets_state",
        ),
        CheckConstraint("size_bytes > 0", name="ck_upload_assets_positive_size"),
        CheckConstraint(
            "length(sha256_digest) = 64",
            name="ck_upload_assets_sha256_length",
        ),
        CheckConstraint(
            "sha256_digest ~ '^[0-9a-f]{64}$'",
            name="ck_upload_assets_sha256_lower_hex",
        ).ddl_if(dialect="postgresql"),
        CheckConstraint(
            "substr(storage_key, 1, 8) = 'objects/' "
            "AND substr(storage_key, 9, 2) = substr(storage_key, 12, 2)",
            name="ck_upload_assets_storage_key_prefix",
        ),
        CheckConstraint(
            "storage_key ~ '^objects/[0-9a-f]{2}/[0-9a-f]{32}\\.[a-z0-9]{1,10}$'",
            name="ck_upload_assets_storage_key_format",
        ).ddl_if(dialect="postgresql"),
        CheckConstraint(
            "(state = 'PENDING' AND purpose = 'POST' "
            "AND owner_user_id IS NOT NULL AND blog_id IS NULL "
            "AND expires_at IS NOT NULL AND bound_at IS NULL "
            "AND delete_after IS NULL AND deleted_at IS NULL "
            "AND scan_completed_at IS NOT NULL) OR "
            "(state = 'ACTIVE' AND owner_user_id IS NOT NULL "
            "AND expires_at IS NULL AND bound_at IS NOT NULL "
            "AND delete_after IS NULL AND deleted_at IS NULL "
            "AND scan_completed_at IS NOT NULL AND "
            "((purpose = 'POST' AND blog_id IS NOT NULL) OR "
            "(purpose IN ('PROFILE_IMAGE', 'COVER_IMAGE') AND blog_id IS NULL))) OR "
            "(state = 'DELETE_PENDING' AND delete_after IS NOT NULL "
            "AND blog_id IS NULL AND expires_at IS NULL "
            "AND deleted_at IS NULL AND scan_completed_at IS NOT NULL) OR "
            "(state = 'DELETED' AND blog_id IS NULL AND expires_at IS NULL "
            "AND delete_after IS NULL AND deleted_at IS NOT NULL "
            "AND original_filename IS NULL AND scan_completed_at IS NOT NULL)",
            name="ck_upload_assets_state_shape",
        ),
        Index(
            "ix_upload_assets_owner_state_created",
            "owner_user_id",
            "state",
            "created_at",
        ),
        Index("ix_upload_assets_blog_id", "blog_id"),
        Index("ix_upload_assets_expires_at", "expires_at"),
        Index("ix_upload_assets_state_delete_after", "state", "delete_after"),
        Index(
            "uq_upload_assets_active_profile_purpose",
            "owner_user_id",
            "purpose",
            unique=True,
            sqlite_where=and_(
                state == "ACTIVE",
                purpose.in_(("PROFILE_IMAGE", "COVER_IMAGE")),
            ),
            postgresql_where=and_(
                state == "ACTIVE",
                purpose.in_(("PROFILE_IMAGE", "COVER_IMAGE")),
            ),
        ),
    )

class SavedPost(Base):
    __tablename__ = "saved_posts"

    id = Column(Integer, primary_key=True, index=True)
    post_id = Column(Integer, ForeignKey("blogs.id", ondelete="CASCADE"), nullable=False)
    user_id = Column(Integer, ForeignKey("users.id", ondelete="CASCADE"), nullable=False)
    created_at = Column(DateTime, default=_utc_now_naive)

    post = relationship("Blog", back_populates="saved_by")
    user = relationship("User", back_populates="saved_posts")

    __table_args__ = (
        UniqueConstraint('post_id', 'user_id', name='unique_saved_post'),
    )

class PostLike(Base):
    __tablename__ = "post_likes"
    
    id = Column(Integer, primary_key=True, index=True)
    post_id = Column(Integer, ForeignKey("blogs.id", ondelete="CASCADE"), nullable=False)
    user_id = Column(Integer, ForeignKey("users.id", ondelete="CASCADE"), nullable=False)
    created_at = Column(DateTime, default=_utc_now_naive)
    
    # Relationships
    post = relationship("Blog", back_populates="likes")
    user = relationship("User", back_populates="likes")
    
    # Add a unique constraint to ensure a user can only like a post once
    __table_args__ = (
        UniqueConstraint('post_id', 'user_id', name='unique_post_like'),
    )

class Comment(Base):
    __tablename__ = "comments"
    
    id = Column(Integer, primary_key=True, index=True)
    content = Column(Text, nullable=False)
    created_at = Column(DateTime, default=_utc_now_naive)
    updated_at = Column(DateTime, default=_utc_now_naive, onupdate=_utc_now_naive)
    
    # Relations
    user_id = Column(Integer, ForeignKey("users.id", ondelete="CASCADE"), nullable=False)
    blog_id = Column(Integer, ForeignKey("blogs.id", ondelete="CASCADE"), nullable=False)
    # Add parent_id for threaded comments
    parent_id = Column(Integer, ForeignKey("comments.id", ondelete="CASCADE"), nullable=True)
    
    # Relationships
    user = relationship("User", back_populates="comments")
    blog = relationship("Blog", back_populates="comments")
    # Add relationships for parent/child comments
    replies = relationship("Comment", back_populates="parent", cascade="all, delete-orphan")
    parent = relationship("Comment", back_populates="replies", remote_side=[id])
    # Add likes relationship
    likes = relationship("CommentLike", back_populates="comment", cascade="all, delete-orphan")

class CommentLike(Base):
    __tablename__ = "comment_likes"
    
    id = Column(Integer, primary_key=True, index=True)
    comment_id = Column(Integer, ForeignKey("comments.id", ondelete="CASCADE"), nullable=False)
    user_id = Column(Integer, ForeignKey("users.id", ondelete="CASCADE"), nullable=False)
    created_at = Column(DateTime, default=_utc_now_naive)
    
    # Relationships
    comment = relationship("Comment", back_populates="likes")
    user = relationship("User", back_populates="comment_likes")
    
    # Add a unique constraint to ensure a user can only like a comment once
    __table_args__ = (
        UniqueConstraint('comment_id', 'user_id', name='unique_comment_like'),
    )

class PasswordReset(Base):
    __tablename__ = "password_resets"
    id = Column(Integer, primary_key=True, index=True)
    user_id = Column(
        Integer,
        ForeignKey("users.id", ondelete="CASCADE"),
        nullable=False,
        unique=True,
        index=True,
    )
    token = Column(String(64), unique=True, nullable=True, index=True)
    created_at = Column(
        DateTime(timezone=True),
        default=_utc_now_naive,
        server_default=func.now(),
        nullable=False,
    )
    expires_at = Column(DateTime(timezone=True), nullable=True)
    used = Column(Boolean, default=False, nullable=False)
    delivery_status = Column(String(16), default="PENDING", nullable=False, index=True)
    delivery_attempted_at = Column(DateTime(timezone=True), nullable=True)
    delivery_claim_digest = Column(String(64), nullable=True)

    __table_args__ = (
        CheckConstraint(
            "delivery_status IN ('PENDING', 'PROCESSING', 'DELIVERED', 'FAILED')",
            name="ck_password_reset_delivery_status",
        ),
        CheckConstraint(
            "delivery_claim_digest IS NULL OR length(delivery_claim_digest) = 64",
            name="ck_password_reset_delivery_claim_digest",
        ),
        CheckConstraint(
            "delivery_claim_digest IS NULL OR "
            "delivery_claim_digest ~ '^[0-9a-f]{64}$'",
            name="ck_password_reset_delivery_claim_digest_lower_hex",
        ).ddl_if(dialect="postgresql"),
        CheckConstraint(
            "token IS NULL OR token ~ '^[0-9a-f]{64}$'",
            name="ck_password_reset_token_lower_hex",
        ).ddl_if(dialect="postgresql"),
    )
