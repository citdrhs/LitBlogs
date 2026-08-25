"""Canonical rich-text import normalization and backend sanitization."""

from __future__ import annotations

import html
import re
from collections import OrderedDict
from urllib.parse import unquote, urlsplit
from xml.etree.ElementTree import Element

import bleach
import tinycss2
from bleach import html5lib_shim
from bleach.css_sanitizer import CSSSanitizer
from tinycss2.color3 import parse_color

from rich_text_contract import FONT_SIZES, HTML_CONTRACT, RICH_TEXT_CONTRACT
from upload_assets import canonical_object_key, object_url

MAX_LEGACY_MEDIA_RECOVERIES = 256
MAX_URL_LENGTH = 2048
MAX_CSS_VALUE_LENGTH = 128

CANONICAL_TAGS = tuple(HTML_CONTRACT["tags"])
CANONICAL_TAG_SET = frozenset(CANONICAL_TAGS)
GLOBAL_ATTRIBUTES = frozenset(HTML_CONTRACT["globalAttributes"])
TAG_ATTRIBUTES = {
    tag: frozenset(attributes) for tag, attributes in HTML_CONTRACT["tagAttributes"].items()
}
CANONICAL_CLASSES = frozenset(HTML_CONTRACT["classes"])
CLASS_PREFIXES = tuple(HTML_CONTRACT["classPrefixes"])
STYLE_PROPERTIES = frozenset(HTML_CONTRACT["styleProperties"])
CSS_KEYWORDS = {
    property_name: frozenset(values)
    for property_name, values in HTML_CONTRACT["cssKeywords"].items()
}
VIDEO_MIME_TYPES = frozenset(HTML_CONTRACT["videoMimeTypes"])
PDF_TYPES = frozenset(HTML_CONTRACT["pdfTypes"])
IMPORT_ONLY = RICH_TEXT_CONTRACT["importOnly"]
IMPORT_TAGS = frozenset(IMPORT_ONLY["tags"])
IMPORT_CLASSES = frozenset(IMPORT_ONLY["classes"])
POINT_TO_PIXEL = {entry["legacyValue"]: entry["cssValue"] for entry in FONT_SIZES}
CANONICAL_PIXEL_SIZES = frozenset(entry["cssValue"] for entry in FONT_SIZES)
HTML_FONT_SIZE_TO_PIXEL = {
    "1": "10.667px",
    "2": "13.333px",
    "3": "16px",
    "4": "18.667px",
    "5": "24px",
    "6": "32px",
    "7": "48px",
}
SYSTEM_COLOR_KEYWORDS = frozenset(
    {
        "accentcolor",
        "accentcolortext",
        "activeborder",
        "activecaption",
        "activetext",
        "appworkspace",
        "background",
        "buttonborder",
        "buttonface",
        "buttonhighlight",
        "buttonshadow",
        "buttontext",
        "canvas",
        "canvastext",
        "captiontext",
        "field",
        "fieldtext",
        "graytext",
        "highlight",
        "highlighttext",
        "inactiveborder",
        "inactivecaption",
        "inactivecaptiontext",
        "infobackground",
        "infotext",
        "linktext",
        "mark",
        "marktext",
        "menu",
        "menutext",
        "scrollbar",
        "selecteditem",
        "selecteditemtext",
        "threeddarkshadow",
        "threedface",
        "threedhighlight",
        "threedlightshadow",
        "threedshadow",
        "visitedtext",
        "window",
        "windowframe",
        "windowtext",
    }
)

DANGEROUS_SUBTREE_TAGS = frozenset(
    {
        "base",
        "embed",
        "form",
        "head",
        "iframe",
        "link",
        "math",
        "meta",
        "noscript",
        "object",
        "script",
        "style",
        "svg",
        "template",
    }
)
CONTROL_SUBTREE_CLASSES = frozenset(
    {
        "audio-placeholder",
        "download-btn",
        "editor-only",
        "editor-only-control",
        "embed-placeholder",
        "file-actions",
        "file-placeholder",
        "media-placeholder",
        "preview-btn",
        "remove-btn",
        "video-data",
        "video-delete-btn",
        "video-delete-overlay",
        "video-placeholder",
    }.intersection(IMPORT_CLASSES)
)
ALIAS_TAGS = {
    tag: canonical
    for tag, canonical in {"b": "strong", "i": "em", "del": "s", "strike": "s"}.items()
    if tag in IMPORT_TAGS
}
LEGACY_MEDIA_TAGS = frozenset({"figure", "source", "video"})

