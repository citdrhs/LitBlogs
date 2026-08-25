import axios from "axios";

import { isCanonicalUploadUrl } from "./editorContract.js";

const MEBIBYTE = 1024 * 1024;
const MAX_DATA_IMAGE_SIZE = 10 * MEBIBYTE;
const MAX_DATA_IMAGE_ENCODED_LENGTH = Math.ceil(MAX_DATA_IMAGE_SIZE / 3) * 4;
const MAX_DATA_IMAGE_HTML_LENGTH = MAX_DATA_IMAGE_ENCODED_LENGTH + (64 * 1024);
const DATA_IMAGE_EXTENSIONS = Object.freeze({
  "image/bmp": "bmp",
  "image/gif": "gif",
  "image/jpeg": "jpg",
  "image/png": "png",
  "image/webp": "webp",
});
const DANGEROUS_DATA_IMAGE_CONTAINERS = new Set([
  "base", "embed", "form", "head", "iframe", "link", "math", "meta",
  "noscript", "object", "script", "style", "svg", "template",
]);
const STRICT_BASE64_PATTERN = /^(?:[A-Za-z0-9+/]{4})*(?:[A-Za-z0-9+/]{2}==|[A-Za-z0-9+/]{3}=)?$/;
const hasUnsafeFileNameCharacter = (name) => Array.from(name).some((character) => {
  const codePoint = character.codePointAt(0);
  return codePoint < 0x20 || codePoint === 0x7f || character === "\\" || character === "/";
});

const UPLOAD_RULES = Object.freeze({
  image: Object.freeze({
    endpoint: "/upload/image",
    maximumSize: 10 * MEBIBYTE,
    typesByExtension: Object.freeze({
      bmp: Object.freeze(["image/bmp"]),
      gif: Object.freeze(["image/gif"]),
      jpeg: Object.freeze(["image/jpeg"]),
      jpg: Object.freeze(["image/jpeg"]),
      png: Object.freeze(["image/png"]),
      webp: Object.freeze(["image/webp"]),
    }),
  }),
  pdf: Object.freeze({
    endpoint: "/upload/file",
    maximumSize: 25 * MEBIBYTE,
    typesByExtension: Object.freeze({
      pdf: Object.freeze(["application/pdf"]),
    }),
  }),
  video: Object.freeze({
    endpoint: "/upload/video",
    maximumSize: 100 * MEBIBYTE,
    typesByExtension: Object.freeze({
      avi: Object.freeze(["video/x-msvideo"]),
      m4v: Object.freeze(["video/mp4", "video/x-m4v"]),
      mkv: Object.freeze(["video/x-matroska"]),
      mp4: Object.freeze(["video/mp4"]),
      ogg: Object.freeze(["video/ogg"]),
      webm: Object.freeze(["video/webm"]),
    }),
  }),
});

const invalidAsset = (message) => new Error(message);

const fileExtension = (name) => {
  const match = name.toLowerCase().match(/\.([a-z0-9]+)$/);
  return match?.[1] ?? null;
};

export const validateEditorAsset = ({ kind, file }) => {
  const rule = UPLOAD_RULES[kind];
  if (!rule) throw invalidAsset("Choose a supported upload type.");
  if (!(file instanceof Blob) || typeof file.name !== "string") {
    throw invalidAsset("Choose a valid file to upload.");
  }

  const name = file.name.trim();
  if (
    name !== file.name
    || name.length < 1
    || name.length > 255
    || hasUnsafeFileNameCharacter(name)
  ) {
    throw invalidAsset("Choose a file with a safe file name.");
  }

  const extension = fileExtension(name);
  const mediaType = typeof file.type === "string" ? file.type.trim().toLowerCase() : "";
  if (!extension || !rule.typesByExtension[extension]?.includes(mediaType)) {
    throw invalidAsset("Choose a supported file type.");
  }
  if (!Number.isSafeInteger(file.size) || file.size < 1) {
    throw invalidAsset("The selected file is empty or invalid.");
  }
  if (file.size > rule.maximumSize) {
    throw invalidAsset("The selected file is too large.");
  }

  return Object.freeze({
    endpoint: rule.endpoint,
    kind,
    mimeType: mediaType,
    name,
    size: file.size,
  });
};

const progressHandler = (onProgress) => {
  if (typeof onProgress !== "function") return undefined;
  return ({ loaded, total }) => {
    if (!Number.isFinite(loaded) || !Number.isFinite(total) || total <= 0) return;
    const percent = Math.max(0, Math.min(100, (loaded / total) * 100));
    onProgress(percent);
  };
};

export const uploadEditorAsset = async ({ kind, file, onProgress, signal } = {}) => {
  const validated = validateEditorAsset({ kind, file });
  const body = new FormData();
  body.append("file", file);

  try {
    const response = await axios.post(validated.endpoint, body, {
      onUploadProgress: progressHandler(onProgress),
      signal,
    });
    const url = response?.data?.url;
    if (!isCanonicalUploadUrl(url)) {
      throw invalidAsset("The server returned an invalid upload response.");
    }
    return Object.freeze({
      kind: validated.kind,
      mimeType: validated.mimeType,
      name: validated.name,
      size: validated.size,
      url,
    });
  } catch (error) {
    if (error?.message === "The server returned an invalid upload response.") throw error;
    if (error?.name === "AbortError" || error?.code === "ERR_CANCELED") throw error;
    throw invalidAsset("Upload failed. Please try again.");
  }
};

