import DOMPurify from "dompurify";

import { mediaPath } from "./urlUtils.js";

const ALLOWED_TAGS = [
  "a", "b", "blockquote", "br", "button", "code", "del", "div", "em",
  "figure", "font", "h1", "h2", "h3", "h4", "h5", "h6", "hr", "i",
  "img", "li", "mark", "ol", "p", "pre", "s", "source", "span", "strike",
  "strong", "table", "tbody", "td", "th", "thead", "tr", "u", "ul", "video",
];
const ALLOWED_ATTRIBUTES = [
  "align", "alt", "class", "color", "colspan", "contenteditable", "controls",
  "data-file-name", "data-file-size", "data-file-type", "data-file-url",
  "data-font-family", "data-heading", "data-inline-pdf-viewer", "data-pdf-title",
  "data-pdf-url", "data-video-type", "data-video-url", "face", "height", "href",
  "preload", "rel", "rowspan", "scope", "size", "src", "style", "target", "title",
  "type", "width",
];
const ALLOWED_CLASSES = new Set([
  "aligncenter", "alignleft", "alignright", "audio-placeholder", "custom-font", "d-block",
  "download-btn", "editor-only", "editor-only-control", "embed-placeholder", "file-actions",
  "file-attachment", "file-icon", "file-info", "file-name", "file-placeholder", "file-size",
  "float-left", "float-right", "mceNonEditable", "media-placeholder", "mx-auto", "post-image",
  "preserved-heading", "preview-btn", "remove-btn", "text-blue-500", "video-container", "video-data",
  "video-delete-btn", "video-delete-overlay", "video-placeholder", "video-wrapper",
]);
const ALLOWED_STYLE_PROPERTIES = new Set([
  "background-color", "border-radius", "color", "display", "float", "font-family",
  "font-size", "font-style", "font-weight", "height", "margin", "margin-bottom",
  "margin-left", "margin-right", "margin-top", "max-height", "max-width", "overflow-wrap",
  "text-align", "text-decoration", "width", "word-break",
]);
const DISPLAY_ONLY_CONTROL_SELECTOR = [
  "button",
  ".editor-only",
  ".editor-only-control",
  ".video-delete-btn",
  ".video-delete-overlay",
].join(",");
const LEGACY_MEDIA_TAGS = new Set(["figure", "source", "video"]);
const LEGACY_CONTROL_TAGS = new Set(["button"]);
const MIME_TYPE_PATTERN = /^video\/(?:mp4|webm|ogg|x-m4v|x-msvideo|x-matroska)$/i;
const SAFE_UPLOAD_SEGMENT_PATTERN = /^[A-Za-z0-9._-]+$/;
const MAX_URL_LENGTH = 2048;
const MAX_CSS_VALUE_LENGTH = 128;
const MAX_RICH_TEXT_INPUT_LENGTH = 1_000_000;
const MAX_LEGACY_MEDIA_RECOVERIES = 256;
const CSS_KEYWORD_VALUES = {
  display: new Set(["block", "inline", "inline-block", "list-item", "table", "table-cell", "table-row"]),
  float: new Set(["left", "none", "right"]),
  "font-style": new Set(["italic", "normal", "oblique"]),
  "font-weight": new Set(["100", "200", "300", "400", "500", "600", "700", "800", "900", "bold", "bolder", "lighter", "normal"]),
  "overflow-wrap": new Set(["anywhere", "break-word", "normal"]),
  "text-align": new Set(["center", "end", "justify", "left", "right", "start"]),
  "text-decoration": new Set(["line-through", "none", "overline", "underline"]),
  "word-break": new Set(["break-all", "break-word", "keep-all", "normal"]),
};

const purifierConfig = {
  ALLOWED_ATTR: ALLOWED_ATTRIBUTES,
  ALLOWED_TAGS,
  ALLOW_ARIA_ATTR: false,
  ALLOW_DATA_ATTR: false,
  ALLOW_UNKNOWN_PROTOCOLS: false,
  KEEP_CONTENT: true,
  SANITIZE_DOM: true,
};

const hasUnsafeUrlCharacters = (value) => Array.from(value).some((character) => {
  const codePoint = character.codePointAt(0);
  return codePoint <= 0x20
    || codePoint === 0x7f
    || character === "\\"
    || /\s/u.test(character);
});

const hasCssEscapeOrControlCharacter = (value) => (
  value.includes("\\")
  || Array.from(value).some((character) => {
    const codePoint = character.codePointAt(0);
    return codePoint < 0x20 || codePoint === 0x7f;
  })
);

