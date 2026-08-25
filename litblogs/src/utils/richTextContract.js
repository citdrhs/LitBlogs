import rawContract from "../../rich_text_contract.json";

const ERROR_MESSAGE = "Invalid rich-text contract";
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
const EXPECTED_FONT_FAMILIES = [
  ["Arial", "Arial, Helvetica, sans-serif"],
  ["Courier New", '"Courier New", Courier, monospace'],
  ["Georgia", 'Georgia, "Times New Roman", Times, serif'],
  ["Tahoma", "Tahoma, Arial, Helvetica, sans-serif"],
  ["Times New Roman", '"Times New Roman", Times, serif'],
  ["Trebuchet MS", '"Trebuchet MS", Geneva, sans-serif'],
  ["Verdana", "Verdana, Geneva, sans-serif"],
];
const EXPECTED_FONT_SIZES = [
  ["8 pt", "8pt", "10.667px"], ["10 pt", "10pt", "13.333px"],
  ["12 pt", "12pt", "16px"], ["14 pt", "14pt", "18.667px"],
  ["16 pt", "16pt", "21.333px"], ["18 pt", "18pt", "24px"],
  ["24 pt", "24pt", "32px"], ["36 pt", "36pt", "48px"],
  ["48 pt", "48pt", "64px"],
];
const EXPECTED_TAGS = [
  "a", "blockquote", "br", "code", "div", "em", "figure", "h1", "h2",
  "h3", "h4", "h5", "h6", "hr", "img", "li", "mark", "ol", "p",
  "pre", "s", "source", "span",
  "strong", "table", "tbody", "td", "th", "thead", "tr", "u", "ul", "video",
];
const EXPECTED_GLOBAL_ATTRIBUTES = ["class", "style"];
const EXPECTED_TAG_ATTRIBUTES = {
  a: ["href", "rel", "target", "title"],
  div: ["data-file-name", "data-file-size", "data-file-type", "data-file-url"],
  img: ["alt", "height", "src", "title", "width"],
  source: ["src", "type"],
  td: ["colspan", "rowspan"],
  th: ["colspan", "rowspan", "scope"],
  video: ["controls", "height", "preload", "src", "width"],
};
const EXPECTED_CLASSES = [
  "aligncenter", "alignleft", "alignright", "custom-font", "d-block",
  "file-attachment", "file-icon", "file-info", "file-name", "file-size",
  "float-left", "float-right", "img-fluid", "mx-auto", "post-image",
  "preserved-heading", "video-container",
];
const EXPECTED_CLASS_PREFIXES = ["language-"];
const EXPECTED_STYLE_PROPERTIES = [
  "background-color", "border-radius", "color", "display", "float", "font-family",
  "font-size", "font-style", "font-weight", "height", "margin", "margin-bottom",
  "margin-left", "margin-right", "margin-top", "max-height", "max-width",
  "overflow-wrap", "text-align", "text-decoration", "width", "word-break",
];
const EXPECTED_CSS_KEYWORDS = {
  display: ["block", "inline", "inline-block", "list-item", "table", "table-cell", "table-row"],
  float: ["left", "none", "right"],
  "font-style": ["italic", "normal", "oblique"],
  "font-weight": [
    "100", "200", "300", "400", "500", "600", "700", "800", "900",
    "bold", "bolder", "lighter", "normal",
  ],
  "overflow-wrap": ["anywhere", "break-word", "normal"],
  "text-align": ["center", "end", "justify", "left", "right", "start"],
  "text-decoration": ["line-through", "none", "overline", "underline"],
  "word-break": ["break-all", "break-word", "keep-all", "normal"],
};
const EXPECTED_VIDEO_MIME_TYPES = [
  "video/mp4", "video/webm", "video/ogg", "video/x-m4v", "video/x-msvideo",
  "video/x-matroska",
];
const EXPECTED_PDF_TYPES = ["pdf", "application/pdf"];
const EXPECTED_IMPORT_TAGS = ["b", "button", "del", "font", "i", "strike"];
const EXPECTED_IMPORT_TAG_ATTRIBUTES = {
  button: ["data-file-url", "data-video-url", "type"],
  div: [
    "align", "contenteditable", "data-inline-pdf-viewer", "data-pdf-title",
    "data-pdf-url", "data-video-type", "data-video-url",
  ],
  figure: ["contenteditable"],
  font: ["color", "face", "size", "data-font-family"],
  h1: ["data-heading"],
  h2: ["data-heading"],
  h3: ["data-heading"],
  h4: ["data-heading"],
  h5: ["data-heading"],
  h6: ["data-heading"],
  span: ["data-font-family"],
};
const EXPECTED_IMPORT_CLASSES = [
  "audio-placeholder", "download-btn", "editor-only", "editor-only-control",
  "embed-placeholder", "file-actions", "file-placeholder", "mceEditable",
  "mceNonEditable", "media-placeholder", "preview-btn", "remove-btn",
  "text-blue-500", "video-data", "video-delete-btn", "video-delete-overlay",
  "video-placeholder", "video-wrapper",
];

