// @vitest-environment node

import { describe, expect, it } from "vitest";

import {
  FONT_FAMILIES,
  FONT_SIZES,
  HIGHLIGHT_COLOR_PALETTE,
  PALETTE_RGB_ALIASES,
  RICH_TEXT_CONTRACT,
  TEXT_COLOR_PALETTE,
  validateRichTextContract,
} from "./richTextContract.js";

const EXPECTED_TEXT_PALETTE = [
  ["Ink", "#111827"], ["Slate", "#374151"], ["Gray", "#6b7280"],
  ["Red", "#b91c1c"], ["Orange", "#c2410c"], ["Gold", "#a16207"],
  ["Green", "#15803d"], ["Teal", "#0f766e"], ["Blue", "#1d4ed8"],
  ["Purple", "#6d28d9"], ["Pink", "#be185d"], ["White", "#ffffff"],
];
const EXPECTED_HIGHLIGHT_PALETTE = [
  ["None", null], ["Amber", "#fef3c7"], ["Gold", "#fde68a"],
  ["Red", "#fecaca"], ["Orange", "#fed7aa"], ["Green", "#bbf7d0"],
  ["Blue", "#bfdbfe"], ["Purple", "#ddd6fe"], ["Pink", "#fbcfe8"],
  ["Gray", "#e5e7eb"],
];
const EXPECTED_FONTS = [
  ["Arial", "Arial, Helvetica, sans-serif"],
  ["Courier New", '"Courier New", Courier, monospace'],
  ["Georgia", 'Georgia, "Times New Roman", Times, serif'],
  ["Tahoma", "Tahoma, Arial, Helvetica, sans-serif"],
  ["Times New Roman", '"Times New Roman", Times, serif'],
  ["Trebuchet MS", '"Trebuchet MS", Geneva, sans-serif'],
  ["Verdana", "Verdana, Geneva, sans-serif"],
];
const EXPECTED_SIZES = [
  ["8 pt", "8pt", "10.667px"], ["10 pt", "10pt", "13.333px"],
  ["12 pt", "12pt", "16px"], ["14 pt", "14pt", "18.667px"],
  ["16 pt", "16pt", "21.333px"], ["18 pt", "18pt", "24px"],
  ["24 pt", "24pt", "32px"], ["36 pt", "36pt", "48px"],
  ["48 pt", "48pt", "64px"],
];

const mutableContract = () => JSON.parse(JSON.stringify(RICH_TEXT_CONTRACT));

describe("canonical rich-text contract", () => {
  it("exports the exact ordered editor choices", () => {
    expect(TEXT_COLOR_PALETTE.map(({ label, value }) => [label, value])).toEqual(EXPECTED_TEXT_PALETTE);
    expect(HIGHLIGHT_COLOR_PALETTE.map(({ label, value }) => [label, value])).toEqual(EXPECTED_HIGHLIGHT_PALETTE);
    expect(FONT_FAMILIES.map(({ label, cssValue }) => [label, cssValue])).toEqual(EXPECTED_FONTS);
    expect(FONT_SIZES.map(({ label, legacyValue, cssValue }) => [label, legacyValue, cssValue])).toEqual(EXPECTED_SIZES);
  });

  it("deep-freezes the contract and every projected menu", () => {
    expect(Object.isFrozen(RICH_TEXT_CONTRACT)).toBe(true);
    expect(Object.isFrozen(RICH_TEXT_CONTRACT.html.tags)).toBe(true);
    expect(Object.isFrozen(TEXT_COLOR_PALETTE[0])).toBe(true);
    expect(() => { RICH_TEXT_CONTRACT.schemaVersion = 2; }).toThrow(TypeError);
    expect(() => { FONT_SIZES[0].cssValue = "99px"; }).toThrow(TypeError);
  });

  it("derives lowercase rgb aliases for both palettes", () => {
    expect(PALETTE_RGB_ALIASES["rgb(17, 24, 39)"]).toBe("#111827");
    expect(PALETTE_RGB_ALIASES["rgb(254, 243, 199)"]).toBe("#fef3c7");
    expect(PALETTE_RGB_ALIASES["rgb(255, 255, 255)"]).toBe("#ffffff");
    expect(Object.keys(PALETTE_RGB_ALIASES)).toHaveLength(21);
    expect(Object.isFrozen(PALETTE_RGB_ALIASES)).toBe(true);
  });

  it("keeps canonical HTML and import-only metadata disjoint and referentially sound", () => {
    const html = RICH_TEXT_CONTRACT.html;
    expect(Object.keys(html.tagAttributes).every((tag) => html.tags.includes(tag))).toBe(true);
    expect(Object.keys(html.cssKeywords).every((property) => html.styleProperties.includes(property))).toBe(true);
    expect(html.tags).toEqual(expect.arrayContaining(["font", "h5", "h6", "strike", "video"]));
    expect(html.tags).not.toContain("button");
    expect(RICH_TEXT_CONTRACT.importOnly.tags).toContain("button");
    expect(html.tagAttributes.div).toEqual([
      "data-file-name", "data-file-size", "data-file-type", "data-file-url",
    ]);
    expect(Object.entries(RICH_TEXT_CONTRACT.importOnly.tagAttributes).every(([tag, attributes]) => {
      const allowedTag = html.tags.includes(tag) || RICH_TEXT_CONTRACT.importOnly.tags.includes(tag);
      const canonicalForTag = new Set([
        ...html.globalAttributes,
        ...(html.tagAttributes[tag] || []),
      ]);
      return allowedTag && attributes.every((attribute) => !canonicalForTag.has(attribute));
    })).toBe(true);
    expect(RICH_TEXT_CONTRACT.importOnly.classes.some((value) => html.classes.includes(value))).toBe(false);
  });

  it.each([
    ["missing key", (value) => { delete value.schemaVersion; }],
    ["unexpected key", (value) => { value.unexpected = true; }],
    ["wrong type", (value) => { value.schemaVersion = "1"; }],
    ["duplicate entry", (value) => { value.html.tags.push(value.html.tags[0]); }],
    ["unsafe tag", (value) => { value.html.tags.push("script"); }],
    ["orphan attributes", (value) => { value.html.tagAttributes.script = ["src"]; }],
    ["unsafe class", (value) => { value.html.classes.push("unsafe class"); }],
    ["unsafe style", (value) => { value.html.styleProperties.push("background-image"); }],
    ["unsafe MIME", (value) => { value.html.videoMimeTypes.push("text/html"); }],
    ["unsafe font", (value) => { value.fontFamilies[0].cssValue = "url(https://bad)"; }],
    ["orphan import attributes", (value) => { value.importOnly.tagAttributes.script = ["src"]; }],
    ["cross-mode attributes", (value) => { value.importOnly.tagAttributes.div.push("data-file-url"); }],
  ])("fails closed for %s", (_label, mutate) => {
    const value = mutableContract();
    mutate(value);
    expect(() => validateRichTextContract(value)).toThrow("Invalid rich-text contract");
  });
});