CLASS_SUFFIX_PATTERN = re.compile(r"[A-Za-z0-9_-]{1,64}")
PERCENT_ESCAPE_PATTERN = re.compile(r"%(?![0-9A-Fa-f]{2})")
OBJECT_URL_PATTERN = re.compile(
    r"^(?:/[^/?#]+)*/api/uploads/objects/([0-9a-f]{2})/([0-9a-f]{32})(\.[a-z0-9]{1,10})$"
)
LENGTH_PATTERN = re.compile(r"^(-?(?:\d+(?:\.\d+)?|\.\d+))(px|%|em|rem)?$", re.IGNORECASE)
FONT_FAMILY_ITEM_PATTERN = re.compile(
    r'''^(?:"[^"\\\r\n]+"|'[^'\\\r\n]+'|[A-Za-z][A-Za-z0-9 _-]*)$'''
)
CSS_NUMBER_SOURCE = r"[+-]?(?:\d+(?:\.\d+)?|\.\d+)"
RGB_CHANNEL_SOURCE = rf"(?:[+-]?\d+|{CSS_NUMBER_SOURCE}%)"
ALPHA_SOURCE = rf"{CSS_NUMBER_SOURCE}%?"
HUE_SOURCE = rf"{CSS_NUMBER_SOURCE}(?:deg)?"
PERCENT_SOURCE = rf"{CSS_NUMBER_SOURCE}%"
RGB_COLOR_PATTERN = re.compile(
    rf"^(rgb|rgba)\(\s*({RGB_CHANNEL_SOURCE})\s*,\s*({RGB_CHANNEL_SOURCE})\s*,\s*"
    rf"({RGB_CHANNEL_SOURCE})(?:\s*,\s*({ALPHA_SOURCE}))?\s*\)$",
    re.IGNORECASE,
)
HSL_COLOR_PATTERN = re.compile(
    rf"^(hsl|hsla)\(\s*({HUE_SOURCE})\s*,\s*({PERCENT_SOURCE})\s*,\s*"
    rf"({PERCENT_SOURCE})(?:\s*,\s*({ALPHA_SOURCE}))?\s*\)$",
    re.IGNORECASE,
)


def _palette_channels() -> dict[tuple[int, int, int], str]:
    aliases = {}
    for palette_name in ("text", "highlight"):
        for entry in RICH_TEXT_CONTRACT["palettes"][palette_name]:
            value = entry["value"]
            if value is None:
                continue
            aliases[tuple(int(value[offset : offset + 2], 16) for offset in (1, 3, 5))] = value
    return aliases


PALETTE_CHANNELS = _palette_channels()


def _tag_name(element) -> str:
    tag = element.tag
    if not isinstance(tag, str):
        return ""
    if tag.startswith("{"):
        return tag.rsplit("}", 1)[-1].lower()
    return tag.lower()


def _has_foreign_namespace(element) -> bool:
    return isinstance(element.tag, str) and element.tag.startswith("{")


def _class_names(element) -> list[str]:
    return (element.attrib.get("class") or "").split()


def _append_before_child(parent, index: int, value: str | None) -> None:
    if not value:
        return
    if index == 0:
        parent.text = (parent.text or "") + value
    else:
        previous = parent[index - 1]
        previous.tail = (previous.tail or "") + value


def _drop_child(parent, index: int) -> None:
    child = parent[index]
    tail = child.tail
    parent.remove(child)
    _append_before_child(parent, index, tail)


def _unwrap_child(parent, index: int) -> int:
    wrapper = parent[index]
    children = list(wrapper)
    wrapper_text = wrapper.text
    wrapper_tail = wrapper.tail
    parent.remove(wrapper)
    _append_before_child(parent, index, wrapper_text)
    for offset, child in enumerate(children):
        wrapper.remove(child)
        parent.insert(index + offset, child)
    if children:
        last = children[-1]
        last.tail = (last.tail or "") + (wrapper_tail or "")
        return len(children)
    _append_before_child(parent, index, wrapper_tail)
    return 0


def _drop_dangerous_subtrees(parent) -> None:
    index = 0
    while index < len(parent):
        child = parent[index]
        tag = _tag_name(child)
        if (
            not isinstance(child.tag, str)
            or _has_foreign_namespace(child)
            or tag in DANGEROUS_SUBTREE_TAGS
        ):
            _drop_child(parent, index)
            continue
        _drop_dangerous_subtrees(child)
        index += 1


def _find_legacy_tag_end(value: str, start_index: int) -> int:
    quote = None
    for index in range(start_index + 1, len(value)):
        character = value[index]
        if quote:
            if character == quote:
                quote = None
        elif character in {'"', "'"}:
            quote = character
        elif character == ">":
            return index
    return -1


