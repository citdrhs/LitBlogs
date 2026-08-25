import secrets


def secure_code_matches(supplied: object, configured: object) -> bool:
    if not isinstance(supplied, str) or not isinstance(configured, str):
        return False
    if not supplied.strip() or not configured.strip():
        return False

    try:
        supplied_bytes = supplied.encode("utf-8")
        configured_bytes = configured.encode("utf-8")
    except UnicodeEncodeError:
        return False

    return secrets.compare_digest(supplied_bytes, configured_bytes)
