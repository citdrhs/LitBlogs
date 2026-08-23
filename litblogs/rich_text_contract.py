"""Validated, immutable access to the canonical rich-text contract."""

from __future__ import annotations

import json
import re
from pathlib import Path
from types import MappingProxyType
from typing import Any, Mapping

DEFAULT_CONTRACT_PATH = Path(__file__).resolve().with_name("rich_text_contract.json")
MAX_CONTRACT_BYTES = 128 * 1024
ERROR_MESSAGE = "Invalid rich-text contract"

EXPECTED_TEXT_PALETTE = (
    ("Ink", "#111827"),
    ("Slate", "#374151"),
    ("Gray", "#6b7280"),
    ("Red", "#b91c1c"),
    ("Orange", "#c2410c"),
    ("Gold", "#a16207"),
    ("Green", "#15803d"),
    ("Teal", "#0f766e"),
    ("Blue", "#1d4ed8"),
    ("Purple", "#6d28d9"),
    ("Pink", "#be185d"),
    ("White", "#ffffff"),
)
EXPECTED_HIGHLIGHT_PALETTE = (
    ("None", None),
    ("Amber", "#fef3c7"),
    ("Gold", "#fde68a"),
    ("Red", "#fecaca"),
    ("Orange", "#fed7aa"),
    ("Green", "#bbf7d0"),
    ("Blue", "#bfdbfe"),
    ("Purple", "#ddd6fe"),
    ("Pink", "#fbcfe8"),
    ("Gray", "#e5e7eb"),
)
EXPECTED_FONT_FAMILIES = (
    ("Arial", "Arial, Helvetica, sans-serif"),
    ("Courier New", '"Courier New", Courier, monospace'),
    ("Georgia", 'Georgia, "Times New Roman", Times, serif'),
    ("Tahoma", "Tahoma, Arial, Helvetica, sans-serif"),
    ("Times New Roman", '"Times New Roman", Times, serif'),
    ("Trebuchet MS", '"Trebuchet MS", Geneva, sans-serif'),
    ("Verdana", "Verdana, Geneva, sans-serif"),
)
EXPECTED_FONT_SIZES = (
    ("8 pt", "8pt", "10.667px"),
    ("10 pt", "10pt", "13.333px"),
    ("12 pt", "12pt", "16px"),
    ("14 pt", "14pt", "18.667px"),
    ("16 pt", "16pt", "21.333px"),
    ("18 pt", "18pt", "24px"),
    ("24 pt", "24pt", "32px"),
    ("36 pt", "36pt", "48px"),
    ("48 pt", "48pt", "64px"),
)
EXPECTED_TAGS = (
    "a",
    "blockquote",
    "br",
    "code",
    "div",
    "em",
    "figure",
    "h1",
    "h2",
    "h3",
    "h4",
    "h5",
    "h6",
    "hr",
    "img",
    "li",
    "mark",
    "ol",
    "p",
    "pre",
    "s",
    "source",
    "span",
    "strong",
    "table",
    "tbody",
    "td",
    "th",
    "thead",
    "tr",
    "u",
    "ul",
    "video",
)
EXPECTED_GLOBAL_ATTRIBUTES = ("class", "style")
EXPECTED_TAG_ATTRIBUTES = {
    "a": ("href", "rel", "target", "title"),
    "div": ("data-file-name", "data-file-size", "data-file-type", "data-file-url"),
    "img": ("alt", "height", "src", "title", "width"),
    "source": ("src", "type"),
    "td": ("colspan", "rowspan"),
    "th": ("colspan", "rowspan", "scope"),
    "video": ("controls", "height", "preload", "src", "width"),
}
EXPECTED_CLASSES = (
    "aligncenter",
    "alignleft",
    "alignright",
    "custom-font",
    "d-block",
    "file-attachment",
    "file-icon",
    "file-info",
    "file-name",
    "file-size",
    "float-left",
    "float-right",
    "img-fluid",
    "mx-auto",
    "post-image",
    "preserved-heading",
    "video-container",
)
EXPECTED_CLASS_PREFIXES = ("language-",)
EXPECTED_STYLE_PROPERTIES = (
    "background-color",
    "border-radius",
    "color",
    "display",
    "float",
    "font-family",
    "font-size",
    "font-style",
    "font-weight",
    "height",
    "margin",
    "margin-bottom",
    "margin-left",
    "margin-right",
    "margin-top",
    "max-height",
    "max-width",
    "overflow-wrap",
    "text-align",
    "text-decoration",
    "width",
    "word-break",
)
EXPECTED_CSS_KEYWORDS = {
    "display": ("block", "inline", "inline-block", "list-item", "table", "table-cell", "table-row"),
    "float": ("left", "none", "right"),
    "font-style": ("italic", "normal", "oblique"),
    "font-weight": (
        "100",
        "200",
        "300",
        "400",
        "500",
        "600",
        "700",
        "800",
        "900",
        "bold",
        "bolder",
        "lighter",
        "normal",
    ),
    "overflow-wrap": ("anywhere", "break-word", "normal"),
    "text-align": ("center", "end", "justify", "left", "right", "start"),
    "text-decoration": ("line-through", "none", "overline", "underline"),
    "word-break": ("break-all", "break-word", "keep-all", "normal"),
}
EXPECTED_VIDEO_MIME_TYPES = (
    "video/mp4",
    "video/webm",
    "video/ogg",
    "video/x-m4v",
    "video/x-msvideo",
    "video/x-matroska",
)
EXPECTED_PDF_TYPES = ("pdf", "application/pdf")
EXPECTED_IMPORT_TAGS = ("b", "button", "del", "font", "i", "strike")
EXPECTED_IMPORT_TAG_ATTRIBUTES = {
    "button": ("data-file-url", "data-video-url", "type"),
    "div": (
        "align",
        "contenteditable",
        "data-inline-pdf-viewer",
        "data-pdf-title",
        "data-pdf-url",
        "data-video-type",
        "data-video-url",
    ),
    "figure": ("contenteditable",),
    "font": ("color", "face", "size", "data-font-family"),
    "h1": ("data-heading",),
    "h2": ("data-heading",),
    "h3": ("data-heading",),
    "h4": ("data-heading",),
    "h5": ("data-heading",),
    "h6": ("data-heading",),
    "span": ("data-font-family",),
}
EXPECTED_IMPORT_CLASSES = (
    "audio-placeholder",
    "download-btn",
    "editor-only",
    "editor-only-control",
    "embed-placeholder",
    "file-actions",
    "file-placeholder",
    "mceEditable",
    "mceNonEditable",
    "media-placeholder",
    "preview-btn",
    "remove-btn",
    "text-blue-500",
    "video-data",
    "video-delete-btn",
    "video-delete-overlay",
    "video-placeholder",
    "video-wrapper",
)