def _legacy_tag_name(candidate: str) -> str | None:
    match = re.match(r"^</?([A-Za-z]+)(?:\s|/?>)", candidate)
    return match.group(1).lower() if match else None


def _recover_legacy_tags_from_text(value: str) -> str | None:
    cursor = 0
    output = []
    recovered = False
    while cursor < len(value):
        tag_start = value.find("<", cursor)
        if tag_start < 0:
            output.append(html.escape(value[cursor:], quote=False))
            break
        output.append(html.escape(value[cursor:tag_start], quote=False))
        tag_end = _find_legacy_tag_end(value, tag_start)
        if tag_end < 0:
            output.append(html.escape(value[tag_start:], quote=False))
            break
        candidate = value[tag_start : tag_end + 1]
        tag_name = _legacy_tag_name(candidate)
        if tag_name in LEGACY_MEDIA_TAGS:
            output.append(candidate)
            recovered = True
        else:
            output.append(html.escape(candidate, quote=False))
        cursor = tag_end + 1
    return "".join(output) if recovered else None


def _parse_fragment(value: str):
    parser = html5lib_shim.HTMLParser(namespaceHTMLElements=False)
    document = parser.parse(
        f"<!doctype html><html><head></head><body>{value}",
        scripting=True,
    )
    body = next(
        (element for element in document.iter() if _tag_name(element) == "body"),
        None,
    )
    if body is None:
        raise ValueError("HTML5 parser did not return a body")
    fragment = Element("DOCUMENT_FRAGMENT")
    fragment.text = body.text
    for child in list(body):
        body.remove(child)
        fragment.append(child)
    return fragment


def _replace_text_slot(parent, preceding_child, value: str) -> None:
    recovered_html = _recover_legacy_tags_from_text(value)
    if recovered_html is None:
        return
    fragment = _parse_fragment(recovered_html)
    _drop_dangerous_subtrees(fragment)
    new_children = list(fragment)
    if preceding_child is None:
        parent.text = fragment.text or ""
        insertion_index = 0
    else:
        preceding_child.tail = fragment.text or ""
        insertion_index = list(parent).index(preceding_child) + 1
    for offset, child in enumerate(new_children):
        fragment.remove(child)
        parent.insert(insertion_index + offset, child)


def _recover_legacy_media(element, *, inside_code: bool = False, state: list[int] | None = None) -> None:
    if state is None:
        state = [0]
    tag = _tag_name(element)
    protected = inside_code or tag in {"pre", "code"}
    original_children = list(element)
    if not protected and element.text and state[0] < MAX_LEGACY_MEDIA_RECOVERIES:
        if _recover_legacy_tags_from_text(element.text) is not None:
            _replace_text_slot(element, None, element.text)
            state[0] += 1
    for child in original_children:
        _recover_legacy_media(child, inside_code=protected, state=state)
        if not protected and child.tail and state[0] < MAX_LEGACY_MEDIA_RECOVERIES:
            if _recover_legacy_tags_from_text(child.tail) is not None:
                _replace_text_slot(element, child, child.tail)
                state[0] += 1


def _safe_text(value: object, maximum: int) -> str | None:
    if not isinstance(value, str) or not value or len(value) > maximum:
        return None
    if any(ord(character) < 0x20 or ord(character) == 0x7F for character in value):
        return None
    return value


def _canonical_upload_url(value: object) -> str | None:
    if (
        not isinstance(value, str)
        or not value
        or value != value.strip()
        or len(value) > MAX_URL_LENGTH
        or PERCENT_ESCAPE_PATTERN.search(value)
        or any(
            ord(character) < 0x20
            or ord(character) == 0x7F
            or character == "\\"
            or character.isspace()
            for character in value
        )
    ):
        return None
    match = OBJECT_URL_PATTERN.fullmatch(value)
    if match is None or match.group(1) != match.group(2)[:2]:
        return None
    canonical_url = (
        f"/api/uploads/objects/{match.group(1)}/{match.group(2)}{match.group(3)}"
    )
    try:
        return object_url(canonical_object_key(canonical_url))
    except ValueError:
        return None


def _normalized_pdf_type(value: object) -> str | None:
    if not isinstance(value, str):
        return None
    normalized = value.lower()
    return normalized if normalized in PDF_TYPES else None


def _normalized_video_type(value: object) -> str | None:
    if not isinstance(value, str):
        return None
    normalized = value.lower()
    return normalized if normalized in VIDEO_MIME_TYPES else None


def _first_descendant_attribute(element, names: tuple[str, ...], normalizer):
    for descendant in element.iter():
        if descendant is element:
            continue
        for name in names:
            normalized = normalizer(descendant.attrib.get(name))
            if normalized is not None:
                return normalized
    return None


