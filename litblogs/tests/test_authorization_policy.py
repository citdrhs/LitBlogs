import ast
import re
from pathlib import Path

from fastapi.routing import APIRoute

import access_control
import main

EXPECTED_PUBLIC_API_ROUTES = frozenset(
    {
        ("GET", "/api/"),
        ("GET", "/api/health/live"),
        ("GET", "/api/health/ready"),
        ("GET", "/api/runtime-config"),
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

EXPECTED_API_ROUTES = frozenset(
    {
        ("DELETE", "/api/classes/{class_id}"),
        ("DELETE", "/api/classes/{class_id}/posts/{post_id}"),
        ("DELETE", "/api/push/unsubscribe"),
        ("DELETE", "/api/upload/{file_path:path}"),
        ("DELETE", "/api/user/account"),
        ("GET", "/api/"),
        ("GET", "/api/health/live"),
        ("GET", "/api/health/ready"),
        ("GET", "/api/assignments/{assignment_id}/draft"),
        ("GET", "/api/auth/session"),
        ("GET", "/api/classes"),
        ("GET", "/api/classes/{class_id}/analytics"),
        ("GET", "/api/classes/{class_id}/assignments"),
        ("GET", "/api/classes/{class_id}/assignments/{assignment_id}/submissions"),
        (
            "GET",
            "/api/classes/{class_id}/assignments/{assignment_id}/submissions/{submission_id}/replies",
        ),
        ("GET", "/api/classes/{class_id}/details"),
        ("GET", "/api/classes/{class_id}/posts"),
        ("GET", "/api/classes/{class_id}/posts/{post_id}"),
        ("GET", "/api/classes/{class_id}/posts/{post_id}/comments"),
        ("GET", "/api/classes/{class_id}/posts/{post_id}/likes"),
        ("GET", "/api/classes/{class_id}/students"),
        ("GET", "/api/classes/{class_id}/students/{student_id}"),
        ("GET", "/api/classes/{class_id}/students/{student_id}/posts"),
        ("GET", "/api/comments/{comment_id}/replies"),
        ("GET", "/api/push/public-key"),
        ("GET", "/api/push/subscription"),
        ("GET", "/api/runtime-config"),
        ("GET", "/api/student/classes"),
        ("GET", "/api/student/posts"),
        ("GET", "/api/teacher/analytics"),
        ("GET", "/api/teacher/dashboard"),
        ("GET", "/api/uploads/{file_path:path}"),
        ("GET", "/api/user/id/{user_id}"),
        ("GET", "/api/user/posts"),
        ("GET", "/api/user/profile"),
        ("GET", "/api/user/profile/{user_id}"),
        ("GET", "/api/user/saved-posts"),
        ("GET", "/api/user/settings"),
        ("GET", "/api/user/{user_id}/posts"),
        ("GET", "/api/users"),
        ("POST", "/api/assignments/{assignment_id}/submit"),
        ("POST", "/api/auth/forgot-password"),
        ("POST", "/api/auth/change-password"),
        ("POST", "/api/auth/google-login"),
        ("POST", "/api/auth/google-signup"),
        ("POST", "/api/auth/login"),
        ("POST", "/api/auth/logout"),
        ("POST", "/api/auth/microsoft-login"),
        ("POST", "/api/auth/microsoft-signup"),
        ("POST", "/api/auth/register"),
        ("POST", "/api/auth/reset-password"),
        ("POST", "/api/classes"),
        ("POST", "/api/classes/{class_id}/assignments"),
        (
            "POST",
            "/api/classes/{class_id}/assignments/{assignment_id}/submissions/{submission_id}/replies",
        ),
        ("POST", "/api/classes/{class_id}/posts"),
        ("POST", "/api/classes/{class_id}/posts/{post_id}/comments"),
        ("POST", "/api/classes/{class_id}/posts/{post_id}/like"),
        ("POST", "/api/classes/{class_id}/posts/{post_id}/save"),
        ("POST", "/api/comments/{comment_id}/like"),
        ("POST", "/api/push/subscribe"),
        ("POST", "/api/student/join-class"),
        ("POST", "/api/upload"),
        ("POST", "/api/upload/file"),
        ("POST", "/api/upload/image"),
        ("POST", "/api/upload/video"),
        ("POST", "/api/user/update-profile"),
        ("POST", "/api/user/upload-cover-image"),
        ("POST", "/api/user/upload-profile-image"),
        ("PUT", "/api/assignments/{assignment_id}/draft"),
        ("PUT", "/api/classes/{class_id}/archive"),
        ("PUT", "/api/classes/{class_id}/assignments/{assignment_id}"),
        ("PUT", "/api/classes/{class_id}/posts/{post_id}"),
        ("PUT", "/api/classes/{class_id}/restore"),
        ("PUT", "/api/classes/{class_id}/students/{student_id}/notes"),
        ("PUT", "/api/user/settings"),
        ("PUT", "/api/users/{user_id}/status"),
    }
)

REMOVED_UNSAFE_ROUTES = frozenset(
    {
        ("GET", "/api/blogs"),
        ("POST", "/api/blogs"),
        ("DELETE", "/api/blogs/{blog_id}"),
        ("GET", "/api/debug/classes"),
        ("GET", "/api/debug/post/{post_id}"),
        ("GET", "/api/test-db"),
        ("POST", "/api/verify-class-code"),
    }
)

CONTENT_UPLOAD_FUNCTIONS_REBASED_SEPARATELY = frozenset(
    {
        "delete_file",
        "download_file",
        "upload_cover_image",
        "upload_file",
        "upload_generic_file",
        "upload_image",
        "upload_profile_image",
        "upload_video",
    }
)
BANNED_EXCEPTION_DISCLOSURE = tuple(
    re.compile(pattern)
    for pattern in (
        r"detail\s*=\s*str\(e\)",
        r"detail\s*=\s*f[^\n]*\{(?:str\()?e",
        r"print\([^\n]*(?:str\(e\)|\{e\}|\{exc\})",
    )
)


def _api_operations():
    operations = {}
    for route in main.app.routes:
        if not isinstance(route, APIRoute) or not route.path.startswith("/api"):
            continue
        for method in route.methods - {"HEAD", "OPTIONS"}:
            operations[(method, route.path)] = route
    return operations


def _dependency_calls(dependant):
    calls = {dependency.call for dependency in dependant.dependencies}
    for dependency in dependant.dependencies:
        calls.update(_dependency_calls(dependency))
    return calls


def test_non_upload_handlers_never_disclose_raw_exception_details():
    main_path = Path(main.__file__)
    source = main_path.read_text(encoding="utf-8")
    tree = ast.parse(source)
    violations = []

    for node in ast.walk(tree):
        if not isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            continue
        if node.name in CONTENT_UPLOAD_FUNCTIONS_REBASED_SEPARATELY:
            continue
        function_source = ast.get_source_segment(source, node) or ""
        if any(pattern.search(function_source) for pattern in BANNED_EXCEPTION_DISCLOSURE):
            violations.append(node.name)

    assert violations == []


def test_public_api_routes_are_explicit_and_complete():
    assert access_control.PUBLIC_API_ROUTES == EXPECTED_PUBLIC_API_ROUTES


def test_api_route_inventory_is_explicit_and_complete():
    assert frozenset(_api_operations()) == EXPECTED_API_ROUTES


def test_sensitive_legacy_and_diagnostic_routes_are_absent():
    operations = _api_operations()
    assert REMOVED_UNSAFE_ROUTES.isdisjoint(operations)


def test_every_non_public_api_route_requires_authenticated_user():
    operations = _api_operations()
    missing_auth = sorted(
        operation
        for operation, route in operations.items()
        if operation not in EXPECTED_PUBLIC_API_ROUTES
        and main.get_current_user not in _dependency_calls(route.dependant)
    )

    assert missing_auth == []
