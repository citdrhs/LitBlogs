import asyncio
import hashlib
import inspect
import re
from datetime import timedelta
from html.parser import HTMLParser
from io import BytesIO
from pathlib import Path
from types import SimpleNamespace

import pytest
from fastapi import HTTPException
from starlette.datastructures import Headers
from starlette.routing import Mount

import main
import models
from database import SessionLocal
from rich_text_contract import RICH_TEXT_CONTRACT

PNG_BYTES = b"\x89PNG\r\n\x1a\n" + b"safe-image-payload"
PDF_BYTES = b"%PDF-1.7\n" + b"safe-pdf-payload"
MP4_BYTES = b"\x00\x00\x00\x18ftypisom" + b"safe-video-payload"
PNG_SIZE = len(PNG_BYTES)
PALETTE_RGB_CASES = [
    (
        ", ".join(str(int(entry["value"][offset : offset + 2], 16)) for offset in (1, 3, 5)),
        entry["value"],
    )
    for palette_name in ("text", "highlight")
    for entry in RICH_TEXT_CONTRACT["palettes"][palette_name]
    if entry["value"] is not None
]


class _RichTextProbe(HTMLParser):
    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.elements = []
        self.text = []

    def handle_starttag(self, tag, attrs):
        self.elements.append((tag, dict(attrs)))

    def handle_startendtag(self, tag, attrs):
        self.elements.append((tag, dict(attrs)))

    def handle_data(self, data):
        self.text.append(data)


def _probe_rich_text(value):
    probe = _RichTextProbe()
    probe.feed(value)
    probe.close()
    return probe


def _element(probe, tag, *, class_name=None):
    for candidate_tag, attributes in probe.elements:
        classes = set((attributes.get("class") or "").split())
        if candidate_tag == tag and (class_name is None or class_name in classes):
            return attributes
    return None


def _security_actor(user_id=42, role=models.UserRole.STUDENT):
    return SimpleNamespace(id=user_id, role=role, disabled_at=None)


def _security_user(db, user_id=42, role=models.UserRole.STUDENT):
    user = models.User(
        id=user_id,
        username=f"content-security-{user_id}",
        email=f"content-security-{user_id}@example.com",
        password="not-a-real-password-hash",
        first_name="Content",
        last_name="Security",
        role=role,
    )
    db.add(user)
    db.flush()
    return user


def _registered_asset(
    db,
    *,
    storage_key,
    owner_id=42,
    original_filename="safe.png",
    media_type="image/png",
    size_bytes=PNG_SIZE,
    sha256_digest=None,
    state="PENDING",
    purpose="POST",
):
    now = main._utc_now_naive()
    asset = models.UploadAsset(
        storage_key=storage_key,
        owner_user_id=owner_id,
        purpose=purpose,
        state=state,
        original_filename=original_filename,
        media_type=media_type,
        size_bytes=size_bytes,
        sha256_digest=sha256_digest
        or hashlib.sha256(
            PDF_BYTES if media_type == "application/pdf" else PNG_BYTES
        ).hexdigest(),
        created_at=now,
        expires_at=now + timedelta(hours=24) if state == "PENDING" else None,
        bound_at=now if state == "ACTIVE" else None,
        scan_completed_at=now,
    )
    db.add(asset)
    db.flush()
    return asset


def make_upload(filename, content_type, content):
    return main.UploadFile(
        file=BytesIO(content),
        filename=filename,
        headers=Headers({"content-type": content_type}),
    )


def test_server_sanitizer_removes_active_content_and_unsafe_urls():
    sanitized = main.sanitize_html(
        """
        <style>body { display: none }</style>
        <script>alert(document.domain)</script>
        <a href="javascript:alert(1)" onclick="alert(1)">Open</a>
        <img src="data:text/html,<script>alert(1)</script>" onerror="alert(1)">
        <img src="https://tracker.example/pixel.png">
        <img src="files/42/not-an-upload-route.png">
        <img src="/api/uploads/images/42/private.png?cache=bypass">
        <figure class="video-container">
          <video controls onplay="alert(1)">
            <source src="https://tracker.example/video.mp4" type="video/mp4">
          </video>
        </figure>
        """
    )

    lowered = sanitized.lower()
    assert "<script" not in lowered
    assert "<style" not in lowered
    assert "onclick" not in lowered
    assert "onerror" not in lowered
    assert "onplay" not in lowered
    assert "javascript:" not in lowered
    assert "data:text/html" not in lowered
    assert "https://tracker.example/video.mp4" not in sanitized
    assert "https://tracker.example/pixel.png" not in sanitized
    assert "not-an-upload-route.png" not in sanitized
    assert "cache=bypass" not in sanitized


def test_server_sanitizer_drops_dangerous_subtrees_but_unwraps_harmless_unknown_markup():
    hidden_key = f"objects/a1/{'a1' + ('1' * 30)}.png"
    sanitized = main.sanitize_html(
        f"""
        <iframe><img src="/api/uploads/{hidden_key}">hidden frame text</iframe>
        <form><p>hidden form text</p></form>
        <svg><title>hidden svg text</title></svg>
        <section><strong>kept wrapper text</strong></section>
        """
    )

    assert hidden_key not in sanitized
    assert "hidden frame text" not in sanitized
    assert "hidden form text" not in sanitized
    assert "hidden svg text" not in sanitized
    assert "<section" not in sanitized
    assert "<strong>kept wrapper text</strong>" in sanitized


def test_server_sanitizer_preserves_html5_foster_parented_content():
    sanitized = main.sanitize_html(
        "<table>before<div>inside</div><tr><td>x</td></tr>after</table>"
    )

    assert "before" in sanitized
    assert "<div>inside</div>" in sanitized
    assert "after" in sanitized
    assert "<table><tbody><tr><td>x</td></tr></tbody></table>" in sanitized
    assert sanitized.index("before") < sanitized.index("<div>inside</div>")
    assert sanitized.index("<div>inside</div>") < sanitized.index("after")
    assert sanitized.index("after") < sanitized.index("<table>")


