"""Container gateway keeps the reviewed ingress limits without serving files."""

import re
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
GATEWAY = ROOT / "deploy/container/nginx.conf"
REFERENCE = ROOT / "deploy/nginx/litblogs.conf"
API_LOCATIONS = (
    "/api/auth/",
    "~ ^/api/(?:upload/image|user/upload-(?:profile|cover)-image)$",
    "= /api/upload/file",
    "~ ^/api/upload(?:/video)?$",
    "/api/",
)


def configuration():
    assert GATEWAY.is_file(), "The container needs its request-limiting gateway"
    return GATEWAY.read_text()


def locations(content):
    return dict(re.findall(r"\blocation\s+([^\n{]+?)\s*\{(.*?)\n\s*\}", content, re.DOTALL))


def directive(content, name):
    match = re.search(rf"^\s*{re.escape(name)}\s+([^;]+);", content, re.MULTILINE)
    return match.group(1) if match else None


def test_gateway_runs_without_root_or_writable_image_directories():
    content = configuration()
    assert directive(content, "pid") == "/tmp/nginx.pid"
    assert directive(content, "listen") == "5000"
    assert directive(content, "user") is None
    assert directive(content, "access_log") == "off"
    assert directive(content, "error_log") == "/dev/stderr crit"
    for name in ("client_body_temp_path", "proxy_temp_path", "fastcgi_temp_path", "uwsgi_temp_path", "scgi_temp_path"):
        assert directive(content, name).startswith("/tmp/")


def test_gateway_preserves_default_body_and_timeout_limits():
    content = configuration()
    reviewed = REFERENCE.read_text()
    for name in ("client_max_body_size", "client_body_timeout", "client_header_timeout", "keepalive_timeout", "send_timeout"):
        assert directive(content, name) == directive(reviewed, name)


def test_gateway_keeps_shared_rate_zones_and_does_not_trust_forwarded_addresses():
    content = configuration()
    reviewed = REFERENCE.read_text()
    zones = re.findall(r"^\s*limit_req_zone\s+([^;]+);", content, re.MULTILINE)
    assert zones == re.findall(r"^\s*limit_req_zone\s+([^;]+);", reviewed, re.MULTILINE)
    assert "real_ip_header" not in content
    assert "set_real_ip_from" not in content
    assert "$http_x_forwarded_for" not in content
    assert directive(content, "limit_req_status") == "429"


@pytest.mark.parametrize("location", API_LOCATIONS)
def test_api_and_upload_locations_preserve_reviewed_limits(location):
    current = locations(configuration())[location]
    reviewed = locations(REFERENCE.read_text())[location]
    for name in ("client_max_body_size", "limit_req", "proxy_connect_timeout", "proxy_read_timeout", "proxy_send_timeout"):
        assert directive(current, name) == directive(reviewed, name)
    assert directive(current, "proxy_pass") == "http://litblogs_backend"


def test_gateway_proxies_all_content_and_preserves_range_and_type_headers():
    content = configuration()
    blocks = locations(content)
    assert set(blocks) == {*API_LOCATIONS, "/", "= /container-gateway-health"}
    assert directive(blocks["/"], "proxy_pass") == "http://litblogs_backend"
    for name in ("root", "alias", "try_files", "proxy_cache", "proxy_hide_header", "proxy_ignore_headers", "proxy_force_ranges"):
        assert directive(content, name) is None
    assert 'proxy_set_header Host $http_host;' in content
    assert 'proxy_set_header Range $http_range;' in content
    assert 'proxy_set_header If-Range $http_if_range;' in content
    assert directive(content, "proxy_buffering") == "off"
    assert directive(content, "proxy_max_temp_file_size") == "0"
    assert directive(content, "proxy_request_buffering") == "on"
    assert directive(content, "proxy_intercept_errors") == "off"
    assert directive(content, "resolver") == "127.0.0.11 valid=10s ipv6=off"
    assert "upstream litblogs_backend {" in content
    assert "zone litblogs_backend 64k;" in content
    assert "server app:5000 resolve;" in content


def test_gateway_health_is_exact_and_contains_no_application_state():
    content = configuration()
    health = locations(content)["= /container-gateway-health"]
    assert directive(health, "return") == "204"
    assert directive(health, "proxy_pass") is None
    assert "LITBLOGS_ORIGIN" not in content


def test_gateway_errors_have_privacy_headers_without_overriding_application_csp_or_cache():
    content = configuration()
    assert "map $upstream_http_content_security_policy $litblogs_gateway_csp" in content
    assert "map $upstream_http_cache_control $litblogs_gateway_cache" in content
    assert "map $upstream_http_strict_transport_security $litblogs_gateway_hsts" in content
    assert '"" "default-src \'none\'; frame-ancestors \'none\'; sandbox";' in content
    assert '"" "no-store";' in content
    assert "add_header Content-Security-Policy $litblogs_gateway_csp always;" in content
    assert "add_header Cache-Control $litblogs_gateway_cache always;" in content
    assert "add_header Strict-Transport-Security $litblogs_gateway_hsts always;" in content
    assert '"" "max-age=31536000; includeSubDomains";' in content
    assert 'add_header X-Content-Type-Options "nosniff" always;' in content
    assert 'add_header Referrer-Policy "no-referrer" always;' in content
