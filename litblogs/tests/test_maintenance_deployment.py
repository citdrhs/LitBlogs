from __future__ import annotations

from pathlib import Path

BACKEND_DIR = Path(__file__).resolve().parents[1]
ROOT_DIR = BACKEND_DIR.parent


PASSWORD_RESET_SERVICE = "deploy/systemd/litblogs-password-reset.service"
PASSWORD_RESET_TIMER = "deploy/systemd/litblogs-password-reset.timer"
UPLOAD_RECONCILIATION_SERVICE = (
    "deploy/systemd/litblogs-upload-reconciliation.service"
)
UPLOAD_RECONCILIATION_TIMER = "deploy/systemd/litblogs-upload-reconciliation.timer"
PASSWORD_RESET_PORT_POLICY_READY = (
    "/run/litblogs-maintenance-egress/password-reset.port-policy-ready"
)
UPLOAD_RECONCILIATION_PORT_POLICY_READY = (
    "/run/litblogs-maintenance-egress/upload-reconciliation.port-policy-ready"
)


def _read(relative_path: str) -> str:
    return (ROOT_DIR / relative_path).read_text(encoding="utf-8")


def test_release_admission_requires_external_maintenance_jobs_and_units():
    import deployment_check

    required = set(deployment_check.REQUIRED_RELEASE_FILES)

    assert {
        PASSWORD_RESET_SERVICE,
        PASSWORD_RESET_TIMER,
        UPLOAD_RECONCILIATION_SERVICE,
        UPLOAD_RECONCILIATION_TIMER,
        "litblogs/password_reset_job.py",
        "litblogs/upload_reconciliation_job.py",
    } <= required


def test_maintenance_services_are_bounded_and_hardened_oneshots():
    services = {
        PASSWORD_RESET_SERVICE: (
            "password_reset_job",
            "litblogs-reset",
            "litblogs-reset",
        ),
        UPLOAD_RECONCILIATION_SERVICE: (
            "upload_reconciliation_job",
            "litblogs",
            "litblogs",
        ),
    }
    hardening = {
        "Type=oneshot",
        "RuntimeMaxSec=300",
        "TimeoutStartSec=300",
        "NoNewPrivileges=true",
        "CapabilityBoundingSet=",
        "AmbientCapabilities=",
        "PrivateTmp=true",
        "PrivateDevices=true",
        "ProtectSystem=strict",
        "ProtectHome=true",
        "ProtectKernelTunables=true",
        "ProtectKernelModules=true",
        "ProtectKernelLogs=true",
        "ProtectControlGroups=true",
        "ProtectClock=true",
        "RestrictSUIDSGID=true",
        "RestrictNamespaces=true",
        "RestrictRealtime=true",
        "LockPersonality=true",
        "MemoryDenyWriteExecute=true",
        "RemoveIPC=true",
        "SystemCallArchitectures=native",
        "IPAddressDeny=any",
    }

    for relative_path, (module, user, group) in services.items():
        unit = _read(relative_path)
        assert hardening <= set(unit.splitlines())
        assert f"User={user}" in unit
        assert f"Group={group}" in unit
        assert "UMask=0077" in unit
        assert "RestrictAddressFamilies=AF_INET AF_INET6" in unit
        assert "AF_UNIX" not in unit
        assert (
            f"ExecStart=/opt/litblogs/current/.venv/bin/python -m {module}" in unit
        )
        assert "/opt/litblogs/venv/" not in unit
        assert "IPAddressAllow=0.0.0.0/0" not in unit
        assert "IPAddressAllow=::/0" not in unit


def test_maintenance_services_fail_closed_without_exact_egress_drop_ins():
    reset = _read(PASSWORD_RESET_SERVICE)
    reset_timer = _read(PASSWORD_RESET_TIMER)
    cleanup = _read(UPLOAD_RECONCILIATION_SERVICE)
    cleanup_timer = _read(UPLOAD_RECONCILIATION_TIMER)

    reset_condition = (
        "ConditionPathExists=/etc/systemd/system/"
        "litblogs-password-reset.service.d/egress.conf"
    )
    cleanup_condition = (
        "ConditionPathExists=/etc/systemd/system/"
        "litblogs-upload-reconciliation.service.d/egress.conf"
    )
    reset_port_policy_condition = (
        f"ConditionPathExists={PASSWORD_RESET_PORT_POLICY_READY}"
    )
    cleanup_port_policy_condition = (
        f"ConditionPathExists={UPLOAD_RECONCILIATION_PORT_POLICY_READY}"
    )
    assert reset_condition in reset
    assert reset_condition in reset_timer
    assert reset_port_policy_condition in reset
    assert reset_port_policy_condition in reset_timer
    assert cleanup_condition in cleanup
    assert cleanup_condition in cleanup_timer
    assert cleanup_port_policy_condition in cleanup
    assert cleanup_port_policy_condition in cleanup_timer
    assert "ReadWritePaths=/var/lib/litblogs/uploads" in cleanup
    assert "upload_scanner" not in cleanup
    assert "clam" not in cleanup.lower()
    assert "smtp" not in cleanup.lower()


