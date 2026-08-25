import { Node } from "@tiptap/core";
import { ReactNodeViewRenderer } from "@tiptap/react";

import EditorAttachmentNodeView from "../components/EditorAttachmentNodeView.jsx";
import EditorImageNodeView from "../components/EditorImageNodeView.jsx";
import EditorVideoNodeView from "../components/EditorVideoNodeView.jsx";
import {
  isCanonicalUploadUrl,
  normalizeDimension,
  normalizeImageClasses,
  normalizePdfType,
  normalizeSafeText,
  normalizeVideoMimeType,
} from "./editorContract.js";

const hiddenAttribute = (defaultValue = null) => ({
  default: defaultValue,
  parseHTML: () => null,
  rendered: false,
});

const imageAttributes = (element) => {
  const src = element.getAttribute("src");
  if (!isCanonicalUploadUrl(src)) return false;
  return {
    src,
    alt: normalizeSafeText(element.getAttribute("alt"), 512),
    title: normalizeSafeText(element.getAttribute("title"), 512),
    width: normalizeDimension(element.getAttribute("width")),
    height: normalizeDimension(element.getAttribute("height")),
    class: normalizeImageClasses(element.getAttribute("class")),
  };
};

const normalizeImageOptions = (attributes) => {
  if (!isCanonicalUploadUrl(attributes?.src)) return null;
  return {
    src: attributes.src,
    alt: normalizeSafeText(attributes.alt, 512),
    title: normalizeSafeText(attributes.title, 512),
    width: normalizeDimension(attributes.width),
    height: normalizeDimension(attributes.height),
    class: normalizeImageClasses(attributes.class),
  };
};

export const CanonicalImage = Node.create({
  name: "image",
  group: "block",
  atom: true,
  draggable: true,

  addAttributes() {
    return {
      src: hiddenAttribute(),
      alt: hiddenAttribute(),
      title: hiddenAttribute(),
      width: hiddenAttribute(),
      height: hiddenAttribute(),
      class: hiddenAttribute(),
    };
  },

  addNodeView() {
    return ReactNodeViewRenderer(EditorImageNodeView);
  },

  parseHTML() {
    return [{ tag: "img[src]", getAttrs: imageAttributes }];
  },

  renderHTML({ node }) {
    const attributes = normalizeImageOptions(node.attrs);
    return attributes ? ["img", attributes] : ["div", {}];
  },

  addCommands() {
    return {
      setImage: (attributes) => ({ commands }) => {
        const normalized = normalizeImageOptions(attributes);
        return normalized
          ? commands.insertContent({ type: this.name, attrs: normalized })
          : false;
      },
    };
  },
});

const videoAttributes = (element) => {
  const video = element.matches("video") ? element : element.querySelector("video");
  const source = video?.querySelector("source[src]");
  const metadata = element.matches("[data-video-url]")
    ? element
    : element.querySelector("[data-video-url]");
  const src = source?.getAttribute("src")
    || video?.getAttribute("src")
    || element.getAttribute("data-video-url")
    || metadata?.getAttribute("data-video-url");
  const type = source?.getAttribute("type")
    || element.getAttribute("data-video-type")
    || metadata?.getAttribute("data-video-type");

  const normalizedType = type ? normalizeVideoMimeType(type) : null;
  if (!isCanonicalUploadUrl(src) || (source && !normalizedType) || (type && !normalizedType)) {
    return false;
  }
  return {
    src,
    type: normalizedType,
    width: normalizeDimension(video?.getAttribute("width")),
    height: normalizeDimension(video?.getAttribute("height")),
    preload: "metadata",
  };
};

const normalizeVideoOptions = (attributes) => {
  const rawType = attributes?.type;
  const type = rawType ? normalizeVideoMimeType(rawType) : null;
  if (!isCanonicalUploadUrl(attributes?.src) || (rawType && !type)) return null;
  return {
    src: attributes.src,
    type,
    width: normalizeDimension(attributes.width),
    height: normalizeDimension(attributes.height),
    preload: "metadata",
  };
};