@pytest.mark.parametrize("tag", ["plaintext", "xmp", "textarea", "title"])
def test_server_sanitizer_does_not_leak_synthetic_html_into_unclosed_text_tags(tag):
    assert main.sanitize_html(f"<{tag}>hello") == "hello"


@pytest.mark.parametrize("tag", ["iframe", "script", "style"])
def test_server_sanitizer_drops_unclosed_dangerous_raw_text_subtrees(tag):
    assert main.sanitize_html(f"<{tag}>hidden<p>swallowed") == ""


def test_server_sanitizer_preserves_supported_rich_text_and_uploaded_media():
    sanitized = main.sanitize_html(
        """
        <h2>Reading response</h2>
        <p style="font-family: Georgia, serif; color: #123456; background-color: #fafafa; font-size: 18px; text-align: center; position: fixed">
          <strong>Close reading</strong>
        </p>
        <figure class="video-container" contenteditable="false">
          <video controls preload="metadata" width="100%">
            <source src="/api/uploads/objects/aa/aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa.mp4" type="video/mp4">
          </video>
        </figure>
        <video controls src="/api/uploads/objects/bb/bbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbb.mp4"></video>
        <video controls src="https://tracker.example/direct.mp4"></video>
        <video controls src="data:video/mp4;base64,AAAA"></video>
        <img src="/api/uploads/objects/cc/cccccccccccccccccccccccccccccccc.png" alt="Book cover">
        """
    )

    assert "<h2>Reading response</h2>" in sanitized
    assert "font-family: Georgia, serif" in sanitized
    assert "color: rgb(18, 52, 86)" in sanitized
    assert "background-color: rgb(250, 250, 250)" in sanitized
    assert "font-size: 18px" in sanitized
    assert "text-align: center" in sanitized
    assert "position" not in sanitized
    assert '<figure class="video-container">' in sanitized
    assert "contenteditable" not in sanitized
    assert "<video controls" in sanitized
    assert '<source src="/api/uploads/objects/aa/aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa.mp4" type="video/mp4">' in sanitized
    assert 'src="/api/uploads/objects/bb/bbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbb.mp4"' in sanitized
    assert "https://tracker.example/direct.mp4" not in sanitized
    assert "data:video/mp4" not in sanitized
    assert '<img src="/api/uploads/objects/cc/cccccccccccccccccccccccccccccccc.png" alt="Book cover">' in sanitized


def test_server_sanitizer_canonicalizes_deployment_prefixed_upload_urls():
    object_id = "ab" + ("1" * 30)
    canonical_url = f"/api/uploads/objects/ab/{object_id}.png"

    sanitized = main.sanitize_html(
        f'<img src="/litblogs{canonical_url}" alt="Legacy deployment path">'
    )

    assert canonical_url in sanitized
    assert "/litblogs/api/uploads/" not in sanitized


@pytest.mark.parametrize(
    ("legacy_size", "canonical_size"),
    [
        ("8pt", "10.667px"),
        ("10pt", "13.333px"),
        ("12pt", "16px"),
        ("14pt", "18.667px"),
        ("16pt", "21.333px"),
        ("18pt", "24px"),
        ("24pt", "32px"),
        ("36pt", "48px"),
        ("48pt", "64px"),
    ],
)
def test_server_sanitizer_normalizes_each_contract_point_size(legacy_size, canonical_size):
    sanitized = main.sanitize_html(
        f'<span style="font-size: {legacy_size} !important">Sized</span>'
    )

    assert f"font-size: {canonical_size}" in sanitized
    assert "!important" not in sanitized


@pytest.mark.parametrize(("rgb_channels", "canonical_hex"), PALETTE_RGB_CASES)
def test_server_sanitizer_normalizes_each_palette_rgb_alias(rgb_channels, canonical_hex):
    sanitized = main.sanitize_html(
        f'<span style="color: rgba({rgb_channels}, 1)">Palette</span>'
    )

    assert f"color: {canonical_hex}" in sanitized


@pytest.mark.parametrize(
    ("legacy_color", "canonical_color"),
    [
        ("transparent", "transparent"),
        ("rgb(10%, 20%, 30%)", "rgb(26, 51, 77)"),
        ("#1234", "rgba(17, 34, 51, 0.266667)"),
        ("rgba(1, 2, 3, .3333333)", "rgba(1, 2, 3, 0.333333)"),
        ("hsl(0, 0%, 50%)", "rgb(128, 128, 128)"),
        ("rebeccapurple", "rebeccapurple"),
        ("currentcolor", "currentcolor"),
        ("canvastext", "canvastext"),
        ("buttontext", "buttontext"),
        ("activeborder", "activeborder"),
        ("buttonhighlight", "buttonhighlight"),
        ("threedface", "threedface"),
        ("windowtext", "windowtext"),
        ("rgba(1, 2, 3, 50%)", "rgba(1, 2, 3, 0.5)"),
        ("rgba(1, 2, 3, 33.333333%)", "rgba(1, 2, 3, 0.333333)"),
        ("hsl(120deg, 100%, 50%)", "rgb(0, 255, 0)"),
        ("hsl(0, 50%, 33.333333%)", "rgb(128, 43, 43)"),
        ("hsl(0, -1%, 50%)", "rgb(128, 128, 128)"),
        ("rgb(49.999%, 0%, 12.345678%)", "rgb(127, 0, 31)"),
        ("rgb(0.196078%, 0%, 0%)", "rgb(1, 0, 0)"),
        ("rgba(12.345678%, 50%, 99.9%, 99.999999%)", "rgb(31, 128, 255)"),
    ],
)
def test_server_sanitizer_canonicalizes_safe_legacy_css_colors(
    legacy_color, canonical_color
):
    sanitized = main.sanitize_html(
        f'<span style="color: {legacy_color}">Legacy color</span>'
    )

    assert f"color: {canonical_color}" in sanitized