def _ensure_class(element, class_name: str) -> None:
    classes = _class_names(element)
    if class_name not in classes:
        classes.append(class_name)
    element.attrib["class"] = " ".join(classes)


def _normalize_pdf_placeholders(fragment) -> None:
    for element in fragment.iter():
        if _tag_name(element) != "div" or element.attrib.get("data-inline-pdf-viewer") != "true":
            continue
        url = _canonical_upload_url(element.attrib.get("data-pdf-url"))
        if url is None:
            continue
        _ensure_class(element, "file-attachment")
        element.attrib["data-file-url"] = url
        title = _safe_text(element.attrib.get("data-pdf-title"), 255)
        if title:
            element.attrib["data-file-name"] = title
        element.attrib["data-file-type"] = "pdf"


def _hoist_attachment_metadata(fragment) -> None:
    _normalize_pdf_placeholders(fragment)
    for element in fragment.iter():
        if _tag_name(element) != "div" or "file-attachment" not in _class_names(element):
            continue
        parent_url = _canonical_upload_url(element.attrib.get("data-file-url"))
        url = parent_url or _first_descendant_attribute(
            element, ("data-file-url", "data-pdf-url"), _canonical_upload_url
        )
        if url:
            element.attrib["data-file-url"] = url
        name = _safe_text(element.attrib.get("data-file-name"), 255) or _first_descendant_attribute(
            element, ("data-file-name", "data-pdf-title"), lambda value: _safe_text(value, 255)
        )
        if name:
            element.attrib["data-file-name"] = name
        size = _safe_text(element.attrib.get("data-file-size"), 64) or _first_descendant_attribute(
            element, ("data-file-size",), lambda value: _safe_text(value, 64)
        )
        if size:
            element.attrib["data-file-size"] = size
        file_type = _normalized_pdf_type(
            element.attrib.get("data-file-type")
        ) or _first_descendant_attribute(
            element, ("data-file-type",), _normalized_pdf_type
        )
        if file_type:
            element.attrib["data-file-type"] = file_type


def _descendants(element, tag: str):
    return [candidate for candidate in element.iter() if _tag_name(candidate) == tag]


def _hoist_video_metadata(fragment) -> None:
    for figure in fragment.iter():
        if _tag_name(figure) != "figure" or "video-container" not in _class_names(figure):
            continue
        videos = _descendants(figure, "video")
        video = videos[0] if videos else None
        sources = _descendants(video, "source") if video is not None else []
        source = sources[0] if sources else None
        direct_url = _canonical_upload_url(video.attrib.get("src")) if video is not None else None
        source_url = _canonical_upload_url(source.attrib.get("src")) if source is not None else None
        fallback_url = _first_descendant_attribute(
            figure, ("data-video-url",), _canonical_upload_url
        )
        selected_url = direct_url or source_url or fallback_url
        if selected_url is None:
            continue
        if video is None:
            video = Element("video")
            video.attrib["controls"] = ""
            figure.append(video)
        if direct_url:
            video.attrib["src"] = direct_url
            continue
        if source is None:
            source = Element("source")
            video.append(source)
        source.attrib["src"] = selected_url
        source_type = _normalized_video_type(source.attrib.get("type")) or _first_descendant_attribute(
            figure, ("data-video-type",), _normalized_video_type
        )
        if source_type:
            source.attrib["type"] = source_type


def _drop_source_descendants(parent) -> None:
    index = 0
    while index < len(parent):
        child = parent[index]
        if _tag_name(child) == "source":
            _drop_child(parent, index)
            continue
        _drop_source_descendants(child)
        index += 1


def _normalize_video_sources(fragment) -> None:
    for video in list(fragment.iter()):
        if _tag_name(video) != "video":
            continue
        direct_url = _canonical_upload_url(video.attrib.get("src"))
        candidates = [
            (
                _canonical_upload_url(source.attrib.get("src")),
                _normalized_video_type(source.attrib.get("type")),
            )
            for source in _descendants(video, "source")
        ]
        typed = next(
            ((url, source_type) for url, source_type in candidates if url and source_type),
            None,
        )
        untyped_url = next((url for url, _source_type in candidates if url), None)

        _drop_source_descendants(video)
        video.attrib.pop("src", None)
        if direct_url:
            video.attrib["src"] = direct_url
        elif typed:
            source = Element("source")
            source.attrib.update({"src": typed[0], "type": typed[1]})
            video.append(source)
        elif untyped_url:
            video.attrib["src"] = untyped_url


def _append_style(element, property_name: str, value: str | None) -> None:
    if not value:
        return
    existing = element.attrib.get("style", "")
    separator = "" if not existing or existing.rstrip().endswith(";") else ";"
    element.attrib["style"] = f"{existing}{separator}{property_name}: {value};"