const parseBoundedCssLength = (token, limits, allowedKeywords = new Set()) => {
  const normalizedToken = token.toLowerCase();
  if (allowedKeywords.has(normalizedToken)) {
    return true;
  }

  const match = normalizedToken.match(/^(-?(?:\d+|\d*\.\d+))(px|%|em|rem)?$/);
  if (!match) {
    return false;
  }
  const amount = Number(match[1]);
  const unit = match[2] || "";
  if (!Number.isFinite(amount)) {
    return false;
  }
  if (!unit) {
    return amount === 0;
  }
  const [minimum, maximum] = limits[unit] || [1, 0];
  return amount >= minimum && amount <= maximum;
};

const isBoundedCssValue = (property, value) => {
  if (!value || value.length > MAX_CSS_VALUE_LENGTH) {
    return false;
  }
  if (property === "color" || property === "background-color") {
    return value.length <= 64;
  }
  if (property === "font-family") {
    return value.length <= 128;
  }
  if (CSS_KEYWORD_VALUES[property]) {
    return CSS_KEYWORD_VALUES[property].has(value.toLowerCase());
  }
  if (property === "font-size") {
    return parseBoundedCssLength(
      value,
      { px: [8, 96], "%": [50, 400], em: [0.5, 6], rem: [0.5, 6] },
      new Set(["large", "larger", "medium", "small", "smaller", "x-large", "x-small", "xx-large", "xx-small"]),
    );
  }
  if (["height", "max-height", "max-width", "width"].includes(property)) {
    return parseBoundedCssLength(
      value,
      { px: [0, 4096], "%": [0, 100], em: [0, 256], rem: [0, 256] },
      new Set(["auto", "none"]),
    );
  }
  if (property === "border-radius") {
    return value.split(/\s+/).every((token) => parseBoundedCssLength(
      token,
      { px: [0, 512], "%": [0, 100], em: [0, 64], rem: [0, 64] },
    ));
  }
  if (property === "margin" || property.startsWith("margin-")) {
    const tokens = value.split(/\s+/);
    return tokens.length <= 4 && tokens.every((token) => parseBoundedCssLength(
      token,
      { px: [-512, 512], "%": [-100, 100], em: [-64, 64], rem: [-64, 64] },
      new Set(["auto"]),
    ));
  }
  return false;
};

const isBoundedDimensionAttribute = (value) => {
  const normalizedValue = String(value || "").trim();
  if (!normalizedValue || normalizedValue.length > 32 || normalizedValue.startsWith("-")) {
    return false;
  }
  const cssLength = /^\d+(?:\.\d+)?$/.test(normalizedValue)
    ? `${normalizedValue}px`
    : normalizedValue;
  return parseBoundedCssLength(
    cssLength,
    { px: [0, 4096], "%": [0, 100], em: [0, 256], rem: [0, 256] },
    new Set(["auto"]),
  );
};

const decodePath = (path) => {
  try {
    return decodeURIComponent(path);
  } catch {
    return null;
  }
};

const getCanonicalUploadPath = (url) => {
  if (url.search || url.hash) {
    return null;
  }

  const decodedPath = decodePath(url.pathname);
  if (!decodedPath || decodedPath.includes("\\")) {
    return null;
  }

  const parts = decodedPath.split("/");
  if (parts[0] === "") {
    parts.shift();
  }
  if (parts.some((part) => !part || part === "." || part === "..")) {
    return null;
  }

  const uploadsIndex = parts.findIndex((part, index) => (
    part === "uploads" && (index === 0 || parts[index - 1] === "api")
  ));
  if (uploadsIndex < 0 || uploadsIndex === parts.length - 1) {
    return null;
  }

  const uploadParts = parts.slice(uploadsIndex + 1);
  if (uploadParts.some((part) => (
    part.length > 255 || !SAFE_UPLOAD_SEGMENT_PATTERN.test(part)
  ))) {
    return null;
  }

  return mediaPath(`/uploads/${uploadParts.join("/")}`);
};

