from datetime import datetime
from enum import Enum
from typing import Annotated, Literal

from pydantic import BaseModel, ConfigDict, EmailStr, Field, field_validator

from auth_security import MAX_PASSWORD_BYTES

MAX_RICH_TEXT_LENGTH = 100_000
MAX_SHORT_TEXT_LENGTH = 10_000
MAX_DESCRIPTION_LENGTH = 50_000
MAX_ASSIGNMENT_CONTENT_LENGTH = 1_000_000


def validate_password_request_bytes(value: str) -> str:
    if len(value.encode("utf-8")) > MAX_PASSWORD_BYTES:
        raise ValueError(
            f"password must not exceed {MAX_PASSWORD_BYTES} UTF-8 bytes"
        )
    return value


class StrictRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")


class CodeSnippet(StrictRequest):
    language: str = Field(min_length=1, max_length=50)
    code: str = Field(min_length=1, max_length=20_000)


class Media(StrictRequest):
    type: Literal["image", "gif", "video"]
    url: str = Field(min_length=1, max_length=2_048)
    alt: str | None = Field(default=None, max_length=500)


class Poll(StrictRequest):
    options: list[Annotated[str, Field(min_length=1, max_length=200)]] = Field(
        min_length=2,
        max_length=10,
    )


class File(StrictRequest):
    name: str = Field(min_length=1, max_length=255)
    url: str = Field(min_length=1, max_length=2_048)


# Blog schemas
class BlogBase(StrictRequest):
    title: str = Field(min_length=1, max_length=200)
    content: str = Field(min_length=1, max_length=MAX_RICH_TEXT_LENGTH)

class BlogCreate(BlogBase):
    code_snippets: list[CodeSnippet] | None = Field(default=None, max_length=20)
    media: list[Media] | None = Field(default=None, max_length=20)
    polls: list[Poll] | None = Field(default=None, max_length=10)
    files: list[File] | None = Field(default=None, max_length=20)

class BlogResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    title: str
    content: str
    created_at: datetime
    owner_id: int
    class_id: int
    author: str | None = None
    author_profile_image: str | None = None
    likes: int = 0
    comments: int = 0
    
    # AI Detection fields
    ai_percentage: int | None = None
    ai_highlighted_html: str | None = None
    ai_sentence_analysis: str | None = None

# User schemas
class UserRole(str, Enum):
    STUDENT = "student"
    TEACHER = "teacher"
    ADMIN = "admin"

class UserBase(BaseModel):
    username: str = Field(min_length=3, max_length=50)
    email: EmailStr = Field(max_length=100)
    first_name: str | None = Field(default=None, max_length=50)
    last_name: str | None = Field(default=None, max_length=50)

class UserCreate(StrictRequest):
    username: str = Field(min_length=3, max_length=50)
    email: EmailStr = Field(max_length=100)
    password: str = Field(min_length=15, max_length=1_024)
    first_name: str | None = Field(default=None, max_length=50)
    last_name: str | None = Field(default=None, max_length=50)
    role: str = Field(max_length=16)
    teacher_invitation_token: str | None = Field(default=None, max_length=512)

    @field_validator("password")
    @classmethod
    def validate_password_size(cls, value: str) -> str:
        return validate_password_request_bytes(value)

    @field_validator("role")
    @classmethod
    def validate_role(cls, value: str) -> str:
        if value not in {"STUDENT", "TEACHER", "ADMIN"}:
            raise ValueError("Invalid role")
        return value

class ClassInfo(BaseModel):
    id: int
    name: str
    access_code: str

class UserResponse(UserBase):
    model_config = ConfigDict(from_attributes=True)

    id: int
    role: str
    is_admin: bool = False
    created_at: datetime
    token: str | None = None
    class_info: ClassInfo | None = None

class ClassBase(BaseModel):
    name: str = Field(min_length=1, max_length=100)
    description: str | None = Field(default=None, max_length=5_000)

class ClassCreate(ClassBase, StrictRequest):
    pass


class JoinClassRequest(StrictRequest):
    access_code: str = Field(min_length=6, max_length=6, pattern=r"^[A-Z0-9]{6}$")