def _convert_import_aliases(fragment) -> None:
    for element in fragment.iter():
        tag = _tag_name(element)
        if tag in ALIAS_TAGS:
            element.tag = ALIAS_TAGS[tag]
            continue
        if tag == "font" and tag in IMPORT_TAGS:
            color = element.attrib.get("color")
            family = element.attrib.get("face") or element.attrib.get("data-font-family")
            size = element.attrib.get("size")
            normalized_size = POINT_TO_PIXEL.get((size or "").lower())
            if normalized_size is None:
                normalized_size = HTML_FONT_SIZE_TO_PIXEL.get(size or "")
            if normalized_size is None and size in CANONICAL_PIXEL_SIZES:
                normalized_size = size
            element.tag = "span"
            retained = {
                name: value for name, value in element.attrib.items() if name in GLOBAL_ATTRIBUTES
            }
            element.attrib.clear()
            element.attrib.update(retained)
            _append_style(element, "color", color)
            _append_style(element, "font-family", family)
            _append_style(element, "font-size", normalized_size)
            continue
        if tag == "div" and element.attrib.get("align"):
            alignment = element.attrib.get("align", "").lower()
            if alignment in CSS_KEYWORDS.get("text-align", ()):
                _append_style(element, "text-align", alignment)
        if tag in {"span", "font"} and element.attrib.get("data-font-family"):
            _append_style(element, "font-family", element.attrib.get("data-font-family"))


def _drop_control_subtrees(parent) -> None:
    index = 0
    while index < len(parent):
        child = parent[index]
        if (
            (_tag_name(child) == "button" and "button" in IMPORT_TAGS)
            or CONTROL_SUBTREE_CLASSES.intersection(_class_names(child))
        ):
            _drop_child(parent, index)
            continue
        _drop_control_subtrees(child)
        index += 1


def _format_number(value: float) -> str:
    if value == 0:
        return "0"
    return f"{value:.6f}".rstrip("0").rstrip(".")


def _clamp(value: float, minimum: float, maximum: float) -> float:
    return max(minimum, min(maximum, value))


def _round_color_byte(unit_value: float) -> int:
    rounded_unit = float(f"{_clamp(unit_value, 0, 1):.6f}")
    return int(rounded_unit * 255 + 0.5)


def _normalize_alpha_token(token: str | None) -> float | None:
    if token is None:
        return 1
    percent = token.endswith("%")
    try:
        amount = float(token[:-1] if percent else token)
    except ValueError:
        return None
    return float(f"{_clamp(amount / (100 if percent else 1), 0, 1):.6f}")


def _canonical_functional_color(channels: tuple[int, int, int], alpha: float) -> str:
    if alpha == 1:
        palette_value = PALETTE_CHANNELS.get(channels)
        if palette_value:
            return palette_value
        return f"rgb({channels[0]}, {channels[1]}, {channels[2]})"
    return f"rgba({channels[0]}, {channels[1]}, {channels[2]}, {_format_number(alpha)})"


def _normalize_rgb_function(value: str) -> str | None:
    match = RGB_COLOR_PATTERN.fullmatch(value)
    if match is None or (match.group(1).lower() == "rgba") != (match.group(5) is not None):
        return None
    channels = []
    for token in match.group(2, 3, 4):
        if token.endswith("%"):
            channels.append(_round_color_byte(float(token[:-1]) / 100))
        else:
            channels.append(int(_clamp(float(token), 0, 255)))
    alpha = _normalize_alpha_token(match.group(5))
    if alpha is None:
        return None
    return _canonical_functional_color(tuple(channels), alpha)


def _hue_channel(minimum: float, maximum: float, raw_hue: float) -> float:
    hue = raw_hue
    if hue < 0:
        hue += 1
    if hue > 1:
        hue -= 1
    if hue < 1 / 6:
        return minimum + (maximum - minimum) * 6 * hue
    if hue < 1 / 2:
        return maximum
    if hue < 2 / 3:
        return minimum + (maximum - minimum) * (2 / 3 - hue) * 6
    return minimum


