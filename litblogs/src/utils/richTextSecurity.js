import DOMPurify from "dompurify";

import {
  FONT_SIZES,
  HTML_CONTRACT,
  RICH_TEXT_CONTRACT,
} from "./richTextContract.js";
import {
  normalizeImportedColor,
  normalizeLinkUrl as normalizeContractLinkUrl,
} from "../editor/editorContract.js";

const MAX_URL_LENGTH = 2048;
const MAX_CSS_VALUE_LENGTH = 128;
const MAX_RICH_TEXT_INPUT_LENGTH = 1_000_000;
const MAX_LEGACY_MEDIA_RECOVERIES = 256;
const MAX_CANONICALIZATION_PASSES = 5;

const CANONICAL_TAGS = new Set(HTML_CONTRACT.tags);
const IMPORT_TAGS = new Set(RICH_TEXT_CONTRACT.importOnly.tags);
const IMPORT_CLASSES = new Set(RICH_TEXT_CONTRACT.importOnly.classes);
const CANONICAL_CLASSES = new Set(HTML_CONTRACT.classes);
const CLASS_PREFIXES = HTML_CONTRACT.classPrefixes;
const STYLE_PROPERTIES = new Set(HTML_CONTRACT.styleProperties);
const CSS_KEYWORDS = Object.fromEntries(
  Object.entries(HTML_CONTRACT.cssKeywords).map(([property, values]) => [
    property,
    new Set(values),
  ]),
);
const VIDEO_MIME_TYPES = new Set(HTML_CONTRACT.videoMimeTypes);
const PDF_TYPES = new Set(HTML_CONTRACT.pdfTypes);
const POINT_TO_PIXEL = new Map(
  FONT_SIZES.map(({ legacyValue, cssValue }) => [legacyValue, cssValue]),
);
const CANONICAL_PIXEL_SIZES = new Set(FONT_SIZES.map(({ cssValue }) => cssValue));
const HTML_FONT_SIZE_TO_PIXEL = new Map([
  ["1", "10.667px"], ["2", "13.333px"], ["3", "16px"],
  ["4", "18.667px"], ["5", "24px"], ["6", "32px"], ["7", "48px"],
]);