HEX_COLOR_PATTERN = re.compile(r"#[0-9a-f]{6}")
HTML_NAME_PATTERN = re.compile(r"[a-z][a-z0-9-]*")
CLASS_NAME_PATTERN = re.compile(r"[A-Za-z][A-Za-z0-9_-]*")
CSS_KEYWORD_PATTERN = re.compile(r"[a-z0-9][a-z0-9-]*")
FONT_SIZE_PATTERN = re.compile(r"(?:[1-9][0-9]*)(?:\.[0-9]+)?(?:pt|px)")
MIME_PATTERN = re.compile(r"(?:video|application)/[a-z0-9][a-z0-9.+-]*")


class RichTextContractError(ValueError):
    """Raised when the bundled rich-text contract cannot be admitted."""


class _DuplicateKeyError(ValueError):
    pass


def _fail() -> None:
    raise RichTextContractError(ERROR_MESSAGE)


def _expect_object(value: object, keys: set[str]) -> dict[str, Any]:
    if type(value) is not dict or set(value) != keys:
        _fail()
    return value


def _expect_string(value: object, *, maximum: int = 128) -> str:
    if (
        type(value) is not str
        or not value
        or len(value) > maximum
        or any(ord(character) < 0x20 or ord(character) == 0x7F for character in value)
    ):
        _fail()
    return value


def _expect_string_list(value: object) -> tuple[str, ...]:
    if type(value) is not list:
        _fail()
    strings = tuple(_expect_string(item) for item in value)
    if len(strings) != len(set(strings)):
        _fail()
    return strings


def _expect_exact_string_list(value: object, expected: tuple[str, ...]) -> tuple[str, ...]:
    strings = _expect_string_list(value)
    if strings != expected:
        _fail()
    return strings


def _validate_palette(value: object, expected: tuple[tuple[str, str | None], ...]) -> None:
    if type(value) is not list:
        _fail()
    records = []
    for raw_entry in value:
        entry = _expect_object(raw_entry, {"label", "value"})
        label = _expect_string(entry["label"], maximum=32)
        color = entry["value"]
        if color is not None and (type(color) is not str or HEX_COLOR_PATTERN.fullmatch(color) is None):
            _fail()
        records.append((label, color))
    if len(records) != len(set(records)) or tuple(records) != expected:
        _fail()