def _normalize_hsl_function(value: str) -> str | None:
    match = HSL_COLOR_PATTERN.fullmatch(value)
    if match is None or (match.group(1).lower() == "hsla") != (match.group(5) is not None):
        return None
    hue_degrees = float(match.group(2).removesuffix("deg"))
    saturation = _clamp(float(match.group(3)[:-1]) / 100, 0, 1)
    lightness = _clamp(float(match.group(4)[:-1]) / 100, 0, 1)
    alpha = _normalize_alpha_token(match.group(5))
    if alpha is None:
        return None
    hue = ((hue_degrees % 360) + 360) % 360 / 360
    if saturation == 0:
        unit_channels = (lightness, lightness, lightness)
    else:
        maximum = (
            lightness * (1 + saturation)
            if lightness < 0.5
            else lightness + saturation - lightness * saturation
        )
        minimum = 2 * lightness - maximum
        unit_channels = (
            _hue_channel(minimum, maximum, hue + 1 / 3),
            _hue_channel(minimum, maximum, hue),
            _hue_channel(minimum, maximum, hue - 1 / 3),
        )
    channels = tuple(_round_color_byte(channel) for channel in unit_channels)
    return _canonical_functional_color(channels, alpha)


def _normalize_color(value: str) -> str | None:
    if not value or len(value) > 64 or "\\" in value:
        return None
    normalized = value.strip().lower()
    if normalized in SYSTEM_COLOR_KEYWORDS:
        return normalized
    if re.match(r"^(?:rgb|hsl)a?\(", normalized):
        return (
            _normalize_rgb_function(normalized)
            if normalized.startswith("rgb")
            else _normalize_hsl_function(normalized)
        )
    if re.fullmatch(r"[a-z]+", normalized):
        if normalized == "rebeccapurple" or parse_color(normalized) is not None:
            return normalized
        return None
    parsed = parse_color(normalized)
    if parsed is None or isinstance(parsed, str):
        return parsed.lower() if isinstance(parsed, str) else None
    channels = tuple(max(0, min(255, int(channel * 255 + 0.5))) for channel in parsed[:3])
    if parsed.alpha == 1:
        palette_value = PALETTE_CHANNELS.get(channels)
        if palette_value:
            return palette_value
        return f"rgb({channels[0]}, {channels[1]}, {channels[2]})"
    alpha = _format_number(max(0, min(1, float(parsed.alpha))))
    return f"rgba({channels[0]}, {channels[1]}, {channels[2]}, {alpha})"


def _normalize_font_family(value: str) -> str | None:
    if not value or len(value) > MAX_CSS_VALUE_LENGTH or "\\" in value:
        return None
    if any(fragment in value.casefold() for fragment in ("url(", "expression", "@import", ";")):
        return None
    families = [family.strip() for family in value.split(",")]
    if not families or any(FONT_FAMILY_ITEM_PATTERN.fullmatch(family) is None for family in families):
        return None
    return ", ".join(families)


def _normalize_length_token(
    value: str,
    limits: dict[str, tuple[float, float]],
    keywords: frozenset[str] = frozenset(),
) -> str | None:
    normalized = value.strip().lower()
    if normalized in keywords:
        return normalized
    match = LENGTH_PATTERN.fullmatch(normalized)
    if match is None:
        return None
    amount = float(match.group(1))
    unit = (match.group(2) or "").lower()
    if not unit:
        pixel_limits = limits.get("px")
        if amount != 0 or pixel_limits is None or not pixel_limits[0] <= 0 <= pixel_limits[1]:
            return None
        return "0px"
    minimum, maximum = limits.get(unit, (1, 0))
    if not minimum <= amount <= maximum:
        return None
    return f"{_format_number(amount)}{unit}"


def _normalize_css_value(property_name: str, value: str) -> str | None:
    if not value or len(value) > MAX_CSS_VALUE_LENGTH or "\\" in value:
        return None
    if any(ord(character) < 0x20 or ord(character) == 0x7F for character in value):
        return None
    if any(fragment in value.casefold() for fragment in ("expression(", "url(", "@import")):
        return None
    if property_name in {"background-color", "color"}:
        return _normalize_color(value)
    if property_name == "font-family":
        return _normalize_font_family(value)
    if property_name in CSS_KEYWORDS:
        normalized = value.strip().lower()
        return normalized if normalized in CSS_KEYWORDS[property_name] else None
    if property_name == "font-size":
        normalized = value.strip().lower()
        if normalized.endswith("pt"):
            return POINT_TO_PIXEL.get(normalized)
        return _normalize_length_token(
            normalized,
            {"px": (8, 96), "%": (50, 400), "em": (0.5, 6), "rem": (0.5, 6)},
            frozenset(
                {"large", "larger", "medium", "small", "smaller", "x-large", "x-small", "xx-large", "xx-small"}
            ),
        )
    if property_name in {"height", "max-height", "max-width", "width"}:
        return _normalize_length_token(
            value,
            {"px": (0, 4096), "%": (0, 100), "em": (0, 256), "rem": (0, 256)},
            frozenset({"auto", "none"}),
        )
    if property_name == "border-radius":
        tokens = value.split()
        normalized_tokens = [
            _normalize_length_token(
                token,
                {"px": (0, 512), "%": (0, 100), "em": (0, 64), "rem": (0, 64)},
            )
            for token in tokens
        ]
        if not 1 <= len(tokens) <= 4 or any(token is None for token in normalized_tokens):
            return None
        return " ".join(normalized_tokens)
    if property_name == "margin" or property_name.startswith("margin-"):
        tokens = value.split()
        normalized_tokens = [
            _normalize_length_token(
                token,
                {"px": (-512, 512), "%": (-100, 100), "em": (-64, 64), "rem": (-64, 64)},
                frozenset({"auto"}),
            )
            for token in tokens
        ]
        if not 1 <= len(tokens) <= 4 or any(token is None for token in normalized_tokens):
            return None
        return " ".join(normalized_tokens)
    return None