const HEX_COLOR_PATTERN = /^#[0-9a-f]{6}$/;
const HTML_NAME_PATTERN = /^[a-z][a-z0-9-]*$/;
const CLASS_NAME_PATTERN = /^[A-Za-z][A-Za-z0-9_-]*$/;
const CSS_KEYWORD_PATTERN = /^[a-z0-9][a-z0-9-]*$/;
const FONT_SIZE_PATTERN = /^(?:[1-9][0-9]*)(?:\.[0-9]+)?(?:pt|px)$/;
const MIME_PATTERN = /^(?:video|application)\/[a-z0-9][a-z0-9.+-]*$/;

const fail = () => {
  throw new Error(ERROR_MESSAGE);
};

const assert = (condition) => {
  if (!condition) fail();
};

const isPlainObject = (value) => (
  value !== null
  && typeof value === "object"
  && !Array.isArray(value)
  && Object.getPrototypeOf(value) === Object.prototype
);

const assertExactKeys = (value, expectedKeys) => {
  assert(isPlainObject(value));
  const actual = Object.keys(value).sort();
  const expected = [...expectedKeys].sort();
  assert(JSON.stringify(actual) === JSON.stringify(expected));
};

const isSafeString = (value, maximum = 128) => (
  typeof value === "string"
  && value.length > 0
  && value.length <= maximum
  && Array.from(value).every((character) => {
    const codePoint = character.codePointAt(0);
    return codePoint >= 0x20 && codePoint !== 0x7f;
  })
);

const assertStringList = (value) => {
  assert(Array.isArray(value));
  assert(value.every((item) => isSafeString(item)));
  assert(new Set(value).size === value.length);
};

const assertExactList = (value, expected) => {
  assertStringList(value);
  assert(JSON.stringify(value) === JSON.stringify(expected));
};

const assertHtmlNames = (value, expected) => {
  assertExactList(value, expected);
  assert(value.every((name) => HTML_NAME_PATTERN.test(name) && !name.startsWith("on")));
};

const assertClasses = (value, expected) => {
  assertExactList(value, expected);
  assert(value.every((name) => CLASS_NAME_PATTERN.test(name)));
};

const validatePalette = (value, expected) => {
  assert(Array.isArray(value));
  const records = value.map((entry) => {
    assertExactKeys(entry, ["label", "value"]);
    assert(isSafeString(entry.label, 32));
    assert(entry.value === null || (typeof entry.value === "string" && HEX_COLOR_PATTERN.test(entry.value)));
    return [entry.label, entry.value];
  });
  assert(new Set(records.map((record) => JSON.stringify(record))).size === records.length);
  assert(JSON.stringify(records) === JSON.stringify(expected));
};