export const Video = Node.create({
  name: "video",
  group: "block",
  atom: true,
  draggable: true,
  selectable: true,

  addAttributes() {
    return {
      src: hiddenAttribute(),
      type: hiddenAttribute(),
      width: hiddenAttribute(),
      height: hiddenAttribute(),
      preload: hiddenAttribute("metadata"),
    };
  },

  addNodeView() {
    return ReactNodeViewRenderer(EditorVideoNodeView);
  },

  parseHTML() {
    return [
      { tag: "figure.video-container", getAttrs: videoAttributes },
      { tag: "div.video-wrapper", getAttrs: videoAttributes },
      { tag: "div.video-data", getAttrs: videoAttributes },
      { tag: "div.video-placeholder", getAttrs: videoAttributes },
      { tag: "video", getAttrs: videoAttributes },
    ];
  },

  renderHTML({ node }) {
    const attributes = normalizeVideoOptions(node.attrs);
    if (!attributes) return ["div", {}];
    const videoAttributesForHtml = {
      controls: "",
      preload: "metadata",
      src: attributes.type ? null : attributes.src,
      width: attributes.width,
      height: attributes.height,
    };
    const video = attributes.type
      ? [
        "video",
        videoAttributesForHtml,
        ["source", { src: attributes.src, type: attributes.type }],
      ]
      : ["video", videoAttributesForHtml];
    return [
      "figure",
      { class: "video-container" },
      video,
    ];
  },

  addCommands() {
    return {
      setVideo: (attributes) => ({ commands }) => {
        const normalized = normalizeVideoOptions(attributes);
        return normalized
          ? commands.insertContent({ type: this.name, attrs: normalized })
          : false;
      },
    };
  },
});

const findAttachmentMetadata = (element, attribute) => (
  element.getAttribute(attribute)
  || element.querySelector(`[${attribute}]`)?.getAttribute(attribute)
);

const attachmentAttributes = (element) => {
  const url = findAttachmentMetadata(element, "data-file-url")
    || findAttachmentMetadata(element, "data-pdf-url")
    || element.getAttribute("href");
  const name = element.getAttribute("data-file-name")
    || element.getAttribute("data-pdf-title")
    || element.getAttribute("title")
    || element.querySelector(".file-name")?.textContent
    || element.textContent;
  const size = element.getAttribute("data-file-size")
    || element.querySelector(".file-size")?.textContent;
  const type = element.getAttribute("data-file-type") || "application/pdf";

  if (!isCanonicalUploadUrl(url) || !normalizePdfType(type) || !normalizeSafeText(name, 255)) {
    return false;
  }
  return {
    url,
    name: normalizeSafeText(name, 255),
    size: normalizeSafeText(size, 64),
    type: "application/pdf",
  };
};

const normalizeAttachmentOptions = (attributes) => {
  const url = attributes?.url ?? attributes?.src;
  const name = normalizeSafeText(attributes?.name, 255);
  const type = normalizePdfType(attributes?.type ?? "application/pdf");
  if (!isCanonicalUploadUrl(url) || !name || !type) return null;
  return {
    url,
    name,
    size: normalizeSafeText(attributes?.size, 64),
    type,
  };
};

export const Attachment = Node.create({
  name: "attachment",
  group: "block",
  atom: true,
  draggable: true,
  selectable: true,

  addAttributes() {
    return {
      url: hiddenAttribute(),
      name: hiddenAttribute(),
      size: hiddenAttribute(),
      type: hiddenAttribute("application/pdf"),
    };
  },

  addNodeView() {
    return ReactNodeViewRenderer(EditorAttachmentNodeView);
  },

  parseHTML() {
    return [
      { tag: "div.file-attachment", getAttrs: attachmentAttributes },
      { tag: "a.file-attachment[href]", priority: 100, getAttrs: attachmentAttributes },
      { tag: "div[data-inline-pdf-viewer]", getAttrs: attachmentAttributes },
      { tag: "div.file-placeholder", getAttrs: attachmentAttributes },
    ];
  },

  renderHTML({ node }) {
    const attributes = normalizeAttachmentOptions(node.attrs);
    if (!attributes) return ["div", {}];
    const info = ["span", { class: "file-info" }, [
      "span",
      { class: "file-name" },
      attributes.name,
    ]];
    if (attributes.size) {
      info.push(["span", { class: "file-size" }, attributes.size]);
    }
    return [
      "div",
      {
        class: "file-attachment",
        "data-file-url": attributes.url,
        "data-file-name": attributes.name,
        "data-file-size": attributes.size,
        "data-file-type": attributes.type,
      },
      ["span", { class: "file-icon" }, "PDF"],
      info,
    ];
  },

  addCommands() {
    return {
      setAttachment: (attributes) => ({ commands }) => {
        const normalized = normalizeAttachmentOptions(attributes);
        return normalized
          ? commands.insertContent({ type: this.name, attrs: normalized })
          : false;
      },
    };
  },
});