def _normalize_style(style: str) -> str | None:
    declarations: OrderedDict[str, tuple[str, bool]] = OrderedDict()
    without_comments = re.sub(r"/\*[\s\S]*?\*/", "", style)
    for token in tinycss2.parse_declaration_list(without_comments):
        if token.type != "declaration" or token.lower_name not in STYLE_PROPERTIES:
            continue
        value = tinycss2.serialize(token.value).strip()
        normalized = _normalize_css_value(token.lower_name, value)
        if normalized is None:
            continue
        previous = declarations.get(token.lower_name)
        if previous is not None and previous[1] and not token.important:
            continue
        declarations[token.lower_name] = (normalized, token.important)
    if not declarations:
        return None
    return "; ".join(
        f"{name}: {value}" for name, (value, _important) in declarations.items()
    ) + ";"


def _normalize_classes(value: str) -> str | None:
    accepted = []
    for class_name in value.split():
        prefix_match = next(
            (prefix for prefix in CLASS_PREFIXES if class_name.startswith(prefix)), None
        )
        if class_name in CANONICAL_CLASSES:
            accepted.append(class_name)
        elif prefix_match and CLASS_SUFFIX_PATTERN.fullmatch(class_name[len(prefix_match) :]):
            accepted.append(class_name)
    unique = list(dict.fromkeys(accepted))
    return " ".join(unique) if unique else None


def _normalize_link_url(value: object) -> str | None:
    if not isinstance(value, str) or not value or value != value.strip() or len(value) > MAX_URL_LENGTH:
        return None
    if "\\" in value or any(character.isspace() or ord(character) < 0x20 or ord(character) == 0x7F for character in value):
        return None
    if PERCENT_ESCAPE_PATTERN.search(value):
        return None
    try:
        parsed = urlsplit(value)
        decoded_path = unquote(parsed.path, encoding="utf-8", errors="strict")
        if parsed.username is not None or parsed.password is not None:
            return None
        if parsed.scheme:
            if parsed.scheme.lower() != "https" or not parsed.hostname:
                return None
            _ = parsed.port
        elif parsed.netloc or value.startswith("//"):
            return None
        segments = decoded_path.split("/")
        if any(segment in {".", ".."} for segment in segments):
            return None
        if any(character.isspace() or ord(character) < 0x20 or character == "\\" for character in decoded_path):
            return None
    except (ValueError, UnicodeError):
        return None
    return value


def _normalize_dimension(value: object) -> str | None:
    if not isinstance(value, str) or not value or len(value) > 32 or value.startswith("-"):
        return None
    normalized = value.strip().lower()
    if re.fullmatch(r"\d+(?:\.\d+)?", normalized):
        amount = float(normalized)
        return _format_number(amount) if 0 <= amount <= 4096 else None
    return _normalize_length_token(
        normalized,
        {"px": (0, 4096), "%": (0, 100), "em": (0, 256), "rem": (0, 256)},
        frozenset({"auto"}),
    )


def _normalize_span(value: object) -> str | None:
    if not isinstance(value, str) or re.fullmatch(r"\d{1,3}", value) is None:
        return None
    amount = int(value)
    return str(amount) if 1 <= amount <= 100 else None