def test_server_sanitizer_rejects_unsupported_modern_css_color_syntax():
    sanitized = main.sanitize_html(
        '<span style="color: rgb(10% 20% 30% / 50%)">Modern color</span>'
        '<span style="color: hsl(.5turn, 100%, 50%)">Turn color</span>'
        '<span style="color: hsl(2.094395rad, 100%, 50%)">Rad color</span>'
        '<span style="color: hsl(200grad, 100%, 50%)">Grad color</span>'
        '<span style="color: rgb(1e2, 0, 0)">Exponent color</span>'
        '<span style="color: rgb(.5, 1.5, 2.5)">Decimal channel color</span>'
    )

    assert "style=" not in sanitized


def test_server_sanitizer_normalizes_legacy_aliases_fonts_colors_and_structural_content():
    sanitized = main.sanitize_html(
        """
        <h1>One</h1><h2>Two</h2><h3>Three</h3><h4>Four</h4><h5>Five</h5><h6>Six</h6>
        <b>bold</b><i>italic</i><del>deleted</del><strike>struck</strike>
        <font color="rgba(17, 24, 39, 1)" face="Legacy Serif" size="12pt">legacy font</font>
        <p class="aligncenter unsafe mceNonEditable" align="center"
           style="color: RGB(18, 52, 86); background-color: navy; font-family: Legacy Serif, serif; font-size: 9pt">
          paragraph
        </p>
        <ol><li>ordered</li></ol><ul><li>unordered</li></ul>
        <table><thead><tr><th scope="col" colspan="2">Head</th></tr></thead>
          <tbody><tr><td rowspan="2">Cell</td></tr></tbody></table>
        <pre><code class="language-python unsafe">print('safe')</code></pre>
        """
    )
    probe = _probe_rich_text(sanitized)
    tags = [tag for tag, _attributes in probe.elements]
    span_styles = [attrs.get("style", "") for tag, attrs in probe.elements if tag == "span"]
    paragraph = _element(probe, "p")
    code = _element(probe, "code")

    assert all(tag in tags for tag in ("h1", "h2", "h3", "h4", "h5", "h6"))
    assert tags.count("strong") == 1
    assert tags.count("em") == 1
    assert tags.count("s") == 2
    assert not {"b", "i", "del", "strike", "font"}.intersection(tags)
    assert any("color: #111827" in style for style in span_styles)
    assert any("font-family: Legacy Serif" in style for style in span_styles)
    assert any("font-size: 16px" in style for style in span_styles)
    assert paragraph is not None
    assert paragraph.get("class") == "aligncenter"
    assert "align" not in paragraph
    assert "color: rgb(18, 52, 86)" in paragraph.get("style", "")
    assert "background-color: navy" in paragraph.get("style", "")
    assert "font-family: Legacy Serif, serif" in paragraph.get("style", "")
    assert "font-size" not in paragraph.get("style", "")
    assert code == {"class": "language-python"}
    assert _element(probe, "th").get("colspan") == "2"
    assert _element(probe, "td").get("rowspan") == "2"


def test_server_sanitizer_hoists_legacy_metadata_before_removing_control_subtrees():
    parent_key = f"objects/b1/{'b1' + ('1' * 30)}.pdf"
    child_key = f"objects/b2/{'b2' + ('2' * 30)}.pdf"
    video_key = f"objects/c1/{'c1' + ('1' * 30)}.mp4"
    pdf_key = f"objects/d1/{'d1' + ('1' * 30)}.pdf"
    sanitized = main.sanitize_html(
        f"""
        <div class="file-attachment mceNonEditable" data-file-url="/api/uploads/{parent_key}"
             data-file-name="Parent.pdf" data-file-size="10 KB" data-file-type="pdf" contenteditable="false">
          <div class="file-actions"><button class="remove-btn editor-only" data-file-url="/api/uploads/{child_key}" onclick="bad()">Remove parent</button></div>
        </div>
        <div class="file-attachment mceNonEditable" data-file-name="Child.pdf" data-file-type="pdf">
          <button class="remove-btn editor-only" data-file-url="/api/uploads/{child_key}">Remove child</button>
        </div>
        <figure class="video-container mceNonEditable" contenteditable="false">
          <video controls preload="AUTO"><source src="https://bad.example/video.mp4" type="text/html"></video>
          <div class="video-data" data-video-url="/api/uploads/{video_key}" data-video-type="VIDEO/MP4"></div>
          <div class="video-delete-overlay editor-only-control"><button class="video-delete-btn" data-video-url="/api/uploads/{video_key}">Delete video</button></div>
        </figure>
        <div data-inline-pdf-viewer="true" data-pdf-url="/api/uploads/{pdf_key}" data-pdf-title="Reading.pdf"></div>
        """
    )
    probe = _probe_rich_text(sanitized)
    attachments = [
        attrs for tag, attrs in probe.elements
        if tag == "div" and "file-attachment" in set((attrs.get("class") or "").split())
    ]
    source = _element(probe, "source")
    video = _element(probe, "video")

    assert [attrs.get("data-file-url") for attrs in attachments] == [
        f"/api/uploads/{parent_key}",
        f"/api/uploads/{child_key}",
        f"/api/uploads/{pdf_key}",
    ]
    assert attachments[2].get("data-file-name") == "Reading.pdf"
    assert attachments[2].get("data-file-type") == "pdf"
    assert source == {"src": f"/api/uploads/{video_key}", "type": "video/mp4"}
    assert video is not None and video.get("preload") is None and "controls" in video
    assert "button" not in [tag for tag, _attrs in probe.elements]
    assert "Remove parent" not in "".join(probe.text)
    assert "Remove child" not in "".join(probe.text)
    assert "Delete video" not in "".join(probe.text)
    assert not any(
        name.startswith("data-pdf") or name.startswith("data-video") or name == "contenteditable"
        for _tag, attrs in probe.elements
        for name in attrs
    )


