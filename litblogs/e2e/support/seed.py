from __future__ import annotations

import json
import os
import secrets
import stat
from pathlib import Path

from sqlalchemy import create_engine
from sqlalchemy.orm import Session

import models
from auth_security import hash_password


def _credential(role: str, suffix: str) -> dict[str, str]:
    normalized = role.lower().replace("_", "-")
    return {
        "username": f"e2e-{normalized}-{suffix}",
        "email": f"e2e-{normalized}-{suffix}@example.com",
        "password": f"E2E-{secrets.token_urlsafe(24)}-aA1!",
    }


def main() -> None:
    database_url = os.environ["E2E_SEED_DATABASE_URL"]
    output_path = Path(os.environ["E2E_CREDENTIALS_FILE"]).resolve()
    suffix = secrets.token_hex(6)
    role_specs = {
        "admin": models.UserRole.ADMIN,
        "teacher": models.UserRole.TEACHER,
        "student": models.UserRole.STUDENT,
        "student2": models.UserRole.STUDENT,
        "outsider": models.UserRole.STUDENT,
    }
    credentials = {
        name: _credential(name, suffix)
        for name in role_specs
    }

    engine = create_engine(database_url, pool_pre_ping=True)
    try:
        with Session(engine) as db:
            users: dict[str, models.User] = {}
            for name, role in role_specs.items():
                credential = credentials[name]
                user = models.User(
                    username=credential["username"],
                    email=credential["email"],
                    password=hash_password(credential["password"]),
                    first_name=name.capitalize(),
                    last_name="Journey",
                    role=role,
                    is_admin=role == models.UserRole.ADMIN,
                )
                db.add(user)
                users[name] = user
            db.flush()
            teacher = users["teacher"]
            db.add(
                models.Teacher(
                    name="E2E Teacher Journey",
                    email=teacher.email,
                    user_id=teacher.id,
                )
            )
            db.commit()
            for name, user in users.items():
                credentials[name].update(
                    {
                        "id": user.id,
                        "role": user.role.value,
                    }
                )
    finally:
        engine.dispose()

    output_path.write_text(
        json.dumps({"run_id": suffix, "users": credentials}),
        encoding="utf-8",
    )
    try:
        output_path.chmod(stat.S_IRUSR | stat.S_IWUSR)
    except OSError:
        pass


if __name__ == "__main__":
    main()
