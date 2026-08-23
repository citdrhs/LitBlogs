import {
  FONT_FAMILIES,
  FONT_SIZES,
  HIGHLIGHT_COLOR_PALETTE,
  HTML_CONTRACT,
  PALETTE_RGB_ALIASES,
  TEXT_COLOR_PALETTE,
} from "../utils/richTextContract.js";

const MAX_URL_LENGTH = 2048;
const MAX_CSS_VALUE_LENGTH = 128;
const CANONICAL_UPLOAD_PATTERN = /^\/api\/uploads\/objects\/([0-9a-f]{2})\/([0-9a-f]{32})(\.[a-z0-9]{1,10})$/;
const MALFORMED_PERCENT_ESCAPE_PATTERN = /%(?![0-9a-f]{2})/i;
const FONT_FAMILY_ITEM_PATTERN = /^(?:"[^"\\\r\n]+"|'[^'\\\r\n]+'|[A-Za-z][A-Za-z0-9 _-]*)$/;
const LENGTH_PATTERN = /^(\d+(?:\.\d+)?|\.\d+)(px|%|em|rem)$/i;
const GLOBAL_CSS_VALUES = new Set(["inherit", "initial", "revert", "revert-layer", "unset"]);

const hasControlCharacters = (value) => Array.from(value).some((character) => {
  const codePoint = character.codePointAt(0);
  return codePoint < 0x20 || codePoint === 0x7f;
});

const paletteValues = {
  highlight: new Set(HIGHLIGHT_COLOR_PALETTE.map(({ value }) => value).filter(Boolean)),
  text: new Set(TEXT_COLOR_PALETTE.map(({ value }) => value)),
};

const normalizeRgbSyntax = (value) => {
  const match = value.match(
    /^rgba?\(\s*(\d{1,3})\s*,\s*(\d{1,3})\s*,\s*(\d{1,3})(?:\s*,\s*(1(?:\.0+)?))?\s*\)$/i,
  );
  if (!match) return null;
  const channels = match.slice(1, 4).map(Number);
  if (channels.some((channel) => channel > 255)) return null;
  return `rgb(${channels.join(", ")})`;
};

const formatNumber = (value) => {
  if (Object.is(value, -0) || value === 0) return "0";
  return Number(value.toFixed(6)).toString();
};

export const normalizePaletteColor = (rawValue, palette = "text") => {
  if (typeof rawValue !== "string" || !paletteValues[palette]) return null;
  const value = rawValue.trim().toLowerCase();
  const rgb = normalizeRgbSyntax(value);
  const canonical = rgb ? PALETTE_RGB_ALIASES[rgb] : value;
  return paletteValues[palette].has(canonical) ? canonical : null;
};

export const normalizeImportedColor = (rawValue) => {
  if (
    typeof rawValue !== "string"
    || !rawValue
    || rawValue.length > 64
    || rawValue.includes("\\")
    || hasControlCharacters(rawValue)
  ) {
    return null;
  }
  const normalized = rawValue.trim().toLowerCase();
  if (!normalized || GLOBAL_CSS_VALUES.has(normalized)) return null;
  const colorFunction = normalized.match(/^(rgb|rgba|hsl|hsla)\(([^)]*)\)$/);
  const expectedCommas = { rgb: 2, rgba: 3, hsl: 2, hsla: 3 };
  if (!(
    /^#[0-9a-f]{3,8}$/.test(normalized)
    || /^[a-z]+$/.test(normalized)
    || (colorFunction
      && (colorFunction[2].match(/,/g) || []).length === expectedCommas[colorFunction[1]])
  )) {
    return null;
  }

  const probe = document.createElement("span");
  probe.style.color = normalized;
  const parsed = probe.style.color.toLowerCase();
  if (!parsed) return null;
  if (/^[a-z]+$/.test(normalized)) {
    return parsed === normalized ? normalized : null;
  }

  const rgbMatch = parsed.match(
    /^rgba?\(\s*(\d+)\s*,\s*(\d+)\s*,\s*(\d+)(?:\s*,\s*([\d.]+))?\s*\)$/,
  );
  if (!rgbMatch) return null;
  let channels = rgbMatch.slice(1, 4).map(Number);
  let alpha = 1;
  const hexMatch = normalized.match(/^#([0-9a-f]{3,8})$/i);
  const alphaFunctionMatch = normalized.match(
    /^(?:rgba|hsla)\([^,]+,[^,]+,[^,]+,\s*([+-]?(?:\d+(?:\.\d+)?|\.\d+))\s*\)$/i,
  );
  if (hexMatch && [4, 8].includes(hexMatch[1].length)) {
    const alphaHex = hexMatch[1].length === 4
      ? `${hexMatch[1][3]}${hexMatch[1][3]}`
      : hexMatch[1].slice(6, 8);
    alpha = Number.parseInt(alphaHex, 16) / 255;
  } else if (alphaFunctionMatch) {
    alpha = Math.max(0, Math.min(1, Number(alphaFunctionMatch[1])));
  } else if (normalized === "transparent") {
    alpha = 0;
    channels = [0, 0, 0];
  } else if (rgbMatch[4] !== undefined) {
    alpha = Number(rgbMatch[4]);
  }
  if (alpha === 1) {
    const rgb = `rgb(${channels.join(", ")})`;
    return PALETTE_RGB_ALIASES[rgb] || rgb;
  }
  return `rgba(${channels.join(", ")}, ${formatNumber(alpha)})`;
};