def test_server_sanitizer_enforces_per_tag_attributes_links_media_and_table_bounds():
    image_key = f"objects/e1/{'e1' + ('1' * 30)}.png"
    video_key = f"objects/e2/{'e2' + ('2' * 30)}.mp4"
    sanitized = main.sanitize_html(
        f"""
        <span href="https://school.example/wrong" src="/api/uploads/{image_key}" data-file-url="/api/uploads/{image_key}" colspan="2">Scoped</span>
        <a id="external" href="https://school.example/library" target="_blank" rel="opener">External</a>
        <a id="local" href="/classes/42?tab=posts#one" target="_self" rel="opener">Local</a>
        <a id="credential" href="https://user:pass@school.example/private" target="_blank">Credential</a>
        <a id="relative" href="lessons/today">Relative</a>
        <a id="scheme-relative" href="//school.example/private">Scheme relative</a>
        <img src="/api/uploads/{image_key}" width="100%" height="4096px" colspan="3">
        <video src="/api/uploads/{video_key}" preload="metadata" controls></video>
        <video preload="auto"><source src="/api/uploads/{video_key}" type="VIDEO/MP4"></video>
        <source src="/api/uploads/{video_key}" type="video/mp4">
        <table><tbody><tr><td colspan="0" rowspan="101">Bad cell</td><th scope="bad" colspan="2">Head</th></tr></tbody></table>
        """
    )
    probe = _probe_rich_text(sanitized)
    anchors = [attrs for tag, attrs in probe.elements if tag == "a"]
    span = _element(probe, "span")
    image = _element(probe, "img")
    videos = [attrs for tag, attrs in probe.elements if tag == "video"]
    sources = [attrs for tag, attrs in probe.elements if tag == "source"]

    assert span == {}
    assert anchors[0] == {
        "href": "https://school.example/library",
        "target": "_blank",
        "rel": "noopener noreferrer",
    }
    assert anchors[1] == {"href": "/classes/42?tab=posts#one"}
    assert anchors[2] == {}
    assert anchors[3] == {"href": "lessons/today"}
    assert anchors[4] == {}
    assert image == {"src": f"/api/uploads/{image_key}", "width": "100%", "height": "4096px"}
    assert videos[0].get("preload") == "metadata"
    assert videos[1].get("preload") is None
    assert sources == [{"src": f"/api/uploads/{video_key}", "type": "video/mp4"}]
    assert _element(probe, "td") == {}
    assert _element(probe, "th") == {"colspan": "2"}


def test_server_sanitizer_normalizes_source_videos_to_one_editor_stable_asset():
    first_key = f"objects/f2/{'f2' + ('2' * 30)}.mp4"
    second_key = f"objects/f3/{'f3' + ('3' * 30)}.webm"
    once = main.sanitize_html(
        f"""
        <video controls><source src="/api/uploads/{first_key}"></video>
        <video controls>
          <source src="/api/uploads/{first_key}" type="text/html">
          <source src="/api/uploads/{second_key}" type="video/webm">
          <source src="/api/uploads/{first_key}" type="video/mp4">
        </video>
        """
    )
    probe = _probe_rich_text(once)
    videos = [attrs for tag, attrs in probe.elements if tag == "video"]
    sources = [attrs for tag, attrs in probe.elements if tag == "source"]

    assert videos[0].get("src") == f"/api/uploads/{first_key}"
    assert "src" not in videos[1]
    assert sources == [
        {"src": f"/api/uploads/{second_key}", "type": "video/webm"}
    ]
    assert main.sanitize_html(once) == once


def test_server_sanitizer_is_idempotent_and_recovers_only_bounded_escaped_media_outside_code():
    video_key = f"objects/f1/{'f1' + ('1' * 30)}.mp4"
    raw = (
        "<pre><code>&lt;video src=&quot;/api/uploads/"
        f"{video_key}&quot;&gt;&lt;/video&gt;</code></pre>"
        "&lt;figure class=&quot;video-container&quot;&gt;&lt;video controls&gt;"
        f"&lt;source src=&quot;/api/uploads/{video_key}&quot; type=&quot;video/mp4&quot;&gt;"
        "&lt;/video&gt;&lt;/figure&gt;"
    )

    once = main.sanitize_html(raw)
    twice = main.sanitize_html(once)
    probe = _probe_rich_text(once)

    assert once == twice
    assert len([tag for tag, _attrs in probe.elements if tag == "video"]) == 1
    assert "<video src=" in "".join(probe.text)


@pytest.mark.parametrize("zero", ["0", "-0"])
def test_server_sanitizer_rejects_unitless_zero_font_size_idempotently(zero):
    once = main.sanitize_html(
        f'<span style="font-size:{zero}">Text</span>'
        f'<p style="margin:{zero};width:{zero}">Box</p>'
    )

    assert "<span>Text</span>" in once
    assert '<p style="margin: 0px; width: 0px;">Box</p>' in once
    assert "font-size" not in once
    assert main.sanitize_html(once) == once


def test_server_sanitizer_normalizes_css_comments_idempotently():
    once = main.sanitize_html(
        '<span style="color:r/**/ed;font-size:1/**/8px">Commented style</span>'
    )

    assert 'style="color: red; font-size: 18px;"' in once
    assert main.sanitize_html(once) == once


def test_server_sanitizer_reparses_unwrapped_content_model_nodes_idempotently():
    once = main.sanitize_html("<li><section><li>x</li></section>")

    assert once == "<li></li><li>x</li>"
    assert main.sanitize_html(once) == once