const validateFonts = (value) => {
  assert(Array.isArray(value));
  const records = value.map((entry) => {
    assertExactKeys(entry, ["label", "cssValue"]);
    assert(isSafeString(entry.label, 32) && isSafeString(entry.cssValue));
    assert(!/(?:url\(|expression|@import|;|\\)/i.test(entry.cssValue));
    return [entry.label, entry.cssValue];
  });
  assert(new Set(records.map((record) => JSON.stringify(record))).size === records.length);
  assert(JSON.stringify(records) === JSON.stringify(EXPECTED_FONT_FAMILIES));
};

const validateFontSizes = (value) => {
  assert(Array.isArray(value));
  const records = value.map((entry) => {
    assertExactKeys(entry, ["label", "legacyValue", "cssValue"]);
    assert(isSafeString(entry.label, 16));
    assert(typeof entry.legacyValue === "string" && FONT_SIZE_PATTERN.test(entry.legacyValue));
    assert(typeof entry.cssValue === "string" && FONT_SIZE_PATTERN.test(entry.cssValue));
    return [entry.label, entry.legacyValue, entry.cssValue];
  });
  assert(new Set(records.map((record) => JSON.stringify(record))).size === records.length);
  assert(JSON.stringify(records) === JSON.stringify(EXPECTED_FONT_SIZES));
};

const validateHtml = (html) => {
  assertExactKeys(html, [
    "tags", "globalAttributes", "tagAttributes", "classes", "classPrefixes",
    "styleProperties", "cssKeywords", "videoMimeTypes", "pdfTypes",
  ]);
  assertHtmlNames(html.tags, EXPECTED_TAGS);
  assertHtmlNames(html.globalAttributes, EXPECTED_GLOBAL_ATTRIBUTES);
  assertExactKeys(html.tagAttributes, Object.keys(EXPECTED_TAG_ATTRIBUTES));
  Object.entries(EXPECTED_TAG_ATTRIBUTES).forEach(([tag, attributes]) => {
    assert(html.tags.includes(tag));
    assertHtmlNames(html.tagAttributes[tag], attributes);
  });
  assertClasses(html.classes, EXPECTED_CLASSES);
  assertExactList(html.classPrefixes, EXPECTED_CLASS_PREFIXES);
  assert(html.classPrefixes.every((prefix) => (
    prefix.endsWith("-") && CLASS_NAME_PATTERN.test(prefix.slice(0, -1))
  )));
  assertHtmlNames(html.styleProperties, EXPECTED_STYLE_PROPERTIES);
  assertExactKeys(html.cssKeywords, Object.keys(EXPECTED_CSS_KEYWORDS));
  Object.entries(EXPECTED_CSS_KEYWORDS).forEach(([property, values]) => {
    assert(html.styleProperties.includes(property));
    assertExactList(html.cssKeywords[property], values);
    assert(html.cssKeywords[property].every((item) => CSS_KEYWORD_PATTERN.test(item)));
  });
  assertExactList(html.videoMimeTypes, EXPECTED_VIDEO_MIME_TYPES);
  assert(html.videoMimeTypes.every((item) => MIME_PATTERN.test(item) && item.startsWith("video/")));
  assertExactList(html.pdfTypes, EXPECTED_PDF_TYPES);
  assert(html.pdfTypes.every((item) => item === "pdf" || MIME_PATTERN.test(item)));
};

const validateImportOnly = (importOnly, html) => {
  assertExactKeys(importOnly, ["tags", "tagAttributes", "classes"]);
  assertHtmlNames(importOnly.tags, EXPECTED_IMPORT_TAGS);
  assert(importOnly.tags.every((tag) => !html.tags.includes(tag)));
  assertExactKeys(importOnly.tagAttributes, Object.keys(EXPECTED_IMPORT_TAG_ATTRIBUTES));
  Object.entries(EXPECTED_IMPORT_TAG_ATTRIBUTES).forEach(([tag, attributes]) => {
    assert(html.tags.includes(tag) || importOnly.tags.includes(tag));
    assertHtmlNames(importOnly.tagAttributes[tag], attributes);
    const canonicalForTag = new Set([
      ...html.globalAttributes,
      ...(html.tagAttributes[tag] || []),
    ]);
    assert(importOnly.tagAttributes[tag].every((attribute) => !canonicalForTag.has(attribute)));
  });
  assertClasses(importOnly.classes, EXPECTED_IMPORT_CLASSES);
  assert(importOnly.classes.every((name) => !html.classes.includes(name)));
};

const cloneJsonValue = (value) => {
  if (Array.isArray(value)) return value.map(cloneJsonValue);
  if (isPlainObject(value)) {
    return Object.fromEntries(
      Object.entries(value).map(([key, item]) => [key, cloneJsonValue(item)]),
    );
  }
  return value;
};

const deepFreeze = (value) => {
  if (value !== null && typeof value === "object" && !Object.isFrozen(value)) {
    Object.values(value).forEach(deepFreeze);
    Object.freeze(value);
  }
  return value;
};

export const validateRichTextContract = (value) => {
  try {
    assertExactKeys(value, [
      "schemaVersion", "palettes", "fontFamilies", "fontSizes", "html", "importOnly",
    ]);
    assert(Number.isInteger(value.schemaVersion) && value.schemaVersion === 1);
    assertExactKeys(value.palettes, ["text", "highlight"]);
    validatePalette(value.palettes.text, EXPECTED_TEXT_PALETTE);
    validatePalette(value.palettes.highlight, EXPECTED_HIGHLIGHT_PALETTE);
    validateFonts(value.fontFamilies);
    validateFontSizes(value.fontSizes);
    validateHtml(value.html);
    validateImportOnly(value.importOnly, value.html);
    return deepFreeze(cloneJsonValue(value));
  } catch {
    throw new Error(ERROR_MESSAGE);
  }
};

export const RICH_TEXT_CONTRACT = validateRichTextContract(rawContract);
export const TEXT_COLOR_PALETTE = RICH_TEXT_CONTRACT.palettes.text;
export const HIGHLIGHT_COLOR_PALETTE = RICH_TEXT_CONTRACT.palettes.highlight;
export const FONT_FAMILIES = RICH_TEXT_CONTRACT.fontFamilies;
export const FONT_SIZES = RICH_TEXT_CONTRACT.fontSizes;
export const HTML_CONTRACT = RICH_TEXT_CONTRACT.html;

const rgbAlias = (hexColor) => {
  const channels = [1, 3, 5].map((offset) => Number.parseInt(hexColor.slice(offset, offset + 2), 16));
  return `rgb(${channels.join(", ")})`;
};

export const PALETTE_RGB_ALIASES = deepFreeze(Object.fromEntries(
  [...TEXT_COLOR_PALETTE, ...HIGHLIGHT_COLOR_PALETTE]
    .filter(({ value }) => value !== null)
    .map(({ value }) => [rgbAlias(value), value]),
));