export const editorAssetKind = (file) => {
  for (const kind of ["image", "video", "pdf"]) {
    try {
      validateEditorAsset({ kind, file });
      return kind;
    } catch {
      // A dropped file is classified only when it satisfies one complete backend rule.
    }
  }
  return null;
};

export const extractEditorDataImages = (html) => {
  if (typeof html !== "string" || !/data:image\//i.test(html)) {
    return { files: [], rejected: false };
  }
  if (html.length > MAX_DATA_IMAGE_HTML_LENGTH) {
    return { files: [], rejected: true };
  }

  const template = document.createElement("template");
  template.innerHTML = html;
  for (const element of template.content.querySelectorAll("*")) {
    const foreignElement = element.namespaceURI !== null
      && element.namespaceURI !== "http://www.w3.org/1999/xhtml";
    if (foreignElement || DANGEROUS_DATA_IMAGE_CONTAINERS.has(element.localName)) {
      element.remove();
    }
  }

  const files = [];
  let rejected = false;
  for (const image of template.content.querySelectorAll("img[src]")) {
    const source = (image.getAttribute("src") || "").trim();
    if (!/^data:image\//i.test(source)) continue;

    const dataMatch = source.match(/^data:([^;,]+);base64,([A-Za-z0-9+/=]*)$/i);
    const mimeType = dataMatch?.[1]?.toLowerCase();
    const encoded = dataMatch?.[2] ?? "";
    const extension = DATA_IMAGE_EXTENSIONS[mimeType];
    if (
      !extension
      || !encoded
      || encoded.length > MAX_DATA_IMAGE_ENCODED_LENGTH
      || encoded.length % 4 !== 0
      || !STRICT_BASE64_PATTERN.test(encoded)
    ) {
      rejected = true;
      continue;
    }

    try {
      const decoded = atob(encoded);
      if (!decoded.length || decoded.length > MAX_DATA_IMAGE_SIZE) {
        rejected = true;
        continue;
      }
      const bytes = Uint8Array.from(decoded, (character) => character.charCodeAt(0));
      const suffix = files.length ? `-${files.length + 1}` : "";
      const file = new File([bytes], `pasted-image${suffix}.${extension}`, { type: mimeType });
      validateEditorAsset({ kind: "image", file });
      files.push(file);
    } catch {
      rejected = true;
    }
  }
  return { files, rejected };
};

export const formatEditorAssetSize = (bytes) => {
  if (!Number.isFinite(bytes) || bytes <= 0) return "0 bytes";
  if (bytes === 1) return "1 byte";
  if (bytes < 1024) return `${Math.round(bytes)} bytes`;
  const units = ["KB", "MB", "GB"];
  let amount = bytes / 1024;
  let unitIndex = 0;
  while (amount >= 1024 && unitIndex < units.length - 1) {
    amount /= 1024;
    unitIndex += 1;
  }
  return `${Number(amount.toFixed(1))} ${units[unitIndex]}`;
};

export const insertEditorAsset = (editor, asset) => {
  if (!editor?.chain || !isCanonicalUploadUrl(asset?.url)) return false;
  let command;
  let attributes;
  if (asset.kind === "image") {
    command = "setImage";
    attributes = { alt: asset.name, class: "img-fluid", src: asset.url };
  } else if (asset.kind === "video") {
    command = "setVideo";
    attributes = { src: asset.url, type: asset.mimeType };
  } else if (asset.kind === "pdf") {
    command = "setAttachment";
    attributes = {
      name: asset.name,
      size: formatEditorAssetSize(asset.size),
      type: "application/pdf",
      url: asset.url,
    };
  } else {
    return false;
  }
  const focused = editor.chain().focus();
  if (typeof focused[command] !== "function") return false;
  return Boolean(focused[command](attributes).run());
};

export const createEditorAssetPreview = (
  file,
  {
    createObjectURL = URL.createObjectURL.bind(URL),
    revokeObjectURL = URL.revokeObjectURL.bind(URL),
  } = {},
) => {
  if (!(file instanceof Blob)) throw invalidAsset("Choose a valid file to preview.");
  const url = createObjectURL(file);
  let disposed = false;
  return Object.freeze({
    dispose: () => {
      if (disposed) return;
      disposed = true;
      revokeObjectURL(url);
    },
    url,
  });
};

export const EDITOR_UPLOAD_ACCEPT = Object.freeze({
  image: ".jpg,.jpeg,.png,.gif,.webp,.bmp,image/jpeg,image/png,image/gif,image/webp,image/bmp",
  pdf: ".pdf,application/pdf",
  video: ".mp4,.m4v,.webm,.mkv,.ogg,.avi,video/mp4,video/x-m4v,video/webm,video/x-matroska,video/ogg,video/x-msvideo",
});