def test_server_sanitizer_recovers_foster_parented_escaped_video_immediately():
    video_url = f"/api/uploads/objects/aa/{'a' * 32}.mp4"
    once = main.sanitize_html(
        f'<table>&lt;video src=&quot;{video_url}&quot;&gt;</table>'
    )

    assert f'<video src="{video_url}"></video>' in once
    assert "&lt;video" not in once
    assert main.sanitize_html(once) == once


def test_server_sanitizer_removes_foster_parented_escaped_orphan_source():
    video_url = f"/api/uploads/objects/aa/{'a' * 32}.mp4"
    once = main.sanitize_html(
        f'<table>&lt;source src=&quot;{video_url}&quot; type=&quot;video/mp4&quot;&gt;</table>'
    )

    assert "source" not in once
    assert video_url not in once
    assert main.sanitize_html(once) == once


def test_server_sanitizer_drops_pathological_layout_values():
    sanitized = main.sanitize_html(
        """
        <p style="font-size: 999999999px; width: 999999999px; height: 999999999px; margin: 999999999px; max-width: 999999999px">Oversized</p>
        <p style="font-size: 18px; width: 100%; max-width: 600px; margin: 12px 0">Bounded</p>
        <img src="/api/uploads/images/42/unsafe.png" width="999999999px" height="999999999px">
        <img src="/api/uploads/images/42/safe.png" width="100%" height="4096px">
        """
    )

    assert "999999999" not in sanitized
    assert "font-size: 18px" in sanitized
    assert "width: 100%" in sanitized
    assert "max-width: 600px" in sanitized
    assert "margin: 12px 0" in sanitized
    assert 'width="100%"' in sanitized
    assert 'height="4096px"' in sanitized


def test_server_sanitizer_rejects_malformed_urls_without_raising():
    sanitized = main.sanitize_html(
        '<a href="https://[">Broken link</a><img src="//[">'
        '<a href="/safe/%FF">Invalid UTF-8</a>'
        '<a href="/%C0%AE%C0%AE/admin">Overlong path</a>'
        '<a href="https:///evil.example/path">Ambiguous authority</a>'
        '<a href="https:////evil.example/path">Ambiguous authority two</a>'
    )

    assert "href=" not in sanitized
    assert "src=" not in sanitized
    assert "%FF" not in sanitized
    assert "%C0%AE" not in sanitized


def test_server_sanitizer_rejects_oversized_content_before_parsing(monkeypatch):
    monkeypatch.setattr(main, "MAX_RICH_TEXT_INPUT_LENGTH", 16)

    with pytest.raises(HTTPException) as error:
        main.sanitize_html("x" * 17)

    assert error.value.status_code == 413
    assert error.value.detail == "Rich text exceeds the allowed size"


def test_post_builder_does_not_append_active_markup_after_sanitization():
    post = main.schemas.BlogCreate(
        title="Security regression",
        content="<p>Visible response</p>",
        code_snippets=[
            {"language": "html", "code": '<img src=x onerror="window.__xss=true">'},
        ],
        media=[{"type": "image", "url": '"><script>window.__xss=true</script>'}],
        polls=[{"options": ["safe", "</div><script>alert(1)</script>"]}],
        files=[{"name": "</div><img src=x onerror=alert(1)>", "url": "/api/uploads/objects/dd/dddddddddddddddddddddddddddddddd.pdf"}],
    )

    built = main._build_post_content(post)

    assert "<script" not in built.lower()
    assert "<img src=x" not in built.lower()
    assert "&lt;img" in built


def test_compatibility_upload_reference_parser_is_removed():
    assert not hasattr(main, "_canonical_upload_relative_path")


def test_upload_path_cannot_escape_upload_root(monkeypatch, tmp_path):
    monkeypatch.setattr(main, "UPLOAD_DIR", tmp_path)

    assert main._upload_path("objects", "aa", "aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa.pdf") == (
        tmp_path / "objects" / "aa" / "aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa.pdf"
    ).resolve()

    with pytest.raises(ValueError, match="upload"):
        main._upload_path("..", "secrets.env")


def test_legacy_and_unmapped_uploads_are_never_served(client, monkeypatch, tmp_path):
    monkeypatch.setattr(main, "UPLOAD_DIR", tmp_path)
    other_users_file = tmp_path / "files" / "99" / "private.pdf"
    other_users_file.parent.mkdir(parents=True)
    other_users_file.write_bytes(b"private")

    with pytest.raises(HTTPException) as legacy_error:
        asyncio.run(main.get_uploaded_file("files/42/private.pdf"))
    assert legacy_error.value.status_code == 400
    assert legacy_error.value.detail == "Invalid upload path"

    rogue_key = "objects/aa/aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa.pdf"
    rogue_path = tmp_path / rogue_key
    rogue_path.parent.mkdir(parents=True)
    rogue_path.write_bytes(PDF_BYTES)
    with SessionLocal() as db:
        _security_user(db)
        db.commit()
        with pytest.raises(HTTPException) as unmapped_error:
            asyncio.run(
                main.get_uploaded_file(
                    rogue_key,
                    db=db,
                    current_user=_security_actor(),
                )
            )
    assert unmapped_error.value.status_code == 404
    assert unmapped_error.value.detail == "File not found"


@pytest.mark.parametrize(
    ("filename", "content_type", "content"),
    [
        ("active.svg", "image/svg+xml", b"<svg onload='alert(1)'></svg>"),
        ("active.html", "text/html", b"<script>alert(1)</script>"),
        ("forged.png", "image/png", b"<script>alert(1)</script>"),
        ("mismatch.jpg", "image/png", PNG_BYTES),
    ],
)
def test_image_upload_rejects_active_or_mismatched_content(
    client,
    monkeypatch,
    tmp_path,
    filename,
    content_type,
    content,
):
    monkeypatch.setattr(main, "UPLOAD_DIR", tmp_path)
    with SessionLocal() as db:
        _security_user(db)
        db.commit()
        with pytest.raises(HTTPException) as error:
            asyncio.run(
                main.upload_image(
                    make_upload(filename, content_type, content),
                    db=db,
                    current_user=_security_actor(),
                )
            )

    assert error.value.status_code == 400
    assert [path for path in tmp_path.rglob("*") if path.is_file()] == []


