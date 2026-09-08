from pathlib import Path

BACKEND_DIR = Path(__file__).resolve().parents[1]


def test_operator_runtime_protects_email_verification_state_from_login_roles():
    source = (BACKEND_DIR / "operator_runtime.py").read_text(encoding="utf-8")
    normalized = " ".join(source.split())

    required_relations = normalized.split(
        "WITH required_relations(relation_oid) AS (", 1
    )[1].split("expected_operator_functions", 1)[0]
    assert "'public.email_verifications'" in required_relations
    assert "has_direct_table_privilege" in normalized
    assert "has_direct_sequence_privilege" in normalized
    assert "operator_function_acl_is_exact" in normalized
