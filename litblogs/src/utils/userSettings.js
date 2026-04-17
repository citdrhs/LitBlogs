export const SETTINGS_KEY = "litblogs_settings";

export const DEFAULT_USER_SETTINGS = {
  darkMode: false,
  reducedMotion: false,
  emailNotifications: true,
  assignmentReminders: true,
  autoPlayVideos: false,
  compactFeed: false,
  rememberDrafts: true,
  showProfileToClassmates: true,
  editorFontSize: "medium",
};

const EDITOR_FONT_SIZE_MAP = {
  small: 13,
  medium: 14,
  large: 16,
};

const normalizeRole = (role = "") => String(role || "").toUpperCase();

const normalizeEditorFontSize = (value) => {
  const normalized = String(value || "").toLowerCase();
  return Object.prototype.hasOwnProperty.call(EDITOR_FONT_SIZE_MAP, normalized)
    ? normalized
    : DEFAULT_USER_SETTINGS.editorFontSize;
};

export const normalizeUserSettings = (rawSettings = {}, role = "STUDENT") => {
  const normalizedRole = normalizeRole(role);
  const merged = {
    ...DEFAULT_USER_SETTINGS,
    ...(rawSettings || {}),
  };

  merged.darkMode = Boolean(merged.darkMode);
  merged.reducedMotion = Boolean(merged.reducedMotion);
  merged.emailNotifications = Boolean(merged.emailNotifications);
  merged.assignmentReminders = Boolean(merged.assignmentReminders);
  merged.autoPlayVideos = Boolean(merged.autoPlayVideos);
  merged.compactFeed = Boolean(merged.compactFeed);
  merged.rememberDrafts = Boolean(merged.rememberDrafts);
  merged.showProfileToClassmates = Boolean(merged.showProfileToClassmates);
  merged.editorFontSize = normalizeEditorFontSize(merged.editorFontSize);

  if (normalizedRole !== "STUDENT") {
    merged.showProfileToClassmates = false;
  }

  return merged;
};

export const getEditorFontSizePx = (fontSize) => {
  const normalized = normalizeEditorFontSize(fontSize);
  return EDITOR_FONT_SIZE_MAP[normalized];
};

export const getLocalUserSettings = (role = "STUDENT") => {
  if (typeof window === "undefined") {
    return normalizeUserSettings(DEFAULT_USER_SETTINGS, role);
  }

  const raw = localStorage.getItem(SETTINGS_KEY);
  if (!raw) {
    return normalizeUserSettings(DEFAULT_USER_SETTINGS, role);
  }

  try {
    return normalizeUserSettings(JSON.parse(raw), role);
  } catch {
    return normalizeUserSettings(DEFAULT_USER_SETTINGS, role);
  }
};

export const saveLocalUserSettings = (settings, role = "STUDENT") => {
  if (typeof window === "undefined") {
    return normalizeUserSettings(settings, role);
  }

  const normalized = normalizeUserSettings(settings, role);
  localStorage.setItem(SETTINGS_KEY, JSON.stringify(normalized));
  return normalized;
};

export const applyGlobalUserSettings = (settings) => {
  if (typeof document === "undefined") {
    return;
  }

  const normalized = normalizeUserSettings(settings);
  document.body.classList.toggle("compact-feed", normalized.compactFeed);
  document.documentElement.setAttribute("data-reduced-motion", normalized.reducedMotion ? "true" : "false");
  document.documentElement.style.setProperty("--editor-font-size", `${getEditorFontSizePx(normalized.editorFontSize)}px`);
};

export const shouldAutoPlayVideos = () => getLocalUserSettings().autoPlayVideos;

export const shouldRememberDrafts = () => getLocalUserSettings().rememberDrafts;