def test_validated_upload_is_bounded_opaque_and_cleans_partial_files(client, monkeypatch, tmp_path):
    monkeypatch.setattr(main, "UPLOAD_DIR", tmp_path)
    monkeypatch.setattr(main, "MAX_IMAGE_UPLOAD_BYTES", len(PNG_BYTES) - 1)

    with SessionLocal() as db:
        _security_user(db)
        db.commit()
        with pytest.raises(HTTPException) as error:
            asyncio.run(
                main.upload_image(
                    make_upload("student-private-name.png", "image/png", PNG_BYTES),
                    db=db,
                    current_user=_security_actor(),
                )
            )
        assert error.value.status_code == 413
        assert [path for path in tmp_path.rglob("*") if path.is_file()] == []

        monkeypatch.setattr(main, "MAX_IMAGE_UPLOAD_BYTES", len(PNG_BYTES))
        result = asyncio.run(
            main.upload_image(
                make_upload("student-private-name.png", "image/png", PNG_BYTES),
                db=db,
                current_user=_security_actor(),
            )
        )
        storage_key = result["url"].removeprefix("/api/uploads/")
        assert re.fullmatch(r"objects/[0-9a-f]{2}/[0-9a-f]{32}\.png", storage_key)
        assert storage_key.split("/")[1] == Path(storage_key).stem[:2]
        assert "student-private-name" not in storage_key
        assert (tmp_path / storage_key).read_bytes() == PNG_BYTES
        assert db.query(models.UploadAsset).one().state == "PENDING"


@pytest.mark.parametrize(
    "endpoint",
    [main.upload_profile_image, main.upload_cover_image],
)
def test_profile_upload_database_failures_clean_files_without_disclosing_paths(
    endpoint,
    monkeypatch,
    tmp_path,
):
    class FailingDatabase:
        def query(self, *_args, **_kwargs):
            raise RuntimeError(str(tmp_path / "private" / "database.sqlite"))

        def rollback(self):
            return None

    monkeypatch.setattr(main, "UPLOAD_DIR", tmp_path)

    with pytest.raises(HTTPException) as error:
        asyncio.run(
            endpoint(
                make_upload("portrait.png", "image/png", PNG_BYTES),
                db=FailingDatabase(),
                current_user=SimpleNamespace(id=42),
            )
        )

    assert error.value.status_code == 500
    assert error.value.detail == "Failed to upload image"
    assert not any(path.is_file() for path in tmp_path.rglob("*"))


def test_upload_round_trip_uses_the_canonical_authenticated_api_route(
    client,
    monkeypatch,
    tmp_path,
):
    monkeypatch.setattr(main, "UPLOAD_DIR", tmp_path)
    with SessionLocal() as db:
        _security_user(db)
        db.commit()
    main.app.dependency_overrides[main.get_current_user] = lambda: _security_actor()
    try:
        upload_response = client.post(
            "/api/upload/image",
            files={"file": ("cover.png", PNG_BYTES, "image/png")},
        )
        assert upload_response.status_code == 200

        upload_url = upload_response.json()["url"]
        assert re.fullmatch(
            r"/api/uploads/objects/[0-9a-f]{2}/[0-9a-f]{32}\.png",
            upload_url,
        )

        served_response = client.get(upload_url)
        assert served_response.status_code == 200
        assert served_response.content == PNG_BYTES
        assert served_response.headers["content-type"] == "image/png"

        upload_path = upload_url.removeprefix("/api/uploads/")
        delete_response = client.delete(f"/api/upload/{upload_path}")
        assert delete_response.status_code == 200
        assert delete_response.json() == {"message": "File deletion queued"}
        assert (tmp_path / upload_path).is_file()
        with SessionLocal() as db:
            assert db.query(models.UploadAsset).one().state == "DELETE_PENDING"
    finally:
        main.app.dependency_overrides.pop(main.get_current_user, None)


@pytest.mark.parametrize(
    ("filename", "content_type", "content", "kind"),
    [
        ("reading.pdf", "application/pdf", PDF_BYTES, "pdf"),
        ("book-talk.mp4", "video/mp4", MP4_BYTES, "video"),
        ("cover.png", "image/png", PNG_BYTES, "image"),
    ],
)
def test_upload_type_classifier_requires_extension_mime_and_signature_agreement(
    filename,
    content_type,
    content,
    kind,
):
    upload = make_upload(filename, content_type, content)
    spec = main._validated_upload_spec(upload, {kind}, content[:32])

    assert spec.kind == kind


def test_all_upload_endpoints_use_the_bounded_validation_writer():
    for endpoint in (
        main.upload_image,
        main.upload_video,
        main.upload_file,
        main.upload_generic_file,
    ):
        assert "_register_pending_upload" in inspect.getsource(endpoint)
    assert "_save_validated_upload" in inspect.getsource(main._register_pending_upload)
    for endpoint in (main.upload_profile_image, main.upload_cover_image):
        assert "_replace_profile_upload" in inspect.getsource(endpoint)
    assert "_save_validated_upload" in inspect.getsource(main._replace_profile_upload)


def test_uploads_are_not_exposed_through_the_public_static_mount():
    assert not any(
        isinstance(route, Mount) and route.path == "/uploads"
        for route in main.app.routes
    )


