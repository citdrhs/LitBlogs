import { API_BASE_PATH } from "./urlUtils.js";

export const MAX_POST_HTML_LENGTH = 100000;

const CANONICAL_UPLOAD_KEY = /^objects\/[0-9a-f]{2}\/[0-9a-f]{32}\.[a-z0-9]{1,10}$/;

const canonicalUploadUrl = (value, apiBasePath) => {
  if (typeof value !== "string") {
    return value;
  }

  const displayPrefix = `${String(apiBasePath || "/api").replace(/\/$/, "")}/uploads/`;
  if (!value.startsWith(displayPrefix)) {
    return value;
  }

  const storageKey = value.slice(displayPrefix.length);
  if (!CANONICAL_UPLOAD_KEY.test(storageKey)) {
    return value;
  }

  const [, prefix, objectId] = storageKey.match(
    /^objects\/([0-9a-f]{2})\/([0-9a-f]{32})/,
  ) || [];
  return prefix === objectId?.slice(0, 2)
    ? `/api/uploads/${storageKey}`
    : value;
};

export const canonicalizePostUploadReferences = (
  content,
  apiBasePath = API_BASE_PATH,
) => {
  if (typeof content !== "string" || !content) {
    return content;
  }

  const template = document.createElement("template");
  template.innerHTML = content;
  const references = [
    ["img[src], video[src], source[src]", "src"],
    ["[data-file-url]", "data-file-url"],
    ["[data-video-url]", "data-video-url"],
    ["a.file-attachment[href]", "href"],
  ];

  references.forEach(([selector, attribute]) => {
    template.content.querySelectorAll(selector).forEach((element) => {
      const current = element.getAttribute(attribute);
      const canonical = canonicalUploadUrl(current, apiBasePath);
      if (canonical !== current) {
        element.setAttribute(attribute, canonical);
      }
    });
  });

  return template.innerHTML;
};

export const buildPostRequestPayload = ({
  title,
  content,
  postContent,
  apiBasePath = API_BASE_PATH,
}) => {
  const media = Array.isArray(postContent?.media)
    ? postContent.media.map(({ type, url, alt }) => ({
      type,
      url: canonicalUploadUrl(url, apiBasePath),
      ...(alt ? { alt } : {}),
    }))
    : [];
  const files = Array.isArray(postContent?.files)
    ? postContent.files.map(({ name, url }) => ({
      name,
      url: canonicalUploadUrl(url, apiBasePath),
    }))
    : [];
  const codeSnippets = Array.isArray(postContent?.codeSnippets)
    ? postContent.codeSnippets.map(({ language, code }) => ({ language, code }))
    : [];

  return {
    title,
    content: canonicalizePostUploadReferences(content, apiBasePath),
    ...(media.length ? { media } : {}),
    ...(files.length ? { files } : {}),
    ...(codeSnippets.length ? { code_snippets: codeSnippets } : {}),
  };
};