const DANGEROUS_SUBTREE_TAGS = new Set([
  "base", "embed", "form", "head", "iframe", "link", "math", "meta",
  "noscript", "object", "script", "style", "svg", "template",
]);
const CONTROL_SUBTREE_CLASSES = new Set([
  "audio-placeholder", "download-btn", "editor-only", "editor-only-control",
  "embed-placeholder", "file-actions", "file-placeholder", "media-placeholder",
  "preview-btn", "remove-btn", "video-data", "video-delete-btn",
  "video-delete-overlay", "video-placeholder",
].filter((className) => IMPORT_CLASSES.has(className)));
const ALIAS_TAGS = new Map([
  ["b", "strong"], ["i", "em"], ["del", "s"], ["strike", "s"],
].filter(([tag]) => IMPORT_TAGS.has(tag)));
const LEGACY_MEDIA_TAGS = new Set(["figure", "source", "video"]);
const CLASS_SUFFIX_PATTERN = /^[A-Za-z0-9_-]{1,64}$/;
const FONT_FAMILY_ITEM_PATTERN = /^(?:"[^"\\\r\n]+"|'[^'\\\r\n]+'|[A-Za-z][A-Za-z0-9 _-]*)$/;
const LENGTH_PATTERN = /^(-?(?:\d+(?:\.\d+)?|\.\d+))(px|%|em|rem)?$/i;
const OBJECT_URL_PATTERN = /^(?:\/[^/?#]+)*\/api\/uploads\/objects\/([0-9a-f]{2})\/([0-9a-f]{32})(\.[a-z0-9]{1,10})$/;
const MALFORMED_PERCENT_ESCAPE_PATTERN = /%(?![0-9a-f]{2})/i;

const canonicalAllowedAttributes = Array.from(new Set([
  ...HTML_CONTRACT.globalAttributes,
  ...Object.values(HTML_CONTRACT.tagAttributes).flat(),
]));
const editorAllowedAttributes = Array.from(new Set([
  ...canonicalAllowedAttributes,
  ...Object.values(RICH_TEXT_CONTRACT.importOnly.tagAttributes).flat(),
]));

const canonicalPurifierConfig = {
  ALLOWED_ATTR: canonicalAllowedAttributes,
  ALLOWED_TAGS: HTML_CONTRACT.tags,
  ALLOW_ARIA_ATTR: false,
  ALLOW_DATA_ATTR: false,
  ALLOW_UNKNOWN_PROTOCOLS: false,
  KEEP_CONTENT: true,
  RETURN_DOM_FRAGMENT: true,
  SANITIZE_DOM: true,
};

const hasControlCharacter = (value) => Array.from(value).some((character) => {
  const codePoint = character.codePointAt(0);
  return codePoint < 0x20 || codePoint === 0x7f;
});

const hasUnsafeUrlCharacters = (value) => Array.from(value).some((character) => (
  hasControlCharacter(character) || character === "\\" || /\s/u.test(character)
));

const safeText = (value, maximum) => (
  typeof value === "string"
  && value.length > 0
  && value.length <= maximum
  && !hasControlCharacter(value)
    ? value
    : null
);

const normalizeUploadUrl = (rawValue) => {
  if (
    typeof rawValue !== "string"
    || !rawValue
    || rawValue !== rawValue.trim()
    || rawValue.length > MAX_URL_LENGTH
    || hasUnsafeUrlCharacters(rawValue)
    || MALFORMED_PERCENT_ESCAPE_PATTERN.test(rawValue)
  ) {
    return null;
  }
  const match = rawValue.match(OBJECT_URL_PATTERN);
  if (!match || match[1] !== match[2].slice(0, 2)) {
    return null;
  }
  return `/api/uploads/objects/${match[1]}/${match[2]}${match[3]}`;
};

const normalizeLinkUrl = normalizeContractLinkUrl;

export const normalizeRichTextUrl = (rawValue, kind = "link") => (
  kind === "link" ? normalizeLinkUrl(rawValue) : normalizeUploadUrl(rawValue)
);

const escapeHtmlText = (value) => String(value || "")
  .replace(/&/g, "&amp;")
  .replace(/</g, "&lt;")
  .replace(/>/g, "&gt;");

const findLegacyTagEnd = (value, startIndex) => {
  let quote = null;
  for (let index = startIndex + 1; index < value.length; index += 1) {
    const character = value[index];
    if (quote) {
      if (character === quote) quote = null;
    } else if (character === '"' || character === "'") {
      quote = character;
    } else if (character === ">") {
      return index;
    }
  }
  return -1;
};

const getLegacyTagName = (candidate) => {
  const match = candidate.match(/^<\/?([A-Za-z]+)(?:\s|\/?>)/);
  return match ? match[1].toLowerCase() : null;
};

const recoverLegacyTagsFromText = (value) => {
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
    if (LEGACY_MEDIA_TAGS.has(getLegacyTagName(candidate))) {
      output += candidate;
      recovered = true;
    } else {
      output += escapeHtmlText(candidate);
    }
    cursor = tagEnd + 1;
  }
  return recovered ? output : null;
};

const parseInertFragment = (html) => {
  const template = document.createElement("template");
  template.innerHTML = html;
  return template.content;
};

const isForeignElement = (element) => (
  element.namespaceURI !== null
  && element.namespaceURI !== "http://www.w3.org/1999/xhtml"
);

const dropDangerousSubtrees = (root) => {
  Array.from(root.querySelectorAll("*")).forEach((element) => {
    if (!element.parentNode) return;
    if (isForeignElement(element) || DANGEROUS_SUBTREE_TAGS.has(element.localName)) {
      element.remove();
    }
  });
};

const recoverLegacyEscapedMedia = (root, recoveryBudget) => {
  const textNodes = [];
  const walker = document.createTreeWalker(root, NodeFilter.SHOW_TEXT);
  while (walker.nextNode()) textNodes.push(walker.currentNode);

  textNodes.forEach((textNode) => {
    if (recoveryBudget.remaining <= 0 || !textNode.parentNode) return;
    if (textNode.parentElement?.closest("pre, code")) return;
    const recoveredHtml = recoverLegacyTagsFromText(textNode.nodeValue || "");
    if (!recoveredHtml) return;
    const recovered = parseInertFragment(recoveredHtml);
    dropDangerousSubtrees(recovered);
    textNode.replaceWith(recovered);
    recoveryBudget.remaining -= 1;
  });
};

const classNames = (element) => new Set((element.getAttribute("class") || "").split(/\s+/).filter(Boolean));

const ensureClass = (element, className) => {
  const classes = classNames(element);
  classes.add(className);
  element.setAttribute("class", Array.from(classes).join(" "));
};

const firstDescendantAttribute = (element, names, normalizer) => {
  for (const descendant of element.querySelectorAll("*")) {
    for (const name of names) {
      const normalized = normalizer(descendant.getAttribute(name));
      if (normalized !== null) return normalized;
    }
  }
  return null;
};

const normalizePdfType = (value) => {
  const normalized = typeof value === "string" ? value.toLowerCase() : "";
  return PDF_TYPES.has(normalized) ? normalized : null;
};

const normalizeVideoType = (value) => {
  const normalized = typeof value === "string" ? value.toLowerCase() : "";
  return VIDEO_MIME_TYPES.has(normalized) ? normalized : null;
};

const normalizePdfPlaceholders = (root) => {
  root.querySelectorAll('div[data-inline-pdf-viewer="true"]').forEach((element) => {
    const url = normalizeUploadUrl(element.getAttribute("data-pdf-url"));
    if (!url) return;
    ensureClass(element, "file-attachment");
    element.setAttribute("data-file-url", url);
    const title = safeText(element.getAttribute("data-pdf-title"), 255);
    if (title) element.setAttribute("data-file-name", title);
    element.setAttribute("data-file-type", "pdf");
  });
};

const hoistAttachmentMetadata = (root) => {
  normalizePdfPlaceholders(root);
  root.querySelectorAll("div.file-attachment").forEach((element) => {
    const url = normalizeUploadUrl(element.getAttribute("data-file-url"))
      || firstDescendantAttribute(element, ["data-file-url", "data-pdf-url"], normalizeUploadUrl);
    if (url) element.setAttribute("data-file-url", url);

    const name = safeText(element.getAttribute("data-file-name"), 255)
      || firstDescendantAttribute(
        element,
        ["data-file-name", "data-pdf-title"],
        (value) => safeText(value, 255),
      );
    if (name) element.setAttribute("data-file-name", name);

    const size = safeText(element.getAttribute("data-file-size"), 64)
      || firstDescendantAttribute(
        element,
        ["data-file-size"],
        (value) => safeText(value, 64),
      );
    if (size) element.setAttribute("data-file-size", size);

    const fileType = normalizePdfType(element.getAttribute("data-file-type"))
      || firstDescendantAttribute(element, ["data-file-type"], normalizePdfType);
    if (fileType) element.setAttribute("data-file-type", fileType);
  });
};

const hoistVideoMetadata = (root) => {
  root.querySelectorAll("figure.video-container").forEach((figure) => {
    let video = figure.querySelector("video");
    let source = video?.querySelector("source") || null;
    const directUrl = normalizeUploadUrl(video?.getAttribute("src"));
    const sourceUrl = normalizeUploadUrl(source?.getAttribute("src"));
    const fallbackUrl = firstDescendantAttribute(figure, ["data-video-url"], normalizeUploadUrl);
    const selectedUrl = directUrl || sourceUrl || fallbackUrl;
    if (!selectedUrl) return;

    if (!video) {
      video = document.createElement("video");
      video.setAttribute("controls", "");
      figure.appendChild(video);
    }
    if (directUrl) {
      video.setAttribute("src", directUrl);
      return;
    }
    if (!source) {
      source = document.createElement("source");
      video.appendChild(source);
    }
    source.setAttribute("src", selectedUrl);
    const sourceType = normalizeVideoType(source.getAttribute("type"))
      || firstDescendantAttribute(figure, ["data-video-type"], normalizeVideoType);
    if (sourceType) source.setAttribute("type", sourceType);
  });
};

const normalizeVideoSources = (root) => {
  root.querySelectorAll("video").forEach((video) => {
    const directUrl = normalizeUploadUrl(video.getAttribute("src"));
    const sources = Array.from(video.querySelectorAll("source"));
    const candidates = sources.map((source) => ({
      source,
      type: normalizeVideoType(source.getAttribute("type")),
      url: normalizeUploadUrl(source.getAttribute("src")),
    }));
    const typed = candidates.find(({ type, url }) => type && url);
    const untyped = candidates.find(({ url }) => url);

    sources.forEach((source) => source.remove());
    video.removeAttribute("src");
    if (directUrl) {
      video.setAttribute("src", directUrl);
      return;
    }
    if (typed) {
      const source = document.createElement("source");
      source.setAttribute("src", typed.url);
      source.setAttribute("type", typed.type);
      video.appendChild(source);
      return;
    }
    if (untyped) video.setAttribute("src", untyped.url);
  });
};

const appendStyle = (element, property, value) => {
  if (!value) return;
  element.style.setProperty(property, value);
};

const replaceTag = (element, tagName) => {
  const replacement = document.createElement(tagName);
  Array.from(element.attributes).forEach(({ name, value }) => replacement.setAttribute(name, value));
  replacement.append(...element.childNodes);
  element.replaceWith(replacement);
  return replacement;
};

const convertImportAliases = (root) => {
  Array.from(root.querySelectorAll("*")).forEach((candidate) => {
    if (!candidate.parentNode) return;
    const tag = candidate.localName;
    if (ALIAS_TAGS.has(tag)) {
      replaceTag(candidate, ALIAS_TAGS.get(tag));
      return;
    }
    if (tag === "font" && IMPORT_TAGS.has(tag)) {
      const color = candidate.getAttribute("color");
      const family = candidate.getAttribute("face") || candidate.getAttribute("data-font-family");
      const size = candidate.getAttribute("size");
      const normalizedSize = POINT_TO_PIXEL.get((size || "").toLowerCase())
        || HTML_FONT_SIZE_TO_PIXEL.get(size)
        || (CANONICAL_PIXEL_SIZES.has(size) ? size : null);
      const element = replaceTag(candidate, "span");
      Array.from(element.attributes).forEach(({ name }) => {
        if (!HTML_CONTRACT.globalAttributes.includes(name)) element.removeAttribute(name);
      });
      appendStyle(element, "color", color);
      appendStyle(element, "font-family", family);
      appendStyle(element, "font-size", normalizedSize);
      return;
    }
    if (tag === "div") {
      const alignment = (candidate.getAttribute("align") || "").toLowerCase();
      if (CSS_KEYWORDS["text-align"].has(alignment)) {
        appendStyle(candidate, "text-align", alignment);
      }
    }
    if (tag === "span" && candidate.hasAttribute("data-font-family")) {
      appendStyle(candidate, "font-family", candidate.getAttribute("data-font-family"));
    }
  });
};

const isEditorControlElement = (element) => {
  const classes = classNames(element);
  if (element.localName === "button" && IMPORT_TAGS.has("button")) {
    return classes.has("remove-btn") || classes.has("video-delete-btn");
  }
  if (element.localName !== "div") return false;
  if (classes.has("file-actions")) {
    return Boolean(element.closest("div.file-attachment"));
  }
  if (classes.has("video-delete-overlay") || classes.has("editor-only-control")) {
    return Boolean(element.closest("figure.video-container"));
  }
  return false;
};

const dropControlSubtrees = (root, mode) => {
  Array.from(root.querySelectorAll("*")).forEach((element) => {
    if (!element.parentNode) return;
    const classes = classNames(element);
    const isControl = element.localName === "button"
      || Array.from(classes).some((className) => CONTROL_SUBTREE_CLASSES.has(className));
    if (!isControl) return;
    if (mode === "editor" && IMPORT_TAGS.has("button") && isEditorControlElement(element)) return;
    element.remove();
  });
};

const unwrapUnsupportedElements = (root, mode) => {
  const allowedTags = mode === "editor"
    ? new Set([...CANONICAL_TAGS, ...["button"].filter((tag) => IMPORT_TAGS.has(tag))])
    : CANONICAL_TAGS;
  Array.from(root.querySelectorAll("*")).reverse().forEach((element) => {
    if (!element.parentNode || allowedTags.has(element.localName)) return;
    element.replaceWith(...element.childNodes);
  });
};

const removeOrphanSources = (root) => {
  root.querySelectorAll("source").forEach((source) => {
    if (source.parentElement?.localName !== "video") source.remove();
  });
};

const formatNumber = (value) => {
  if (Object.is(value, -0) || value === 0) return "0";
  return Number(value.toFixed(6)).toString();
};

const normalizeColor = normalizeImportedColor;

const normalizeFontFamily = (value) => {
  if (
    !value
    || value.length > MAX_CSS_VALUE_LENGTH
    || value.includes("\\")
    || /(?:url\(|expression|@import|;)/i.test(value)
  ) {
    return null;
  }
  const families = value.split(",").map((family) => family.trim());
  if (!families.length || families.some((family) => !FONT_FAMILY_ITEM_PATTERN.test(family))) {
    return null;
  }
  return families.join(", ");
};

const normalizeLengthToken = (value, limits, keywords = new Set()) => {
  const normalized = value.trim().toLowerCase();
  if (keywords.has(normalized)) return normalized;
  const match = normalized.match(LENGTH_PATTERN);
  if (!match) return null;
  const amount = Number(match[1]);
  const unit = (match[2] || "").toLowerCase();
  if (!Number.isFinite(amount)) return null;
  if (!unit) {
    const pixelLimits = limits.px;
    return amount === 0 && pixelLimits && pixelLimits[0] <= 0 && pixelLimits[1] >= 0
      ? "0px"
      : null;
  }
  const [minimum, maximum] = limits[unit] || [1, 0];
  if (amount < minimum || amount > maximum) return null;
  return `${formatNumber(amount)}${unit}`;
};

const normalizeCssValue = (property, value) => {
  if (
    !value
    || value.length > MAX_CSS_VALUE_LENGTH
    || value.includes("\\")
    || hasControlCharacter(value)
    || /(?:expression\(|url\(|@import)/i.test(value)
  ) {
    return null;
  }
  if (["background-color", "color"].includes(property)) return normalizeColor(value);
  if (property === "font-family") return normalizeFontFamily(value);
  if (CSS_KEYWORDS[property]) {
    const normalized = value.trim().toLowerCase();
    return CSS_KEYWORDS[property].has(normalized) ? normalized : null;
  }
  if (property === "font-size") {
    const normalized = value.trim().toLowerCase();
    if (normalized.endsWith("pt")) return POINT_TO_PIXEL.get(normalized) || null;
    return normalizeLengthToken(
      normalized,
      { px: [8, 96], "%": [50, 400], em: [0.5, 6], rem: [0.5, 6] },
      new Set(["large", "larger", "medium", "small", "smaller", "x-large", "x-small", "xx-large", "xx-small"]),
    );
  }
  if (["height", "max-height", "max-width", "width"].includes(property)) {
    return normalizeLengthToken(
      value,
      { px: [0, 4096], "%": [0, 100], em: [0, 256], rem: [0, 256] },
      new Set(["auto", "none"]),
    );
  }
  if (property === "border-radius") {
    const tokens = value.trim().split(/\s+/);
    if (tokens.length < 1 || tokens.length > 4) return null;
    const normalized = tokens.map((token) => normalizeLengthToken(
      token,
      { px: [0, 512], "%": [0, 100], em: [0, 64], rem: [0, 64] },
    ));
    return normalized.some((token) => token === null) ? null : normalized.join(" ");
  }
  if (property === "margin" || property.startsWith("margin-")) {
    const tokens = value.trim().split(/\s+/);
    if (tokens.length < 1 || tokens.length > 4) return null;
    const normalized = tokens.map((token) => normalizeLengthToken(
      token,
      { px: [-512, 512], "%": [-100, 100], em: [-64, 64], rem: [-64, 64] },
      new Set(["auto"]),
    ));
    return normalized.some((token) => token === null) ? null : normalized.join(" ");
  }
  return null;
};

const normalizeStyle = (element) => {
  if (!element.hasAttribute("style")) return null;
  const accepted = new Map();
  const rawDeclarations = element.getAttribute("style").replace(/\/\*[\s\S]*?\*\//g, "").split(";");
  rawDeclarations.forEach((declaration) => {
    const separator = declaration.indexOf(":");
    if (separator < 0) return;
    const property = declaration.slice(0, separator).trim().toLowerCase();
    if (!STYLE_PROPERTIES.has(property)) return;
    const rawValue = declaration.slice(separator + 1);
    const important = /\s*!important\s*$/i.test(rawValue);
    const value = rawValue.replace(/\s*!important\s*$/i, "").trim();
    const normalized = normalizeCssValue(property, value);
    const previous = accepted.get(property);
    if (normalized === null || (previous?.important && !important)) return;
    accepted.set(property, { important, value: normalized });
  });
  if (!accepted.size) return null;
  return `${Array.from(accepted, ([property, { value }]) => `${property}: ${value}`).join("; ")};`;
};

const isCanonicalClass = (className) => {
  if (CANONICAL_CLASSES.has(className)) return true;
  const prefix = CLASS_PREFIXES.find((candidate) => className.startsWith(candidate));
  return Boolean(prefix && CLASS_SUFFIX_PATTERN.test(className.slice(prefix.length)));
};

const editorImportClasses = (element, originalClasses) => {
  const accepted = [];
  if (
    originalClasses.has("mceNonEditable")
    && ((element.localName === "div" && originalClasses.has("file-attachment"))
      || (element.localName === "figure" && originalClasses.has("video-container")))
  ) {
    accepted.push("mceNonEditable");
  }
  if (element.localName === "div" && element.closest("div.file-attachment")) {
    if (originalClasses.has("file-actions")) accepted.push("file-actions");
  }
  if (element.localName === "div" && element.closest("figure.video-container")) {
    if (originalClasses.has("video-delete-overlay")) accepted.push("video-delete-overlay");
    if (originalClasses.has("editor-only-control")) accepted.push("editor-only-control");
  }
  if (element.localName === "button") {
    if (originalClasses.has("remove-btn")) accepted.push("remove-btn");
    if (originalClasses.has("editor-only") && originalClasses.has("remove-btn")) {
      accepted.push("editor-only");
    }
    if (originalClasses.has("video-delete-btn")) accepted.push("video-delete-btn");
  }
  return accepted.filter((className) => IMPORT_CLASSES.has(className));
};

const normalizeClasses = (element, mode) => {
  const originalClasses = classNames(element);
  const accepted = Array.from(originalClasses).filter(isCanonicalClass);
  if (mode === "editor") accepted.push(...editorImportClasses(element, originalClasses));
  return Array.from(new Set(accepted)).join(" ") || null;
};

const normalizeDimension = (value) => {
  if (typeof value !== "string" || !value || value.length > 32 || value.startsWith("-")) {
    return null;
  }
  const normalized = value.trim().toLowerCase();
  if (/^\d+(?:\.\d+)?$/.test(normalized)) {
    const amount = Number(normalized);
    return amount <= 4096 ? formatNumber(amount) : null;
  }
  return normalizeLengthToken(
    normalized,
    { px: [0, 4096], "%": [0, 100], em: [0, 256], rem: [0, 256] },
    new Set(["auto"]),
  );
};

const normalizeSpan = (value) => {
  if (typeof value !== "string" || !/^\d{1,3}$/.test(value)) return null;
  const amount = Number(value);
  return amount >= 1 && amount <= 100 ? String(amount) : null;
};

const normalizeElementAttributes = (element, mode) => {
  const tag = element.localName;
  const original = Object.fromEntries(
    Array.from(element.attributes, ({ name, value }) => [name, value]),
  );
  const classes = normalizeClasses(element, mode);
  const style = tag === "button" ? null : normalizeStyle(element);
  Array.from(element.attributes).forEach(({ name }) => element.removeAttribute(name));
  if (classes) element.setAttribute("class", classes);
  if (style) element.setAttribute("style", style);

  if (tag === "a") {
    const href = normalizeLinkUrl(original.href);
    if (href) element.setAttribute("href", href);
    const title = safeText(original.title, 512);
    if (title) element.setAttribute("title", title);
    if (href && original.target === "_blank") {
      element.setAttribute("target", "_blank");
      element.setAttribute("rel", "noopener noreferrer");
    }
  } else if (tag === "div" && classes?.split(" ").includes("file-attachment")) {
    const url = normalizeUploadUrl(original["data-file-url"]);
    if (url) element.setAttribute("data-file-url", url);
    [["data-file-name", 255], ["data-file-size", 64]].forEach(([name, maximum]) => {
      const value = safeText(original[name], maximum);
      if (value) element.setAttribute(name, value);
    });
    const fileType = normalizePdfType(original["data-file-type"]);
    if (fileType) element.setAttribute("data-file-type", fileType);
  } else if (tag === "img") {
    const src = normalizeUploadUrl(original.src);
    if (src) element.setAttribute("src", src);
    ["alt", "title"].forEach((name) => {
      const value = safeText(original[name], 512);
      if (value) element.setAttribute(name, value);
    });
    ["height", "width"].forEach((name) => {
      const value = normalizeDimension(original[name]);
      if (value) element.setAttribute(name, value);
    });
  } else if (tag === "source") {
    const src = normalizeUploadUrl(original.src);
    if (src) element.setAttribute("src", src);
    const type = normalizeVideoType(original.type);
    if (type) element.setAttribute("type", type);
  } else if (tag === "video") {
    const src = normalizeUploadUrl(original.src);
    if (src) element.setAttribute("src", src);
    if (Object.hasOwn(original, "controls")) element.setAttribute("controls", "");
    if ((original.preload || "").toLowerCase() === "metadata") {
      element.setAttribute("preload", "metadata");
    }
    ["height", "width"].forEach((name) => {
      const value = normalizeDimension(original[name]);
      if (value) element.setAttribute(name, value);
    });
  } else if (tag === "td" || tag === "th") {
    ["colspan", "rowspan"].forEach((name) => {
      const value = normalizeSpan(original[name]);
      if (value) element.setAttribute(name, value);
    });
    if (tag === "th" && ["col", "colgroup", "row", "rowgroup"].includes((original.scope || "").toLowerCase())) {
      element.setAttribute("scope", original.scope.toLowerCase());
    }
  }

  if (mode !== "editor") return;
  if (
    original.contenteditable === "false"
    && ((tag === "div" && classes?.split(" ").includes("file-attachment"))
      || (tag === "figure" && classes?.split(" ").includes("video-container")))
  ) {
    element.setAttribute("contenteditable", "false");
  }
  if (tag === "button") {
    element.setAttribute("type", "button");
    if (classes?.split(" ").includes("remove-btn")) {
      const url = normalizeUploadUrl(original["data-file-url"]);
      if (url) element.setAttribute("data-file-url", url);
    }
    if (classes?.split(" ").includes("video-delete-btn")) {
      const url = normalizeUploadUrl(original["data-video-url"]);
      if (url) element.setAttribute("data-video-url", url);
    }
  }
};

const normalizeTree = (root, mode, recoveryBudget) => {
  dropDangerousSubtrees(root);
  recoverLegacyEscapedMedia(root, recoveryBudget);
  dropDangerousSubtrees(root);
  hoistAttachmentMetadata(root);
  hoistVideoMetadata(root);
  normalizeVideoSources(root);
  convertImportAliases(root);
  dropControlSubtrees(root, mode);
  unwrapUnsupportedElements(root, mode);
  removeOrphanSources(root);
  root.querySelectorAll("*").forEach((element) => normalizeElementAttributes(element, mode));
};

const buildSanitizedFragment = (html, { mode = "display" } = {}) => {
  const raw = typeof html === "string" ? html : String(html || "");
  if (raw.length > MAX_RICH_TEXT_INPUT_LENGTH) return document.createDocumentFragment();
  const canonicalMode = mode === "editor" ? "editor" : "display";
  try {
    const purifierConfig = {
      ...canonicalPurifierConfig,
      ALLOWED_ATTR: canonicalMode === "editor"
        ? editorAllowedAttributes
        : canonicalAllowedAttributes,
      ALLOWED_TAGS: canonicalMode === "editor"
        ? [...HTML_CONTRACT.tags, ...["button"].filter((tag) => IMPORT_TAGS.has(tag))]
        : HTML_CONTRACT.tags,
    };
    let current = raw;
    const recoveryBudget = { remaining: MAX_LEGACY_MEDIA_RECOVERIES };
    for (let pass = 0; pass < MAX_CANONICALIZATION_PASSES; pass += 1) {
      const fragment = parseInertFragment(current);
      normalizeTree(fragment, canonicalMode, recoveryBudget);
      const cleaned = DOMPurify.sanitize(fragment, purifierConfig);
      const container = document.createElement("div");
      container.appendChild(cleaned.cloneNode(true));
      const next = container.innerHTML;
      if (next === current) return cleaned;
      current = next;
    }
    return document.createDocumentFragment();
  } catch {
    return document.createDocumentFragment();
  }
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