def test_upload_route_requires_authentication_before_revealing_file(client, monkeypatch, tmp_path):
    monkeypatch.setattr(main, "UPLOAD_DIR", tmp_path)
    storage_key = "objects/aa/aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa.png"
    image_path = tmp_path / storage_key
    image_path.parent.mkdir(parents=True)
    image_path.write_bytes(PNG_BYTES)
    with SessionLocal() as db:
        _security_user(db)
        _registered_asset(db, storage_key=storage_key)
        db.commit()

    upload_url = f"/api/uploads/{storage_key}"
    unauthenticated = client.get(upload_url)
    assert unauthenticated.status_code == 401

    main.app.dependency_overrides[main.get_current_user] = lambda: _security_actor()
    try:
        authenticated = client.get(upload_url)
        main.app.dependency_overrides[main.get_current_user] = lambda: _security_actor(
            99,
            models.UserRole.ADMIN,
        )
        admin_read = client.get(upload_url)
    finally:
        main.app.dependency_overrides.pop(main.get_current_user, None)

    assert authenticated.status_code == 200
    assert authenticated.content == PNG_BYTES
    assert admin_read.status_code == 200
    assert admin_read.content == PNG_BYTES


def test_upload_request_body_cap_runs_before_auth_and_multipart_parsing(client, monkeypatch):
    monkeypatch.setattr(main, "MAX_IMAGE_UPLOAD_BYTES", 16)

    response = client.post(
        "/api/upload/image",
        files={"file": ("oversized.png", b"x" * (2 * 1024 * 1024), "image/png")},
    )

    assert response.status_code == 413
    assert response.json() == {"detail": "Upload request exceeds the allowed size"}


def test_upload_request_body_cap_counts_chunked_bodies_without_content_length(monkeypatch):
    monkeypatch.setattr(main, "MAX_IMAGE_UPLOAD_BYTES", 5)
    monkeypatch.setattr(main, "UPLOAD_REQUEST_OVERHEAD_BYTES", 0)
    request_messages = iter(
        [
            {"type": "http.request", "body": b"123", "more_body": True},
            {"type": "http.request", "body": b"456", "more_body": False},
        ]
    )
    sent_messages = []
    downstream_completed = False

    async def receive():
        return next(request_messages)

    async def send(message):
        sent_messages.append(message)

    async def downstream(_scope, limited_receive, _send):
        nonlocal downstream_completed
        await limited_receive()
        await limited_receive()
        downstream_completed = True

    middleware = main.UploadRequestBodyLimitMiddleware(downstream)
    scope = {
        "type": "http",
        "method": "POST",
        "path": "/api/upload/image",
        "headers": [],
    }

    asyncio.run(middleware(scope, receive, send))

    response_start = next(
        message for message in sent_messages if message["type"] == "http.response.start"
    )
    assert response_start["status"] == 413
    assert downstream_completed is False


def test_safe_upload_response_has_fixed_type_and_defensive_headers(client, monkeypatch, tmp_path):
    monkeypatch.setattr(main, "UPLOAD_DIR", tmp_path)
    storage_key = "objects/aa/aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa.png"
    image_path = tmp_path / storage_key
    image_path.parent.mkdir(parents=True)
    image_path.write_bytes(PNG_BYTES)

    with SessionLocal() as db:
        _security_user(db)
        _registered_asset(db, storage_key=storage_key)
        db.commit()
        response = asyncio.run(
            main.get_uploaded_file(
                storage_key,
                db=db,
                current_user=_security_actor(),
            )
        )

    assert response.media_type == "image/png"
    assert response.headers["x-content-type-options"] == "nosniff"
    assert response.headers["cross-origin-resource-policy"] == "same-origin"
    assert response.headers["cache-control"] == "private, no-store"
    assert "sandbox" in response.headers["content-security-policy"]
    assert response.headers["content-disposition"].startswith("inline;")


def test_pdf_uploads_are_always_served_as_attachments(client, monkeypatch, tmp_path):
    monkeypatch.setattr(main, "UPLOAD_DIR", tmp_path)
    storage_key = "objects/bb/bbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbb.pdf"
    document_path = tmp_path / storage_key
    document_path.parent.mkdir(parents=True)
    document_path.write_bytes(PDF_BYTES)

    with SessionLocal() as db:
        _security_user(db)
        _registered_asset(
            db,
            storage_key=storage_key,
            original_filename="safe.pdf",
            media_type="application/pdf",
            size_bytes=len(PDF_BYTES),
        )
        db.commit()
        response = asyncio.run(
            main.get_uploaded_file(
                storage_key,
                db=db,
                current_user=_security_actor(),
            )
        )

    assert response.media_type == "application/pdf"
    assert response.headers["content-disposition"].startswith("attachment;")


def test_registry_response_uses_stored_name_and_sanitizes_it(client, monkeypatch, tmp_path):
    monkeypatch.setattr(main, "UPLOAD_DIR", tmp_path)
    storage_key = "objects/bb/bbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbb.pdf"
    document_path = tmp_path / storage_key
    document_path.parent.mkdir(parents=True)
    document_path.write_bytes(PDF_BYTES)

    with SessionLocal() as db:
        _security_user(db)
        _registered_asset(
            db,
            storage_key=storage_key,
            original_filename='report.html"\r\nX-Injected: true',
            media_type="application/pdf",
            size_bytes=len(PDF_BYTES),
        )
        db.commit()
        response = asyncio.run(
            main.get_uploaded_file(
                storage_key,
                db=db,
                current_user=_security_actor(),
            )
        )

    disposition = response.headers["content-disposition"]
    assert response.media_type == "application/pdf"
    assert disposition.startswith("attachment;")
    assert ".html" not in disposition
    assert disposition.endswith('report.pdf"')
    assert "\r" not in disposition and "\n" not in disposition
    assert response.headers["x-content-type-options"] == "nosniff"


