# models.py
from datetime import datetime
from enum import Enum

from sqlalchemy import (
    Boolean,
    CheckConstraint,
    Column,
    DateTime,
    ForeignKey,
    Integer,
    String,
    Text,
    UniqueConstraint,
    func,
)
from sqlalchemy import Enum as SQLAlchemyEnum
from sqlalchemy.orm import relationship

from base import Base


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
    bio = Column(String(500), nullable=True)
    profile_image = Column(String(255), nullable=True)
    cover_image = Column(String(255), nullable=True)
    avatar_id = Column(String(50), nullable=True)
    avatar_color = Column(String(50), nullable=True)
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
    email = Column(String, unique=True, index=True)
    hashed_password = Column(String)
    user_id = Column(Integer, ForeignKey("users.id"))
    user = relationship("User", backref="teacher_profile")
    classes = relationship("Class", back_populates="teacher")

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
    updated_at = Column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=False)

    assignment = relationship("Assignment", back_populates="drafts")
    student = relationship("User", back_populates="assignment_drafts")

    __table_args__ = (
        UniqueConstraint('assignment_id', 'student_id', name='unique_assignment_draft'),
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
    student = relationship("User", back_populates="enrolled_classes")
    class_ = relationship("Class", back_populates="students")

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

class SavedPost(Base):
    __tablename__ = "saved_posts"

    id = Column(Integer, primary_key=True, index=True)
    post_id = Column(Integer, ForeignKey("blogs.id", ondelete="CASCADE"), nullable=False)
    user_id = Column(Integer, ForeignKey("users.id", ondelete="CASCADE"), nullable=False)
    created_at = Column(DateTime, default=datetime.utcnow)

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
    created_at = Column(DateTime, default=datetime.utcnow)
    
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
    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)
    
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
    created_at = Column(DateTime, default=datetime.utcnow)
    
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
    user_id = Column(Integer, ForeignKey("users.id"), nullable=False)
    token = Column(String(64), unique=True, nullable=False, index=True)
    created_at = Column(DateTime(timezone=True), server_default=func.now())
    expires_at = Column(DateTime(timezone=True), nullable=False)
    used = Column(Boolean, default=False)