class CommentCreate(StrictRequest):
    content: str = Field(min_length=1, max_length=MAX_SHORT_TEXT_LENGTH)
    parent_id: int | None = Field(default=None, gt=0)

    @field_validator("content")
    @classmethod
    def reject_blank_content(cls, value: str) -> str:
        if not value.strip():
            raise ValueError("content must not be blank")
        return value


class ChangePasswordRequest(StrictRequest):
    current_password: str = Field(min_length=1, max_length=1_024)
    new_password: str = Field(min_length=15, max_length=1_024)

    @field_validator("current_password", "new_password")
    @classmethod
    def validate_password_sizes(cls, value: str) -> str:
        return validate_password_request_bytes(value)


class UserStatusUpdate(StrictRequest):
    disabled: bool


class SubmissionReplyCreate(StrictRequest):
    content: str = Field(min_length=1, max_length=MAX_SHORT_TEXT_LENGTH)

    @field_validator("content")
    @classmethod
    def normalize_content(cls, value: str) -> str:
        normalized = value.strip()
        if not normalized:
            raise ValueError("content must not be blank")
        return normalized


class StudentNotesUpdate(StrictRequest):
    notes: str = Field(default="", max_length=MAX_SHORT_TEXT_LENGTH)


class ProfileUpdate(StrictRequest):
    bio: str | None = Field(default=None, max_length=500)
    first_name: str | None = Field(default=None, max_length=50)
    last_name: str | None = Field(default=None, max_length=50)
    avatar_id: str | None = Field(default=None, max_length=50)
    avatar_color: str | None = Field(default=None, max_length=50)
    profile_image: str | None = Field(default=None, max_length=255)
    cover_image: str | None = Field(default=None, max_length=255)

class ClassResponse(ClassBase):
    model_config = ConfigDict(from_attributes=True)

    id: int
    access_code: str
    teacher_id: int
    created_at: datetime
    posts_visibility: str | None = None

class AssignmentCreate(StrictRequest):
    title: str = Field(min_length=1, max_length=200)
    description: str | None = Field(default=None, max_length=MAX_DESCRIPTION_LENGTH)
    due_date: datetime
    allow_late: bool | None = True
    visibility: Literal["class", "private"] | None = "class"

class AssignmentUpdate(StrictRequest):
    title: str = Field(min_length=1, max_length=200)
    description: str | None = Field(default=None, max_length=MAX_DESCRIPTION_LENGTH)
    due_date: datetime
    allow_late: bool | None = True
    visibility: Literal["class", "private"] | None = "class"

class AssignmentResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    class_id: int
    title: str
    description: str | None = None
    due_date: datetime
    created_at: datetime
    created_by: int
    allow_late: bool
    visibility: str

class AssignmentSubmissionCreate(StrictRequest):
    content: str | None = Field(
        default=None,
        max_length=MAX_ASSIGNMENT_CONTENT_LENGTH,
    )
    expected_draft_revision: int = Field(ge=0, le=2_147_483_646)

class AssignmentDraftUpdate(StrictRequest):
    content: str | None = Field(
        default=None,
        max_length=MAX_ASSIGNMENT_CONTENT_LENGTH,
    )
    expected_revision: int = Field(ge=0, le=2_147_483_646)

class AssignmentSubmissionResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    assignment_id: int
    student_id: int
    submitted_at: datetime
    content: str | None = None
    is_late: bool
    
    # AI Detection fields
    ai_percentage: int | None = None
    ai_highlighted_html: str | None = None
    ai_sentence_analysis: str | None = None

class TeacherBase(BaseModel):
    id: int
    name: str
    email: str
    classes: list[ClassBase]

class TeacherCreate(StrictRequest):
    name: str = Field(min_length=1, max_length=100)
    email: EmailStr = Field(max_length=100)
    password: str = Field(min_length=15, max_length=1_024)

    @field_validator("password")
    @classmethod
    def validate_password_size(cls, value: str) -> str:
        return validate_password_request_bytes(value)

class Teacher(TeacherBase):
    model_config = ConfigDict(from_attributes=True)
