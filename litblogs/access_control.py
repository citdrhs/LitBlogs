"""Central, default-deny authorization policy for LitBlog resources."""

from fastapi import HTTPException, status
from sqlalchemy.orm import Session

import models

PUBLIC_API_ROUTES = frozenset(
    {
        ("GET", "/api/"),
        ("POST", "/api/auth/forgot-password"),
        ("POST", "/api/auth/google-login"),
        ("POST", "/api/auth/google-signup"),
        ("POST", "/api/auth/login"),
        ("POST", "/api/auth/microsoft-login"),
        ("POST", "/api/auth/microsoft-signup"),
        ("POST", "/api/auth/register"),
        ("POST", "/api/auth/reset-password"),
    }
)


def _role_value(user: models.User) -> str:
    role = getattr(user, "role", "")
    return str(getattr(role, "value", role)).upper()


def _forbidden() -> HTTPException:
    return HTTPException(
        status_code=status.HTTP_403_FORBIDDEN,
        detail="Not authorized to access this resource",
    )


def require_admin(user: models.User) -> None:
    if _role_value(user) != models.UserRole.ADMIN.value:
        raise _forbidden()


def get_teacher_record(db: Session, user: models.User) -> models.Teacher | None:
    if _role_value(user) != models.UserRole.TEACHER.value:
        return None
    return db.query(models.Teacher).filter(models.Teacher.user_id == user.id).first()


def get_class_or_404(db: Session, class_id: int) -> models.Class:
    db_class = db.query(models.Class).filter(models.Class.id == class_id).first()
    if db_class is None or db_class.status == "deleted":
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Class not found")
    return db_class


def teacher_owns_class(db: Session, user: models.User, db_class: models.Class) -> bool:
    teacher = get_teacher_record(db, user)
    return teacher is not None and db_class.teacher_id == teacher.id


def can_access_class(db: Session, user: models.User, db_class: models.Class) -> bool:
    role = _role_value(user)
    if role == models.UserRole.ADMIN.value:
        return True
    if role == models.UserRole.TEACHER.value:
        return teacher_owns_class(db, user, db_class)
    if role != models.UserRole.STUDENT.value:
        return False
    return (
        db.query(models.ClassEnrollment.id)
        .filter(
            models.ClassEnrollment.student_id == user.id,
            models.ClassEnrollment.class_id == db_class.id,
        )
        .first()
        is not None
    )


def require_class_access(db: Session, user: models.User, class_id: int) -> models.Class:
    db_class = get_class_or_404(db, class_id)
    if not can_access_class(db, user, db_class):
        raise _forbidden()
    return db_class


def require_active_class(db_class: models.Class) -> models.Class:
    if db_class.status != "active":
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="This class is not active",
        )
    return db_class


def require_active_class_access(db: Session, user: models.User, class_id: int) -> models.Class:
    return require_active_class(require_class_access(db, user, class_id))


def require_class_owner(db: Session, user: models.User, class_id: int) -> models.Class:
    db_class = get_class_or_404(db, class_id)
    if _role_value(user) == models.UserRole.ADMIN.value:
        return db_class
    if not teacher_owns_class(db, user, db_class):
        raise _forbidden()
    return db_class


def require_active_class_owner(db: Session, user: models.User, class_id: int) -> models.Class:
    return require_active_class(require_class_owner(db, user, class_id))


def require_enrolled_student(
    db: Session,
    class_id: int,
    student_id: int,
) -> tuple[models.User, models.ClassEnrollment]:
    student = (
        db.query(models.User)
        .filter(
            models.User.id == student_id,
            models.User.role == models.UserRole.STUDENT,
        )
        .first()
    )
    if student is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Student not found")

    enrollment = (
        db.query(models.ClassEnrollment)
        .filter(
            models.ClassEnrollment.student_id == student.id,
            models.ClassEnrollment.class_id == class_id,
        )
        .first()
    )
    if enrollment is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Student not enrolled in this class",
        )
    return student, enrollment