def test_upload_and_delete_errors_do_not_disclose_server_paths(
    client,
    monkeypatch,
    tmp_path,
    capsys,
):
    monkeypatch.setattr(main, "UPLOAD_DIR", tmp_path)
    missing_key = "objects/bb/bbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbb.pdf"
    with SessionLocal() as db:
        _security_user(db)
        db.commit()
        with pytest.raises(HTTPException) as upload_error:
            asyncio.run(
                main.get_uploaded_file(
                    missing_key,
                    db=db,
                    current_user=_security_actor(),
                )
            )
    assert upload_error.value.status_code == 404
    assert upload_error.value.detail == "File not found"

    class FailingDatabase:
        def query(self, *_args, **_kwargs):
            raise RuntimeError(str(tmp_path / "private" / "student-record.pdf"))

        def rollback(self):
            return None

    with pytest.raises(HTTPException) as delete_error:
        asyncio.run(
            main.delete_file(
                missing_key,
                db=FailingDatabase(),
                current_user=_security_actor(),
            )
        )
    assert delete_error.value.status_code == 500
    assert delete_error.value.detail == "Failed to delete file"
    assert capsys.readouterr().out == ""


def test_unmapped_or_forged_uploads_are_not_served(client, monkeypatch, tmp_path):
    monkeypatch.setattr(main, "UPLOAD_DIR", tmp_path)
    unmapped_key = "objects/aa/aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa.png"
    forged_key = "objects/bb/bbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbb.png"
    unmapped_png = tmp_path / unmapped_key
    forged_png = tmp_path / forged_key
    unmapped_png.parent.mkdir(parents=True)
    unmapped_png.write_bytes(PNG_BYTES)
    forged_png.parent.mkdir(parents=True)
    forged_payload = b"<script>alert(1)</script>"
    forged_png.write_bytes(forged_payload)

    with SessionLocal() as db:
        _security_user(db)
        _registered_asset(
            db,
            storage_key=forged_key,
            size_bytes=len(forged_payload),
            sha256_digest=hashlib.sha256(forged_payload).hexdigest(),
        )
        db.commit()
        for reference in (unmapped_key, forged_key):
            with pytest.raises(HTTPException) as error:
                asyncio.run(
                    main.get_uploaded_file(
                        reference,
                        db=db,
                        current_user=_security_actor(),
                    )
                )
            assert error.value.status_code == 404
            assert error.value.detail == "File not found"


def test_delete_upload_maps_malformed_paths_to_bad_request(client):
    with SessionLocal() as db:
        _security_user(db)
        db.commit()
        with pytest.raises(HTTPException) as error:
            asyncio.run(
                main.delete_file(
                    file_path="../secrets.env",
                    db=db,
                    current_user=_security_actor(),
                )
            )

    assert error.value.status_code == 400
    assert error.value.detail == "Invalid upload path"


def test_delete_upload_hides_another_owners_registered_object(client):
    storage_key = "objects/aa/aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa.pdf"
    with SessionLocal() as db:
        _security_user(db, 42)
        _security_user(db, 420)
        _registered_asset(
            db,
            storage_key=storage_key,
            owner_id=420,
            original_filename="reading.pdf",
            media_type="application/pdf",
            size_bytes=len(PDF_BYTES),
        )
        db.commit()
        with pytest.raises(HTTPException) as error:
            asyncio.run(
                main.delete_file(
                    file_path=storage_key,
                    db=db,
                    current_user=_security_actor(42),
                )
            )

    assert error.value.status_code == 404
    assert error.value.detail == "File not found"


def test_delete_upload_rejects_direct_active_asset(client):
    storage_key = "objects/aa/aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa.png"
    with SessionLocal() as db:
        _security_user(db)
        _registered_asset(
            db,
            storage_key=storage_key,
            state="ACTIVE",
            purpose="PROFILE_IMAGE",
        )
        db.commit()
        with pytest.raises(HTTPException) as error:
            asyncio.run(
                main.delete_file(
                    file_path=storage_key,
                    db=db,
                    current_user=_security_actor(),
                )
            )

    assert error.value.status_code == 409
    assert error.value.detail == "Active uploads must be removed from their resource"


def test_delete_upload_rejects_directories_without_disclosing_paths(
    client,
    monkeypatch,
    tmp_path,
    capsys,
):
    monkeypatch.setattr(main, "UPLOAD_DIR", tmp_path)
    (tmp_path / "objects" / "aa").mkdir(parents=True)

    with SessionLocal() as db:
        _security_user(db)
        db.commit()
        with pytest.raises(HTTPException) as error:
            asyncio.run(
                main.delete_file(
                    file_path="objects/aa",
                    db=db,
                    current_user=_security_actor(),
                )
            )

    assert error.value.status_code == 400
    assert error.value.detail == "Invalid upload path"
    assert capsys.readouterr().out == ""


def test_pending_delete_queues_without_synchronously_unlinking(
    client,
    monkeypatch,
    tmp_path,
    capsys,
):
    monkeypatch.setattr(main, "UPLOAD_DIR", tmp_path)
    storage_key = "objects/aa/aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa.png"
    stored_file = tmp_path / storage_key
    stored_file.parent.mkdir(parents=True)
    stored_file.write_bytes(PNG_BYTES)
    with SessionLocal() as db:
        _security_user(db)
        _registered_asset(db, storage_key=storage_key)
        db.commit()

    def fail_unlink(_path):
        raise OSError(str(tmp_path / "private" / "student-record.png"))

    monkeypatch.setattr(Path, "unlink", fail_unlink)

    with SessionLocal() as db:
        result = asyncio.run(
            main.delete_file(
                file_path=storage_key,
                db=db,
                current_user=_security_actor(),
            )
        )

    assert result == {"message": "File deletion queued"}
    assert stored_file.is_file()
    with SessionLocal() as db:
        asset = db.query(models.UploadAsset).one()
        assert asset.state == "DELETE_PENDING"
        assert asset.delete_after is not None
    assert capsys.readouterr().out == ""
