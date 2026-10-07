import { sanitizeRichText } from "./richTextSecurity.js";
import { MAX_POST_HTML_LENGTH } from "./postRequestContract.js";

export const assignmentContentFormat = (format) => (
  format === "rich" ? "rich" : "plain"
);

const escapeText = (value) => value
  .replaceAll("&", "&amp;")
  .replaceAll("<", "&lt;")
  .replaceAll(">", "&gt;")
  .replaceAll('"', "&quot;")
  .replaceAll("'", "&#39;");
const LEGACY_MEDIA_LITERAL = /<\/?(?:figure|source|video)(?=[\s/>])/i;

export const assignmentContentForEditor = (content, format) => {
  const value = typeof content === "string" ? content : "";
  if (assignmentContentFormat(format) === "rich") {
    return sanitizeRichText(value, { mode: "editor" });
  }
  if (!value) return "";
  return value.replaceAll("\r\n", "\n").split("\n")
    .map((line) => {
      const escaped = escapeText(line);
      // The shared sanitizer recovers legacy escaped media outside code/pre.
      // Keep literal tags from older plain responses as text during editing,
      // rendering, and the backend's own canonicalization.
      if (LEGACY_MEDIA_LITERAL.test(line)) return `<p><code>${escaped}</code></p>`;
      return `<p>${escaped || "<br>"}</p>`;
    })
    .join("");
};

export const assignmentContentForEditing = (content, format) => {
  const value = typeof content === "string" ? content : "";
  if (assignmentContentFormat(format) === "plain" && value.length > MAX_POST_HTML_LENGTH) {
    return { content: value, contentFormat: "plain" };
  }
  const editorContent = assignmentContentForEditor(value, format);
  if (assignmentContentFormat(format) === "plain" && editorContent.length > MAX_POST_HTML_LENGTH) {
    return { content: value, contentFormat: "plain" };
  }
  return { content: editorContent, contentFormat: "rich" };
};

export const hasAssignmentResponse = (html) => {
  if (typeof html !== "string" || !html.trim()) return false;
  const template = document.createElement("template");
  template.innerHTML = sanitizeRichText(html);
  return Boolean(
    template.content.textContent?.trim()
    || template.content.querySelector("img[src], video[src], .file-attachment[data-file-url]"),
  );
};