export const normalizeRichTextUrl = (rawValue, kind = "link") => {
  if (typeof rawValue !== "string") {
    return null;
  }

  const value = rawValue.trim();
  if (
    !value
    || value !== rawValue
    || value.length > MAX_URL_LENGTH
    || value.startsWith("//")
    || hasUnsafeUrlCharacters(value)
  ) {
    return null;
  }

  const rawPath = value.split(/[?#]/, 1)[0];
  const decodedRawPath = decodePath(rawPath);
  if (
    !decodedRawPath
    || decodedRawPath.split("/").some((part) => part === "." || part === "..")
  ) {
    return null;
  }

  let parsed;
  let base;
  try {
    base = new URL(document.baseURI);
    parsed = new URL(value, base);
  } catch {
    return null;
  }

  if (parsed.username || parsed.password || !["http:", "https:"].includes(parsed.protocol)) {
    return null;
  }

  const sameOrigin = parsed.origin === base.origin;
  if (kind === "link") {
    if (!sameOrigin && parsed.protocol !== "https:") {
      return null;
    }
    return value;
  }

  const uploadPath = sameOrigin ? getCanonicalUploadPath(parsed) : null;
  if (uploadPath) {
    return uploadPath;
  }

  return null;
};

const escapeHtmlText = (value) => String(value || "")
  .replace(/&/g, "&amp;")
  .replace(/</g, "&lt;")
  .replace(/>/g, "&gt;");

const findLegacyTagEnd = (value, startIndex) => {
  let quote = null;
  for (let index = startIndex + 1; index < value.length; index += 1) {
    const character = value[index];
    if (quote) {
      if (character === quote) {
        quote = null;
      }
    } else if (character === '"' || character === "'") {
      quote = character;
    } else if (character === ">") {
      return index;
    }
  }
  return -1;
};

const getLegacyTagName = (candidate) => {
  let index = 1;
  if (candidate[index] === "/") {
    index += 1;
  }
  const nameStart = index;
  while (index < candidate.length && /[A-Za-z]/.test(candidate[index])) {
    index += 1;
  }
  if (index === nameStart || !/[\s/>]/.test(candidate[index] || ">")) {
    return null;
  }
  return candidate.slice(nameStart, index).toLowerCase();
};

const recoverLegacyTagsFromText = (value, allowedTags) => {
  let cursor = 0;
  let output = "";
  let recovered = false;

  while (cursor < value.length) {
    const tagStart = value.indexOf("<", cursor);
    if (tagStart < 0) {
      output += escapeHtmlText(value.slice(cursor));
      break;
    }
    output += escapeHtmlText(value.slice(cursor, tagStart));

    const tagEnd = findLegacyTagEnd(value, tagStart);
    if (tagEnd < 0) {
      output += escapeHtmlText(value.slice(tagStart));
      break;
    }

    const candidate = value.slice(tagStart, tagEnd + 1);
    const tagName = getLegacyTagName(candidate);
    if (tagName && allowedTags.has(tagName)) {
      output += candidate;
      recovered = true;
    } else {
      output += escapeHtmlText(candidate);
    }
    cursor = tagEnd + 1;
  }

  return recovered ? output : null;
};

const sanitizeToFragment = (html) => {
  const untrustedHtml = String(html || "");
  if (untrustedHtml.length > MAX_RICH_TEXT_INPUT_LENGTH) {
    return document.createDocumentFragment();
  }

  // Template contents are inert: media does not load and script does not run.
  // Passing a node also keeps attacker markup out of DOMPurify's DOMParser path.
  const inertTemplate = document.createElement("template");
  inertTemplate.innerHTML = untrustedHtml;
  return DOMPurify.sanitize(inertTemplate.content, {
    ...purifierConfig,
    RETURN_DOM_FRAGMENT: true,
  });
};

const recoverLegacyEscapedMedia = (fragment) => {
  const container = document.createElement("div");
  container.appendChild(fragment);
  const textNodes = [];
  const walker = document.createTreeWalker(container, NodeFilter.SHOW_TEXT);
  while (walker.nextNode()) {
    textNodes.push(walker.currentNode);
  }

  let recoveredMediaCount = 0;
  textNodes.forEach((textNode) => {
    if (recoveredMediaCount >= MAX_LEGACY_MEDIA_RECOVERIES) {
      return;
    }
    const parent = textNode.parentElement;
    if (!parent || parent.closest("pre, code")) {
      return;
    }

    const allowedTags = new Set(LEGACY_MEDIA_TAGS);
    if (parent.closest(".file-actions, .video-delete-overlay")) {
      LEGACY_CONTROL_TAGS.forEach((tagName) => allowedTags.add(tagName));
    }
    const recoveredHtml = recoverLegacyTagsFromText(textNode.nodeValue || "", allowedTags);
    if (!recoveredHtml) {
      return;
    }

    textNode.replaceWith(sanitizeToFragment(recoveredHtml));
    recoveredMediaCount += 1;
  });

  const recoveredFragment = document.createDocumentFragment();
  recoveredFragment.append(...container.childNodes);
  return recoveredFragment;
};

const normalizeClassAttribute = (element) => {
  if (!element.hasAttribute("class")) {
    return;
  }

  const safeClasses = Array.from(element.classList).filter((className) => (
    ALLOWED_CLASSES.has(className) || className.startsWith("language-")
  ));
  if (safeClasses.length > 0) {
    element.setAttribute("class", safeClasses.join(" "));
  } else {
    element.removeAttribute("class");
  }
};

const normalizeStyleAttribute = (element) => {
  if (!element.hasAttribute("style")) {
    return;
  }

  const acceptedStyles = [];
  for (let index = 0; index < element.style.length; index += 1) {
    const property = element.style.item(index).toLowerCase();
    const value = element.style.getPropertyValue(property).trim();
    if (
      ALLOWED_STYLE_PROPERTIES.has(property)
      && value
      && !/(?:expression|url|@import)\s*\(/i.test(value)
      && !hasCssEscapeOrControlCharacter(value)
      && isBoundedCssValue(property, value)
    ) {
      acceptedStyles.push([property, value]);
    }
  }

  element.removeAttribute("style");
  acceptedStyles.forEach(([property, value]) => {
    element.style.setProperty(property, value);
  });
  if (!element.getAttribute("style")) {
    element.removeAttribute("style");
  }
};

const normalizeUrlAttribute = (element, attributeName, kind) => {
  if (!element.hasAttribute(attributeName)) {
    return;
  }

  const normalizedUrl = normalizeRichTextUrl(element.getAttribute(attributeName), kind);
  if (normalizedUrl) {
    element.setAttribute(attributeName, normalizedUrl);
  } else {
    element.removeAttribute(attributeName);
  }
};

const hardenElement = (element) => {
  normalizeClassAttribute(element);
  normalizeStyleAttribute(element);

  if (element.hasAttribute("contenteditable") && element.getAttribute("contenteditable") !== "false") {
    element.removeAttribute("contenteditable");
  }

  if (element.tagName === "A") {
    normalizeUrlAttribute(element, "href", "link");
    if (element.getAttribute("target") === "_blank" && element.hasAttribute("href")) {
      element.setAttribute("rel", "noopener noreferrer");
    } else {
      element.removeAttribute("target");
      element.removeAttribute("rel");
    }
  }
  if (element.tagName === "IMG") {
    normalizeUrlAttribute(element, "src", "image");
  }
  if (element.tagName === "SOURCE") {
    normalizeUrlAttribute(element, "src", "video");
    if (element.hasAttribute("type") && !MIME_TYPE_PATTERN.test(element.getAttribute("type"))) {
      element.removeAttribute("type");
    }
  }
  if (element.tagName === "VIDEO") {
    normalizeUrlAttribute(element, "src", "video");
  }
  if (element.tagName === "BUTTON" && element.getAttribute("type") !== "button") {
    element.setAttribute("type", "button");
  }

  ["data-file-url", "data-pdf-url", "data-video-url"].forEach((attributeName) => {
    normalizeUrlAttribute(element, attributeName, "attachment");
  });
  if (
    element.hasAttribute("data-inline-pdf-viewer")
    && element.getAttribute("data-inline-pdf-viewer") !== "true"
  ) {
    element.removeAttribute("data-inline-pdf-viewer");
  }
  ["width", "height"].forEach((attributeName) => {
    if (
      element.hasAttribute(attributeName)
      && !isBoundedDimensionAttribute(element.getAttribute(attributeName))
    ) {
      element.removeAttribute(attributeName);
    }
  });
};

const buildSanitizedFragment = (html, { mode = "display" } = {}) => {
  const fragment = recoverLegacyEscapedMedia(sanitizeToFragment(html));

  fragment.querySelectorAll("*").forEach(hardenElement);
  if (mode !== "editor") {
    fragment.querySelectorAll(DISPLAY_ONLY_CONTROL_SELECTOR).forEach((element) => element.remove());
  }
  return fragment;
};

export const createSanitizedRichTextContainer = (html, options) => {
  const container = document.createElement("div");
  container.appendChild(buildSanitizedFragment(html, options));
  return container;
};

export const sanitizeRichText = (html, options) => (
  createSanitizedRichTextContainer(html, options).innerHTML
);

export const serializeSanitizedRichText = (container, options) => (
  sanitizeRichText(container?.innerHTML || "", options)
);
