import copy
import json
import os
import subprocess
import sys
from pathlib import Path
from types import MappingProxyType

import pytest

from rich_text_contract import (
    RICH_TEXT_CONTRACT,
    RichTextContractError,
    load_rich_text_contract,
    validate_rich_text_contract_data,
)

BACKEND_DIR = Path(__file__).resolve().parents[1]
CONTRACT_PATH = BACKEND_DIR / "rich_text_contract.json"

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
EXPECTED_FONTS = (
    ("Arial", "Arial, Helvetica, sans-serif"),
    ("Courier New", '"Courier New", Courier, monospace'),
    ("Georgia", 'Georgia, "Times New Roman", Times, serif'),
    ("Tahoma", "Tahoma, Arial, Helvetica, sans-serif"),
    ("Times New Roman", '"Times New Roman", Times, serif'),
    ("Trebuchet MS", '"Trebuchet MS", Geneva, sans-serif'),
    ("Verdana", "Verdana, Geneva, sans-serif"),
)
EXPECTED_SIZES = (
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


def _mutable_contract():
    return json.loads(CONTRACT_PATH.read_text(encoding="utf-8"))


def test_contract_has_exact_editor_choices_and_is_deeply_immutable():
    contract = RICH_TEXT_CONTRACT

    assert contract["schemaVersion"] == 1
    assert tuple((entry["label"], entry["value"]) for entry in contract["palettes"]["text"]) == EXPECTED_TEXT_PALETTE
    assert (
        tuple((entry["label"], entry["value"]) for entry in contract["palettes"]["highlight"])
        == EXPECTED_HIGHLIGHT_PALETTE
    )
    assert tuple((entry["label"], entry["cssValue"]) for entry in contract["fontFamilies"]) == EXPECTED_FONTS
    assert (
        tuple((entry["label"], entry["legacyValue"], entry["cssValue"]) for entry in contract["fontSizes"])
        == EXPECTED_SIZES
    )
    assert isinstance(contract, MappingProxyType)
    assert isinstance(contract["html"], MappingProxyType)
    assert isinstance(contract["html"]["tags"], tuple)
    with pytest.raises(TypeError):
        contract["schemaVersion"] = 2
    with pytest.raises(TypeError):
        contract["palettes"]["text"][0]["value"] = "#000000"


def test_html_policy_is_referentially_sound_and_separates_import_only_metadata():
    contract = RICH_TEXT_CONTRACT
    html = contract["html"]
    imported = contract["importOnly"]
    tags = set(html["tags"])
    legacy_aliases = {"b", "i", "del", "strike", "font"}
    assert set(html["tagAttributes"]).issubset(tags)
    assert set(html["cssKeywords"]).issubset(html["styleProperties"])
    assert {"h5", "h6", "figure", "source", "video"}.issubset(tags)
    assert legacy_aliases.isdisjoint(tags)
    assert "font" not in html["tagAttributes"]
    assert {"button", *legacy_aliases}.issubset(imported["tags"])
    assert imported["tagAttributes"]["font"] == (
        "color",
        "face",
        "size",
        "data-font-family",
    )
    assert set(imported["tags"]).isdisjoint(tags)
    assert html["tagAttributes"]["div"] == (
        "data-file-name",
        "data-file-size",
        "data-file-type",
        "data-file-url",
    )
    assert set(imported["tagAttributes"]).issubset(tags | set(imported["tags"]))
    for tag, attributes in imported["tagAttributes"].items():
        canonical_for_tag = set(html["globalAttributes"])
        canonical_for_tag.update(html["tagAttributes"].get(tag, ()))
        assert set(attributes).isdisjoint(canonical_for_tag)
    assert set(imported["classes"]).isdisjoint(html["classes"])
    assert "mceNonEditable" in imported["classes"]
    assert "editor-only" in imported["classes"]
    assert "language-" in html["classPrefixes"]
    assert html["videoMimeTypes"] == (
        "video/mp4",
        "video/webm",
        "video/ogg",
        "video/x-m4v",
        "video/x-msvideo",
        "video/x-matroska",
    )
    assert html["pdfTypes"] == ("pdf", "application/pdf")


@pytest.mark.parametrize(
    "mutate",
    [
        lambda value: value.pop("schemaVersion"),
        lambda value: value.update({"unexpected": True}),
        lambda value: value.update({"schemaVersion": "1"}),
        lambda value: value["palettes"]["text"].append(copy.deepcopy(value["palettes"]["text"][0])),
        lambda value: value["fontFamilies"].__setitem__(0, {"label": "Unsafe", "cssValue": "url(https://bad)"}),
        lambda value: value["fontSizes"][0].update({"cssValue": "expression(alert(1))"}),
        lambda value: value["html"]["tags"].append("script"),
        lambda value: value["html"]["globalAttributes"].append("onclick"),
        lambda value: value["html"]["tagAttributes"].update({"script": ["src"]}),
        lambda value: value["html"]["classes"].append("unsafe class"),
        lambda value: value["html"]["styleProperties"].append("background-image"),
        lambda value: value["html"]["videoMimeTypes"].append("text/html"),
        lambda value: value["importOnly"]["tagAttributes"].update({"script": ["src"]}),
        lambda value: value["importOnly"]["tagAttributes"]["div"].append("data-file-url"),
    ],
)
def test_object_validator_fails_closed_for_malformed_contracts(mutate):
    contract = _mutable_contract()
    mutate(contract)

    with pytest.raises(RichTextContractError, match="Invalid rich-text contract"):
        validate_rich_text_contract_data(contract)


def test_path_loader_rejects_missing_malformed_duplicate_and_unexpected_json(tmp_path):
    missing = tmp_path / "missing.json"
    with pytest.raises(RichTextContractError, match="Invalid rich-text contract"):
        load_rich_text_contract(missing)

    malformed = tmp_path / "malformed.json"
    malformed.write_text("{", encoding="utf-8")
    with pytest.raises(RichTextContractError, match="Invalid rich-text contract"):
        load_rich_text_contract(malformed)

    duplicate = tmp_path / "duplicate.json"
    duplicate.write_text('{"schemaVersion":1,"schemaVersion":1}', encoding="utf-8")
    with pytest.raises(RichTextContractError, match="Invalid rich-text contract"):
        load_rich_text_contract(duplicate)

    unexpected = tmp_path / "unexpected.json"
    value = _mutable_contract()
    value["unexpected"] = True
    unexpected.write_text(json.dumps(value), encoding="utf-8")
    with pytest.raises(RichTextContractError, match="Invalid rich-text contract"):
        load_rich_text_contract(unexpected)


def test_default_contract_loading_is_independent_of_current_working_directory(tmp_path):
    environment = os.environ.copy()
    environment["PYTHONPATH"] = str(BACKEND_DIR)
    result = subprocess.run(
        [sys.executable, "-c", "import rich_text_contract; print(rich_text_contract.RICH_TEXT_CONTRACT['schemaVersion'])"],
        cwd=tmp_path,
        env=environment,
        check=False,
        capture_output=True,
        text=True,
    )

    assert result.returncode == 0, result.stderr
    assert result.stdout.strip() == "1"
