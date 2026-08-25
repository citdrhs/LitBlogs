import axios from "axios";
import { beforeEach, describe, expect, it, vi } from "vitest";

import {
  createEditorAssetPreview,
  editorAssetKind,
  extractEditorDataImages,
  formatEditorAssetSize,
  insertEditorAsset,
  uploadEditorAsset,
  validateEditorAsset,
} from "./editorUploads.js";

vi.mock("axios", () => ({
  default: {
    post: vi.fn(),
  },
}));

const objectUrl = (hex, extension) => (
  `/api/uploads/objects/${hex.slice(0, 2)}/${hex}.${extension}`
);

const makeFile = ({
  name,
  size = 12,
  type,
}) => {
  const file = new File([new Uint8Array(Math.min(size, 12))], name, { type });
  Object.defineProperty(file, "size", { configurable: true, value: size });
  return file;
};

describe("editor asset uploads", () => {
  beforeEach(() => {
    axios.post.mockReset();
  });

  it.each([
    ["image", "diagram.png", "image/png", 10 * 1024 * 1024, "/upload/image", "png"],
    ["video", "lesson.webm", "video/webm", 100 * 1024 * 1024, "/upload/video", "webm"],
    ["pdf", "reading.pdf", "application/pdf", 25 * 1024 * 1024, "/upload/file", "pdf"],
  ])(
    "uploads a validated %s through its authenticated endpoint",
    async (kind, name, type, maximumSize, endpoint, extension) => {
      const file = makeFile({ name, type, size: maximumSize });
      const url = objectUrl("a".repeat(32), extension);
      const progress = vi.fn();
      const controller = new AbortController();
      axios.post.mockResolvedValue({ data: { url } });

      const result = await uploadEditorAsset({
        kind,
        file,
        onProgress: progress,
        signal: controller.signal,
      });

      expect(axios.post).toHaveBeenCalledTimes(1);
      const [requestPath, body, options] = axios.post.mock.calls[0];
      expect(requestPath).toBe(endpoint);
      expect(body).toBeInstanceOf(FormData);
      expect(body.get("file")).toBe(file);
      expect(options.signal).toBe(controller.signal);
      expect(options.headers).toBeUndefined();

      options.onUploadProgress({ loaded: maximumSize / 2, total: maximumSize });
      options.onUploadProgress({ loaded: maximumSize, total: maximumSize });
      expect(progress.mock.calls.map(([value]) => value)).toEqual([50, 100]);
      expect(result).toEqual({
        kind,
        mimeType: type,
        name,
        size: maximumSize,
        url,
      });
    },
  );

  it.each([
    ["image", "photo.jpg", "image/jpeg"],
    ["image", "photo.jpeg", "image/jpeg"],
    ["image", "photo.gif", "image/gif"],
    ["image", "photo.webp", "image/webp"],
    ["image", "photo.bmp", "image/bmp"],
    ["video", "clip.mp4", "video/mp4"],
    ["video", "clip.m4v", "video/x-m4v"],
    ["video", "clip.m4v", "video/mp4"],
    ["video", "clip.mkv", "video/x-matroska"],
    ["video", "clip.ogg", "video/ogg"],
    ["video", "clip.avi", "video/x-msvideo"],
  ])("accepts the backend-compatible %s type %s", (kind, name, type) => {
    expect(validateEditorAsset({ kind, file: makeFile({ name, type }) })).toMatchObject({
      mimeType: type,
      name,
    });
  });

  it.each([
    ["image", "photo.png", "image/jpeg", "type"],
    ["image", "photo.svg", "image/svg+xml", "type"],
    ["video", "clip.mov", "video/quicktime", "type"],
    ["pdf", "reading.txt", "application/pdf", "type"],
    ["pdf", "reading.pdf", "text/plain", "type"],
    ["image", "bad\nname.png", "image/png", "name"],
  ])("rejects an invalid %s file before any request", async (kind, name, type, reason) => {
    const file = makeFile({ name, type });

    expect(() => validateEditorAsset({ kind, file })).toThrow(
      reason === "name" ? "safe file name" : "supported file type",
    );
    await expect(uploadEditorAsset({ kind, file })).rejects.toThrow(
      reason === "name" ? "safe file name" : "supported file type",
    );
    expect(axios.post).not.toHaveBeenCalled();
  });

  it.each([
    ["image", "large.png", "image/png", (10 * 1024 * 1024) + 1],
    ["video", "large.mp4", "video/mp4", (100 * 1024 * 1024) + 1],
    ["pdf", "large.pdf", "application/pdf", (25 * 1024 * 1024) + 1],
  ])("rejects an oversized %s before any request", async (kind, name, type, size) => {
    const file = makeFile({ name, type, size });
    await expect(uploadEditorAsset({ kind, file })).rejects.toThrow("too large");
    expect(axios.post).not.toHaveBeenCalled();
  });

  it("rejects malformed and remote server URLs", async () => {
    const file = makeFile({ name: "diagram.png", type: "image/png" });

    for (const url of [
      "https://tracker.example/diagram.png",
      "/api/uploads/objects/ff/aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa.png",
      "/api/uploads/objects/aa/aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa.png?download=1",
    ]) {
      axios.post.mockResolvedValueOnce({ data: { url } });
      await expect(uploadEditorAsset({ kind: "image", file })).rejects.toThrow(
        "invalid upload response",
      );
    }
  });

  it("uses a generic error and never includes server or file secrets", async () => {
    const file = makeFile({ name: "private-teacher-notes.pdf", type: "application/pdf" });
    axios.post.mockRejectedValue(new Error("database secret and /private/path leaked"));

    let thrown;
    try {
      await uploadEditorAsset({ kind: "pdf", file });
    } catch (error) {
      thrown = error;
    }

    expect(thrown?.message).toBe("Upload failed. Please try again.");
    expect(String(thrown)).not.toContain("private-teacher-notes");
    expect(String(thrown)).not.toContain("database secret");
  });

  it("ignores indeterminate progress and clamps determinate progress", async () => {
    const file = makeFile({ name: "diagram.png", type: "image/png" });
    const url = objectUrl("b".repeat(32), "png");
    const progress = vi.fn();
    axios.post.mockResolvedValue({ data: { url } });

    await uploadEditorAsset({ kind: "image", file, onProgress: progress });
    const { onUploadProgress } = axios.post.mock.calls[0][2];
    onUploadProgress({ loaded: 1 });
    onUploadProgress({ loaded: 30, total: 20 });
    onUploadProgress({ loaded: -1, total: 20 });

    expect(progress.mock.calls.map(([value]) => value)).toEqual([100, 0]);
  });

  it("creates an explicitly disposable local preview URL", () => {
    const file = makeFile({ name: "diagram.png", type: "image/png" });
    const createObjectURL = vi.fn(() => "blob:local-preview");
    const revokeObjectURL = vi.fn();

    const preview = createEditorAssetPreview(file, { createObjectURL, revokeObjectURL });
    expect(preview.url).toBe("blob:local-preview");
    preview.dispose();
    preview.dispose();

    expect(createObjectURL).toHaveBeenCalledWith(file);
    expect(revokeObjectURL).toHaveBeenCalledTimes(1);
    expect(revokeObjectURL).toHaveBeenCalledWith("blob:local-preview");
  });

  it.each([
    ["image/png", "png"],
    ["image/jpeg", "jpg"],
    ["image/gif", "gif"],
    ["image/webp", "webp"],
    ["image/bmp", "bmp"],
  ])("decodes a pasted base64 %s image into a validated local File", (type, extension) => {
    const { files, rejected } = extractEditorDataImages(
      `<p>Paste</p><img alt="Pasted" src="data:${type};base64,AQIDBA==">`,
    );

    expect(rejected).toBe(false);
    expect(files).toHaveLength(1);
    expect(files[0]).toBeInstanceOf(File);
    expect(files[0]).toMatchObject({
      name: `pasted-image.${extension}`,
      size: 4,
      type,
    });
    expect(validateEditorAsset({ kind: "image", file: files[0] })).toBeTruthy();
  });

  it.each([
    '<img src="data:image/svg+xml;base64,PHN2Zz4=">',
    '<img src="data:image/png;base64,not-valid-***">',
    '<img src="data:image/png;base64,">',
  ])("rejects an unsupported or malformed pasted data image", (html) => {
    expect(extractEditorDataImages(html)).toEqual({ files: [], rejected: true });
  });

  it("does not decode remote images or data-looking text outside an image source", () => {
    expect(extractEditorDataImages(
      '<p>data:image/png;base64,AQIDBA==</p><img src="https://tracker.example/pixel.png">',
    )).toEqual({ files: [], rejected: false });
  });

  it("ignores parser-confusing image text and images inside dangerous subtrees", () => {
    const dataUrl = "data:image/png;base64,AQIDBA==";
    const html = [
      `<script>const bait = '<img src="${dataUrl}">'</script>`,
      `<img alt=" src='${dataUrl}'" src="https://tracker.example/pixel.png">`,
      `<template><img src="${dataUrl}"></template>`,
      `<svg><foreignObject><img src="${dataUrl}"></foreignObject></svg>`,
    ].join("");

    expect(extractEditorDataImages(html)).toEqual({ files: [], rejected: false });
  });

  it.each([
    [makeFile({ name: "diagram.png", type: "image/png" }), "image"],
    [makeFile({ name: "lesson.mp4", type: "video/mp4" }), "video"],
    [makeFile({ name: "reading.pdf", type: "application/pdf" }), "pdf"],
    [makeFile({ name: "tracker.svg", type: "image/svg+xml" }), null],
  ])("classifies dropped files without reading or fetching them", (file, kind) => {
    expect(editorAssetKind(file)).toBe(kind);
  });

  it.each([
    [0, "0 bytes"],
    [1, "1 byte"],
    [1024, "1 KB"],
    [1536, "1.5 KB"],
    [2 * 1024 * 1024, "2 MB"],
  ])("formats %d bytes for attachment display", (bytes, expected) => {
    expect(formatEditorAssetSize(bytes)).toBe(expected);
  });

  it.each([
    [
      { kind: "image", mimeType: "image/png", name: "Diagram.png", size: 20, url: objectUrl("1".repeat(32), "png") },
      "setImage",
      { alt: "Diagram.png", class: "img-fluid", src: objectUrl("1".repeat(32), "png") },
    ],
    [
      { kind: "video", mimeType: "video/mp4", name: "Lesson.mp4", size: 20, url: objectUrl("2".repeat(32), "mp4") },
      "setVideo",
      { src: objectUrl("2".repeat(32), "mp4"), type: "video/mp4" },
    ],
    [
      { kind: "pdf", mimeType: "application/pdf", name: "Reading.pdf", size: 1536, url: objectUrl("3".repeat(32), "pdf") },
      "setAttachment",
      {
        name: "Reading.pdf",
        size: "1.5 KB",
        type: "application/pdf",
        url: objectUrl("3".repeat(32), "pdf"),
      },
    ],
  ])("inserts a validated %s result with the canonical node command", (asset, command, attributes) => {
    const run = vi.fn(() => true);
    const commandFn = vi.fn(() => ({ run }));
    const focus = vi.fn(() => ({ [command]: commandFn }));
    const editor = { chain: vi.fn(() => ({ focus })) };

    expect(insertEditorAsset(editor, asset)).toBe(true);
    expect(commandFn).toHaveBeenCalledWith(attributes);
    expect(run).toHaveBeenCalledTimes(1);
  });

  it("refuses to insert a malformed result", () => {
    const editor = { chain: vi.fn() };
    expect(insertEditorAsset(editor, {
      kind: "image",
      mimeType: "image/png",
      name: "Diagram.png",
      size: 20,
      url: "https://tracker.example/diagram.png",
    })).toBe(false);
    expect(editor.chain).not.toHaveBeenCalled();
  });
});
