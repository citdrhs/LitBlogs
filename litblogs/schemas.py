from datetime import datetime
from enum import Enum

from pydantic import BaseModel, ConfigDict, EmailStr, Field, field_validator

MAX_ASSIGNMENT_CONTENT_LENGTH = 1_000_000


# Blog schemas
class BlogBase(BaseModel):
    title: str
    content: str

class BlogCreate(BaseModel):
    title: str
    content: str  # This will now contain HTML
    code_snippets: list[dict] | None = None
    media: list[dict] | None = None
    polls: list[dict] | None = None
    files: list[dict] | None = None

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
    username: str
    email: EmailStr
    first_name: str | None = None
    last_name: str | None = None

class UserCreate(BaseModel):
    username: str
    email: EmailStr
    password: str
    first_name: str | None = None
    last_name: str | None = None
    role: str
    access_code: str | None = None

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
    name: str
    description: str | None = None

class ClassCreate(ClassBase):
    pass

class ClassResponse(ClassBase):
    model_config = ConfigDict(from_attributes=True)

    id: int
    access_code: str
    teacher_id: int
    created_at: datetime
    posts_visibility: str | None = None

class AssignmentCreate(BaseModel):
    title: str
    description: str | None = None
    due_date: datetime
    allow_late: bool | None = True
    visibility: str | None = "class"

class AssignmentUpdate(BaseModel):
    title: str
    description: str | None = None
    due_date: datetime
    allow_late: bool | None = True
    visibility: str | None = "class"

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

class AssignmentSubmissionCreate(BaseModel):
    content: str | None = Field(
        default=None,
        max_length=MAX_ASSIGNMENT_CONTENT_LENGTH,
    )
    expected_draft_revision: int = Field(ge=0, le=2_147_483_646)

class AssignmentDraftUpdate(BaseModel):
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

class TeacherCreate(BaseModel):
    name: str
    email: str
    password: str

class Teacher(TeacherBase):
    model_config = ConfigDict(from_attributes=True)

class CodeSnippet(BaseModel):
    language: str
    code: str

class Media(BaseModel):
    type: str  # 'image', 'gif', 'video'
    url: str
    alt: str | None = None

class Poll(BaseModel):
    options: list[str]

class File(BaseModel):
    name: str
    url: str