def test_password_reset_service_has_dedicated_identity_env_and_no_upload_surface():
    reset = _read(PASSWORD_RESET_SERVICE)

    assert "User=litblogs-reset" in reset
    assert "Group=litblogs-reset" in reset
    assert "EnvironmentFile=/etc/litblogs/password-reset.env" in reset
    assert "EnvironmentFile=/etc/litblogs/litblogs.env" not in reset
    assert (
        "InaccessiblePaths=/etc/litblogs/litblogs.env /var/lib/litblogs/uploads"
        in reset
    )
    assert "ReadWritePaths=" not in reset
    assert "ExecStartPre=" not in reset

    reconciliation = _read(UPLOAD_RECONCILIATION_SERVICE)
    assert "User=litblogs" in reconciliation
    assert "Group=litblogs" in reconciliation
    assert "EnvironmentFile=/etc/litblogs/litblogs.env" in reconciliation
    assert "ReadWritePaths=/var/lib/litblogs/uploads" in reconciliation


def test_maintenance_timers_are_persistent_jittered_and_non_push():
    for relative_path, service in (
        (PASSWORD_RESET_TIMER, "litblogs-password-reset.service"),
        (UPLOAD_RECONCILIATION_TIMER, "litblogs-upload-reconciliation.service"),
    ):
        timer = _read(relative_path)
        assert "OnCalendar=" in timer
        assert "Persistent=true" in timer
        assert "RandomizedDelaySec=" in timer
        assert "AccuracySec=" in timer
        assert f"Unit={service}" in timer
        assert "WantedBy=timers.target" in timer
        assert "reminder" not in timer.lower()


def test_operator_docs_gate_maintenance_timers_on_reviewed_exact_egress():
    documents = [
        _read("deploy/README.md").lower(),
        _read("docs/operations/production-runbook.md").lower(),
    ]

    for document in documents:
        assert "litblogs-password-reset.timer" in document
        assert "litblogs-upload-reconciliation.timer" in document
        assert "exact resolved postgresql addresses" in document
        assert "exact resolved smtp addresses" in document
        assert "database-only egress" in document
        assert "egress.conf" in document
        assert "must remain disabled" in document
        assert "no malware scanner" in document
        assert "do not enable litblogs-reminders.timer" in document

    runbook = documents[1]
    stop_workers = runbook.index(
        "systemctl stop litblogs-password-reset.timer "
        "litblogs-upload-reconciliation.timer"
    )
    migrate = runbook.index("alembic.ini upgrade head", stop_workers)
    activate = runbook.index("release_switch.py", migrate)
    smoke_workers = runbook.index("systemctl start litblogs-password-reset.service", activate)
    enable_workers = runbook.index("systemctl enable --now litblogs-password-reset.timer", smoke_workers)

    assert stop_workers < migrate < activate < smoke_workers < enable_workers


def test_repository_policy_enforces_packaged_maintenance_contract():
    validator = _read("scripts/validate-repository-policy.py")

    for required in (
        PASSWORD_RESET_SERVICE,
        PASSWORD_RESET_TIMER,
        UPLOAD_RECONCILIATION_SERVICE,
        UPLOAD_RECONCILIATION_TIMER,
        "litblogs/password_reset_job.py",
        "litblogs/upload_reconciliation_job.py",
    ):
        assert required in validator

    for reset_boundary in (
        "User=litblogs-reset",
        "Group=litblogs-reset",
        "EnvironmentFile=/etc/litblogs/password-reset.env",
        "InaccessiblePaths=/etc/litblogs/litblogs.env /var/lib/litblogs/uploads",
    ):
        assert reset_boundary in validator