def _validate_fonts(value: object) -> None:
    if type(value) is not list:
        _fail()
    records = []
    for raw_entry in value:
        entry = _expect_object(raw_entry, {"label", "cssValue"})
        label = _expect_string(entry["label"], maximum=32)
        css_value = _expect_string(entry["cssValue"])
        if any(fragment in css_value.casefold() for fragment in ("url(", "expression", "@import", ";", "\\")):
            _fail()
        records.append((label, css_value))
    if len(records) != len(set(records)) or tuple(records) != EXPECTED_FONT_FAMILIES:
        _fail()


def _validate_font_sizes(value: object) -> None:
    if type(value) is not list:
        _fail()
    records = []
    for raw_entry in value:
        entry = _expect_object(raw_entry, {"label", "legacyValue", "cssValue"})
        label = _expect_string(entry["label"], maximum=16)
        legacy_value = _expect_string(entry["legacyValue"], maximum=16)
        css_value = _expect_string(entry["cssValue"], maximum=16)
        if FONT_SIZE_PATTERN.fullmatch(legacy_value) is None or FONT_SIZE_PATTERN.fullmatch(css_value) is None:
            _fail()
        records.append((label, legacy_value, css_value))
    if len(records) != len(set(records)) or tuple(records) != EXPECTED_FONT_SIZES:
        _fail()


def _validate_html_name_list(value: object, expected: tuple[str, ...]) -> tuple[str, ...]:
    names = _expect_exact_string_list(value, expected)
    if any(HTML_NAME_PATTERN.fullmatch(name) is None or name.startswith("on") for name in names):
        _fail()
    return names


def _validate_class_list(value: object, expected: tuple[str, ...]) -> tuple[str, ...]:
    names = _expect_exact_string_list(value, expected)
    if any(CLASS_NAME_PATTERN.fullmatch(name) is None for name in names):
        _fail()
    return names


def _validate_html(value: object) -> tuple[tuple[str, ...], set[str], tuple[str, ...]]:
    html = _expect_object(
        value,
        {
            "tags",
            "globalAttributes",
            "tagAttributes",
            "classes",
            "classPrefixes",
            "styleProperties",
            "cssKeywords",
            "videoMimeTypes",
            "pdfTypes",
        },
    )
    tags = _validate_html_name_list(html["tags"], EXPECTED_TAGS)
    global_attributes = _validate_html_name_list(html["globalAttributes"], EXPECTED_GLOBAL_ATTRIBUTES)

    tag_attributes = _expect_object(html["tagAttributes"], set(EXPECTED_TAG_ATTRIBUTES))
    if not set(tag_attributes).issubset(tags):
        _fail()
    canonical_attributes = set(global_attributes)
    for tag, expected_attributes in EXPECTED_TAG_ATTRIBUTES.items():
        attributes = _validate_html_name_list(tag_attributes[tag], expected_attributes)
        canonical_attributes.update(attributes)

    classes = _validate_class_list(html["classes"], EXPECTED_CLASSES)
    class_prefixes = _expect_exact_string_list(html["classPrefixes"], EXPECTED_CLASS_PREFIXES)
    if any(
        not prefix.endswith("-") or CLASS_NAME_PATTERN.fullmatch(prefix[:-1]) is None
        for prefix in class_prefixes
    ):
        _fail()

    style_properties = _validate_html_name_list(html["styleProperties"], EXPECTED_STYLE_PROPERTIES)
    css_keywords = _expect_object(html["cssKeywords"], set(EXPECTED_CSS_KEYWORDS))
    if not set(css_keywords).issubset(style_properties):
        _fail()
    for property_name, expected_values in EXPECTED_CSS_KEYWORDS.items():
        values = _expect_exact_string_list(css_keywords[property_name], expected_values)
        if any(CSS_KEYWORD_PATTERN.fullmatch(item) is None for item in values):
            _fail()

    mime_types = _expect_exact_string_list(html["videoMimeTypes"], EXPECTED_VIDEO_MIME_TYPES)
    if any(MIME_PATTERN.fullmatch(item) is None or not item.startswith("video/") for item in mime_types):
        _fail()
    pdf_types = _expect_exact_string_list(html["pdfTypes"], EXPECTED_PDF_TYPES)
    if any(item != "pdf" and MIME_PATTERN.fullmatch(item) is None for item in pdf_types):
        _fail()

    return tags, canonical_attributes, classes