def _normalize_element_attributes(element) -> None:
    tag = _tag_name(element)
    original = dict(element.attrib)
    normalized: OrderedDict[str, str] = OrderedDict()
    class_value = _normalize_classes(original.get("class", ""))
    if class_value:
        normalized["class"] = class_value
    style_value = _normalize_style(original.get("style", ""))
    if style_value:
        normalized["style"] = style_value

    if tag == "a":
        href = _normalize_link_url(original.get("href"))
        if href:
            normalized["href"] = href
        title = _safe_text(original.get("title"), 512)
        if title:
            normalized["title"] = title
        if href and original.get("target") == "_blank":
            normalized["target"] = "_blank"
            normalized["rel"] = "noopener noreferrer"
    elif tag == "div" and "file-attachment" in (class_value or "").split():
        url = _canonical_upload_url(original.get("data-file-url"))
        if url:
            normalized["data-file-url"] = url
        for name, maximum in (("data-file-name", 255), ("data-file-size", 64)):
            value = _safe_text(original.get(name), maximum)
            if value:
                normalized[name] = value
        file_type = _normalized_pdf_type(original.get("data-file-type"))
        if file_type:
            normalized["data-file-type"] = file_type
    elif tag == "img":
        src = _canonical_upload_url(original.get("src"))
        if src:
            normalized["src"] = src
        for name in ("alt", "title"):
            value = _safe_text(original.get(name), 512)
            if value:
                normalized[name] = value
        for name in ("height", "width"):
            value = _normalize_dimension(original.get(name))
            if value:
                normalized[name] = value
    elif tag == "source":
        src = _canonical_upload_url(original.get("src"))
        if src:
            normalized["src"] = src
        source_type = _normalized_video_type(original.get("type"))
        if source_type:
            normalized["type"] = source_type
    elif tag == "video":
        src = _canonical_upload_url(original.get("src"))
        if src:
            normalized["src"] = src
        if "controls" in original:
            normalized["controls"] = ""
        if original.get("preload", "").lower() == "metadata":
            normalized["preload"] = "metadata"
        for name in ("height", "width"):
            value = _normalize_dimension(original.get(name))
            if value:
                normalized[name] = value
    elif tag in {"td", "th"}:
        for name in ("colspan", "rowspan"):
            value = _normalize_span(original.get(name))
            if value:
                normalized[name] = value
        if tag == "th" and original.get("scope", "").lower() in {"col", "colgroup", "row", "rowgroup"}:
            normalized["scope"] = original["scope"].lower()
    element.attrib.clear()
    element.attrib.update(normalized)


def _unwrap_unsupported(parent) -> None:
    index = 0
    while index < len(parent):
        child = parent[index]
        tag = _tag_name(child)
        if tag in CANONICAL_TAG_SET:
            _unwrap_unsupported(child)
            index += 1
            continue
        inserted = _unwrap_child(parent, index)
        if inserted == 0:
            continue


def _remove_orphan_sources(parent) -> None:
    index = 0
    parent_tag = _tag_name(parent)
    while index < len(parent):
        child = parent[index]
        if _tag_name(child) == "source" and parent_tag != "video":
            _drop_child(parent, index)
            continue
        _remove_orphan_sources(child)
        index += 1


def _normalize_tree(fragment) -> None:
    _drop_dangerous_subtrees(fragment)
    _recover_legacy_media(fragment)
    _drop_dangerous_subtrees(fragment)
    _hoist_attachment_metadata(fragment)
    _hoist_video_metadata(fragment)
    _normalize_video_sources(fragment)
    _convert_import_aliases(fragment)
    _drop_control_subtrees(fragment)
    _unwrap_unsupported(fragment)
    _remove_orphan_sources(fragment)
    for element in fragment.iter():
        if element is not fragment:
            _normalize_element_attributes(element)


def _serialize_fragment(fragment) -> str:
    walker = html5lib_shim.getTreeWalker("etree")
    serializer = html5lib_shim.BleachHTMLSerializer(
        quote_attr_values="always",
        omit_optional_tags=False,
        escape_lt_in_attrs=True,
        resolve_entities=False,
        sanitize=False,
        alphabetical_attributes=False,
    )
    return serializer.render(walker(fragment))


class ContractCSSSanitizer(CSSSanitizer):
    def sanitize_css(self, style: str) -> str:
        return _normalize_style(style) or ""


def _attribute_allowed(tag: str, name: str, _value: str) -> bool:
    return name in GLOBAL_ATTRIBUTES or name in TAG_ATTRIBUTES.get(tag, frozenset())


def _canonical_cleaner() -> bleach.Cleaner:
    return bleach.Cleaner(
        tags=CANONICAL_TAGS,
        attributes=_attribute_allowed,
        protocols={"https"},
        css_sanitizer=ContractCSSSanitizer(allowed_css_properties=STYLE_PROPERTIES),
        strip=True,
        strip_comments=True,
    )


def sanitize_rich_text_html(content: object) -> str:
    """Normalize legacy markup and return canonical, backend-authoritative HTML."""

    if not isinstance(content, str):
        return ""
    try:
        fragment = _parse_fragment(content)
        _normalize_tree(fragment)
        return _canonical_cleaner().clean(_serialize_fragment(fragment))
    except Exception:
        return ""


__all__ = ("sanitize_rich_text_html",)