def require_post_access(
    db: Session,
    user: models.User,
    class_id: int,
    post_id: int,
) -> tuple[models.Class, models.Blog]:
    db_class = require_class_access(db, user, class_id)
    post = (
        db.query(models.Blog)
        .filter(models.Blog.id == post_id, models.Blog.class_id == db_class.id)
        .first()
    )
    if post is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Post not found")
    return db_class, post


def can_moderate_post(
    db: Session,
    user: models.User,
    db_class: models.Class,
    post: models.Blog,
) -> bool:
    return (
        post.owner_id == user.id
        or _role_value(user) == models.UserRole.ADMIN.value
        or teacher_owns_class(db, user, db_class)
    )


def can_view_post_analysis(
    db: Session,
    user: models.User,
    db_class: models.Class,
    post: models.Blog,
) -> bool:
    return can_moderate_post(db, user, db_class, post)


def require_comment_access(
    db: Session,
    user: models.User,
    comment_id: int,
) -> tuple[models.Class, models.Blog, models.Comment]:
    comment = db.query(models.Comment).filter(models.Comment.id == comment_id).first()
    if comment is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Comment not found")
    post = db.query(models.Blog).filter(models.Blog.id == comment.blog_id).first()
    if post is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Post not found")
    db_class = require_class_access(db, user, post.class_id)
    return db_class, post, comment


def user_class_ids(db: Session, user: models.User) -> list[int]:
    role = _role_value(user)
    if role == models.UserRole.STUDENT.value:
        return [
            class_id
            for (class_id,) in db.query(models.ClassEnrollment.class_id)
            .filter(models.ClassEnrollment.student_id == user.id)
            .all()
        ]
    if role == models.UserRole.TEACHER.value:
        teacher = get_teacher_record(db, user)
        if teacher is None:
            return []
        return [
            class_id
            for (class_id,) in db.query(models.Class.id)
            .filter(models.Class.teacher_id == teacher.id)
            .all()
        ]
    return []


def shared_class_ids(db: Session, viewer: models.User, target: models.User) -> list[int]:
    return sorted(set(user_class_ids(db, viewer)).intersection(user_class_ids(db, target)))


def require_profile_access(
    db: Session,
    viewer: models.User,
    target: models.User,
) -> list[int]:
    if viewer.id == target.id or _role_value(viewer) == models.UserRole.ADMIN.value:
        return user_class_ids(db, target)
    shared_ids = shared_class_ids(db, viewer, target)
    if not shared_ids:
        raise _forbidden()
    return shared_ids


def require_assignment_for_class(
    db: Session,
    user: models.User,
    class_id: int,
    assignment_id: int,
) -> tuple[models.Class, models.Assignment]:
    db_class = require_class_access(db, user, class_id)
    assignment = (
        db.query(models.Assignment)
        .filter(
            models.Assignment.id == assignment_id,
            models.Assignment.class_id == db_class.id,
        )
        .first()
    )
    if assignment is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Assignment not found")
    return db_class, assignment


def require_submission_access(
    db: Session,
    user: models.User,
    class_id: int,
    assignment_id: int,
    submission_id: int,
) -> tuple[models.Class, models.Assignment, models.AssignmentSubmission]:
    db_class, assignment = require_assignment_for_class(
        db,
        user,
        class_id,
        assignment_id,
    )
    submission = (
        db.query(models.AssignmentSubmission)
        .filter(
            models.AssignmentSubmission.id == submission_id,
            models.AssignmentSubmission.assignment_id == assignment.id,
        )
        .first()
    )
    if submission is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Submission not found")

    role = _role_value(user)
    if role == models.UserRole.ADMIN.value or teacher_owns_class(db, user, db_class):
        return db_class, assignment, submission
    if role == models.UserRole.STUDENT.value and submission.student_id == user.id:
        return db_class, assignment, submission
    raise _forbidden()