def _validate_import_only(
    value: object,
    canonical_tags: tuple[str, ...],
    canonical_global_attributes: tuple[str, ...],
    canonical_tag_attributes: dict[str, Any],
    canonical_classes: tuple[str, ...],
) -> None:
    imported = _expect_object(value, {"tags", "tagAttributes", "classes"})
    tags = _validate_html_name_list(imported["tags"], EXPECTED_IMPORT_TAGS)
    classes = _validate_class_list(imported["classes"], EXPECTED_IMPORT_CLASSES)
    tag_attributes = _expect_object(imported["tagAttributes"], set(EXPECTED_IMPORT_TAG_ATTRIBUTES))
    if not set(tag_attributes).issubset(set(canonical_tags) | set(tags)):
        _fail()
    for tag, expected_attributes in EXPECTED_IMPORT_TAG_ATTRIBUTES.items():
        attributes = _validate_html_name_list(tag_attributes[tag], expected_attributes)
        canonical_for_tag = set(canonical_global_attributes)
        canonical_for_tag.update(canonical_tag_attributes.get(tag, ()))
        if not set(attributes).isdisjoint(canonical_for_tag):
            _fail()
    if not set(tags).isdisjoint(canonical_tags) or not set(classes).isdisjoint(canonical_classes):
        _fail()


def _freeze(value: Any) -> Any:
    if type(value) is dict:
        return MappingProxyType({key: _freeze(item) for key, item in value.items()})
    if type(value) is list:
        return tuple(_freeze(item) for item in value)
    return value


def validate_rich_text_contract_data(value: object) -> Mapping[str, Any]:
    """Validate an already-decoded contract object and return an immutable copy."""

    try:
        contract = _expect_object(
            value,
            {"schemaVersion", "palettes", "fontFamilies", "fontSizes", "html", "importOnly"},
        )
        if type(contract["schemaVersion"]) is not int or contract["schemaVersion"] != 1:
            _fail()
        palettes = _expect_object(contract["palettes"], {"text", "highlight"})
        _validate_palette(palettes["text"], EXPECTED_TEXT_PALETTE)
        _validate_palette(palettes["highlight"], EXPECTED_HIGHLIGHT_PALETTE)
        _validate_fonts(contract["fontFamilies"])
        _validate_font_sizes(contract["fontSizes"])
        tags, _attributes, classes = _validate_html(contract["html"])
        html = contract["html"]
        _validate_import_only(
            contract["importOnly"],
            tags,
            tuple(html["globalAttributes"]),
            html["tagAttributes"],
            classes,
        )
        return _freeze(contract)
    except RichTextContractError:
        raise
    except Exception:
        raise RichTextContractError(ERROR_MESSAGE) from None


def _reject_duplicate_keys(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    result = {}
    for key, value in pairs:
        if key in result:
            raise _DuplicateKeyError
        result[key] = value
    return result


def _reject_non_finite_number(_value: str) -> None:
    raise ValueError


def load_rich_text_contract(path: str | Path = DEFAULT_CONTRACT_PATH) -> Mapping[str, Any]:
    """Load and validate a local contract path without consulting the working directory."""

    try:
        raw_bytes = Path(path).read_bytes()
        if not raw_bytes or len(raw_bytes) > MAX_CONTRACT_BYTES:
            _fail()
        raw_contract = json.loads(
            raw_bytes.decode("utf-8"),
            object_pairs_hook=_reject_duplicate_keys,
            parse_constant=_reject_non_finite_number,
        )
    except RichTextContractError:
        raise
    except (OSError, UnicodeError, TypeError, ValueError, json.JSONDecodeError):
        raise RichTextContractError(ERROR_MESSAGE) from None
    return validate_rich_text_contract_data(raw_contract)


def validate_rich_text_contract(path: str | Path = DEFAULT_CONTRACT_PATH) -> Mapping[str, Any]:
    """Admission check used by deployment preflight and other local runtimes."""

    return load_rich_text_contract(path)


RICH_TEXT_CONTRACT = validate_rich_text_contract()
TEXT_COLOR_PALETTE = RICH_TEXT_CONTRACT["palettes"]["text"]
HIGHLIGHT_COLOR_PALETTE = RICH_TEXT_CONTRACT["palettes"]["highlight"]
FONT_FAMILIES = RICH_TEXT_CONTRACT["fontFamilies"]
FONT_SIZES = RICH_TEXT_CONTRACT["fontSizes"]
HTML_CONTRACT = RICH_TEXT_CONTRACT["html"]

__all__ = (
    "DEFAULT_CONTRACT_PATH",
    "FONT_FAMILIES",
    "FONT_SIZES",
    "HIGHLIGHT_COLOR_PALETTE",
    "HTML_CONTRACT",
    "RICH_TEXT_CONTRACT",
    "RichTextContractError",
    "TEXT_COLOR_PALETTE",
    "load_rich_text_contract",
    "validate_rich_text_contract",
    "validate_rich_text_contract_data",
)