const normalizeFontKey = (value) => value
  .trim()
  .replace(/'/g, '"')
  .replace(/\s*,\s*/g, ",")
  .replace(/\s+/g, " ")
  .toLowerCase();

const fontFamilyByKey = new Map(
  FONT_FAMILIES.map(({ cssValue }) => [normalizeFontKey(cssValue), cssValue]),
);

export const normalizeFontFamily = (rawValue) => {
  if (typeof rawValue !== "string") return null;
  return fontFamilyByKey.get(normalizeFontKey(rawValue)) ?? null;
};

export const normalizeImportedFontFamily = (rawValue) => {
  if (
    typeof rawValue !== "string"
    || !rawValue
    || rawValue.length > MAX_CSS_VALUE_LENGTH
    || rawValue.includes("\\")
    || hasControlCharacters(rawValue)
    || /(?:url\(|expression|@import|;)/i.test(rawValue)
  ) {
    return null;
  }
  const contractFamily = normalizeFontFamily(rawValue);
  if (contractFamily) return contractFamily;
  const families = rawValue.split(",").map((family) => family.trim());
  if (!families.length || families.some((family) => !FONT_FAMILY_ITEM_PATTERN.test(family))) {
    return null;
  }
  return families.join(", ");
};

const fontSizeByValue = new Map(FONT_SIZES.flatMap(({ legacyValue, cssValue }) => [
  [legacyValue.toLowerCase(), cssValue],
  [cssValue.toLowerCase(), cssValue],
]));

export const normalizeFontSize = (rawValue) => {
  if (typeof rawValue !== "string") return null;
  return fontSizeByValue.get(rawValue.trim().toLowerCase()) ?? null;
};

export const normalizeImportedFontSize = (rawValue) => {
  if (typeof rawValue !== "string") return null;
  const normalized = rawValue.trim().toLowerCase();
  const contractSize = normalizeFontSize(normalized);
  if (contractSize) return contractSize;
  if (normalized.endsWith("pt")) return null;
  const keywords = new Set([
    "large", "larger", "medium", "small", "smaller",
    "x-large", "x-small", "xx-large", "xx-small",
  ]);
  if (keywords.has(normalized)) return normalized;
  const match = normalized.match(LENGTH_PATTERN);
  if (!match) return null;
  const amount = Number(match[1]);
  const unit = match[2].toLowerCase();
  const limits = { px: [8, 96], "%": [50, 400], em: [0.5, 6], rem: [0.5, 6] };
  const [minimum, maximum] = limits[unit];
  return Number.isFinite(amount) && amount >= minimum && amount <= maximum
    ? `${formatNumber(amount)}${unit}`
    : null;
};

export const isCanonicalUploadUrl = (rawValue) => {
  if (typeof rawValue !== "string" || rawValue.length > MAX_URL_LENGTH) return false;
  const match = rawValue.match(CANONICAL_UPLOAD_PATTERN);
  return Boolean(match && match[1] === match[2].slice(0, 2));
};

const hasUnsafeUrlCharacters = (value) => (
  value.includes("\\")
  || Array.from(value).some((character) => {
    const codePoint = character.codePointAt(0);
    return codePoint <= 0x20 || codePoint === 0x7f || /\s/u.test(character);
  })
);

const browserBaseUrl = () => {
  try {
    return new URL(document.baseURI);
  } catch {
    return new URL("https://litblogs.invalid/");
  }
};

export const normalizeLinkUrl = (rawValue) => {
  if (typeof rawValue !== "string") return null;
  const value = rawValue.trim();
  if (
    !value
    || value !== rawValue
    || value.length > MAX_URL_LENGTH
    || value.startsWith("//")
    || hasUnsafeUrlCharacters(value)
    || MALFORMED_PERCENT_ESCAPE_PATTERN.test(value)
  ) {
    return null;
  }

  const rawPath = value.split(/[?#]/, 1)[0];
  let decodedPath;
  try {
    decodedPath = decodeURIComponent(rawPath);
  } catch {
    return null;
  }
  if (
    decodedPath === null
    || hasUnsafeUrlCharacters(decodedPath)
    || decodedPath.split("/").some((part) => part === "." || part === "..")
  ) {
    return null;
  }

  try {
    const base = browserBaseUrl();
    const parsed = new URL(value, base);
    if (parsed.username || parsed.password || !["http:", "https:"].includes(parsed.protocol)) {
      return null;
    }
    if (/^[a-z][a-z0-9+.-]*:/i.test(value) && parsed.protocol !== "https:") return null;
    if (parsed.origin !== base.origin && parsed.protocol !== "https:") return null;
    return value;
  } catch {
    return null;
  }
};

export const isExternalLink = (value) => {
  const normalized = normalizeLinkUrl(value);
  if (!normalized) return false;
  try {
    return new URL(normalized, browserBaseUrl()).origin !== browserBaseUrl().origin;
  } catch {
    return false;
  }
};

export const normalizeSafeText = (rawValue, maximum = 255) => {
  if (typeof rawValue !== "string") return null;
  const value = rawValue.trim();
  if (!value || value.length > maximum || hasControlCharacters(value)) return null;
  return value;
};

export const normalizeDimension = (rawValue) => {
  if (rawValue === null || rawValue === undefined || rawValue === "") return null;
  const value = String(rawValue).trim().toLowerCase();
  const match = value.match(/^(\d+(?:\.\d+)?)(px|%|em|rem)?$/);
  if (!match) return null;
  const amount = Number(match[1]);
  const maximums = { "": 4096, px: 4096, "%": 100, em: 256, rem: 256 };
  return Number.isFinite(amount) && amount <= maximums[match[2] || ""] ? value : null;
};

export const normalizeVideoMimeType = (rawValue) => {
  if (typeof rawValue !== "string") return null;
  const value = rawValue.trim().toLowerCase();
  return HTML_CONTRACT.videoMimeTypes.includes(value) ? value : null;
};

export const normalizePdfType = (rawValue) => {
  if (typeof rawValue !== "string") return null;
  const value = rawValue.trim().toLowerCase();
  return HTML_CONTRACT.pdfTypes.includes(value) ? "application/pdf" : null;
};

const imageClasses = new Set([
  "aligncenter",
  "alignleft",
  "alignright",
  "d-block",
  "float-left",
  "float-right",
  "img-fluid",
  "mx-auto",
  "post-image",
]);

export const normalizeImageClasses = (rawValue) => {
  if (typeof rawValue !== "string") return null;
  const classes = [...new Set(rawValue.split(/\s+/).filter((name) => imageClasses.has(name)))];
  return classes.length ? classes.join(" ") : null;
};

export const normalizeSpan = (rawValue, minimum = 1, maximum = 100) => {
  const value = Number.parseInt(String(rawValue ?? ""), 10);
  return Number.isInteger(value) && value >= minimum && value <= maximum ? value : 1;
};
