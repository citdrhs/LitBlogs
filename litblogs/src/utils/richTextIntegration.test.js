// @vitest-environment node

import { readFileSync } from "node:fs";
import path from "node:path";
import { fileURLToPath } from "node:url";

import { describe, expect, it } from "vitest";

const sourceRoot = path.resolve(
  path.dirname(fileURLToPath(import.meta.url)),
  "..",
);
const directSanitizerConsumers = ["ClassFeed.jsx"];
const sharedRendererConsumers = [
  "PostView.jsx",
  "StudentHub.jsx",
  "components/ClassDetails.jsx",
  "components/StudentDetails.jsx",
];
const richTextConsumers = [
  ...directSanitizerConsumers,
  ...sharedRendererConsumers,
];

const readSource = (relativePath) => readFileSync(
  path.join(sourceRoot, relativePath),
  "utf8",
);

describe("rich-text integration policy", () => {
  it.each(directSanitizerConsumers)("routes %s through the canonical sanitizer", (relativePath) => {
    const source = readSource(relativePath);

    expect(source).toContain("richTextSecurity");
    expect(source).toMatch(/sanitizeRichText|createSanitizedRichTextContainer/);
    expect(source).not.toMatch(/ReactHtmlParser/);
  });

  it.each(sharedRendererConsumers)("routes %s through RichTextContent", (relativePath) => {
    const source = readSource(relativePath);

    expect(source).toContain("RichTextContent");
    expect(source).not.toContain("richTextSecurity");
    expect(source).not.toMatch(/dangerouslySetInnerHTML/);
    expect(source).not.toMatch(
      /createSanitizedRichTextContainer|serializeSanitizedRichText|processHTMLWithDOM|stripInlineTextColor|truncateHTML/,
    );
  });

  it("uses the full shared renderer for PostView", () => {
    const source = readSource("PostView.jsx");

    expect(source).toMatch(/<RichTextContent\s+html=\{post\.content \|\| ''\}/);
    expect(source).not.toMatch(/<RichTextContent[\s\S]*?\scompact(?:\s|=)[\s\S]*?\/>/);
  });

  it.each([
    "StudentHub.jsx",
    "components/ClassDetails.jsx",
    "components/StudentDetails.jsx",
  ])("uses the compact shared renderer for %s", (relativePath) => {
    const source = readSource(relativePath);

    expect(source).toMatch(/<RichTextContent[\s\S]*?\scompact\s+[\s\S]*?\/>/);
  });

  it.each(richTextConsumers)("does not reparse DOM text with innerHTML in %s", (relativePath) => {
    const source = readSource(relativePath);

    expect(source).not.toMatch(/\.innerHTML\s*=/);
    expect(source).not.toMatch(/decodeHTML(?:Entities|HtmlEntities)/);
    expect(source).not.toMatch(/\.replace\(\/&lt;\/g,\s*["']<["']\)/);
  });

  it("sanitizes Tiptap imports, pasted HTML, and serialized output", () => {
    const source = readSource("components/LitBlogsEditor.jsx");

    expect(source).toContain("transformPastedHTML: sanitizeImportedHtml");
    expect(source).toContain("initialContentRef.current = sanitizeImportedHtml(value)");
    const rawRead = source.indexOf("const rawHtml = updatedEditor.getHTML()");
    const limitReport = source.indexOf("reportContentLimit(rawHtml)", rawRead);
    const sanitizeRaw = source.indexOf("sanitizeSerializedHtml(rawHtml)", limitReport);
    expect(rawRead).toBeGreaterThan(-1);
    expect(limitReport).toBeGreaterThan(rawRead);
    expect(sanitizeRaw).toBeGreaterThan(limitReport);
    expect(source).not.toMatch(/tinymce|SelfHostedEditor|editor\.insertContent/i);
  });

  it("rejects non-canonical image URLs before inserting them into Tiptap", () => {
    const editorSource = readSource("components/LitBlogsEditor.jsx");
    const uploadSource = readSource("editor/editorUploads.js");

    expect(editorSource).toContain('normalizeRichTextUrl(imageUrl, "image")');
    expect(uploadSource).toContain("isCanonicalUploadUrl(asset?.url)");
  });

});
