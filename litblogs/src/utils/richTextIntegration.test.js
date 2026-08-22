// @vitest-environment node

import { readFileSync } from "node:fs";
import path from "node:path";
import { fileURLToPath } from "node:url";

import { describe, expect, it } from "vitest";

const sourceRoot = path.resolve(
  path.dirname(fileURLToPath(import.meta.url)),
  "..",
);
const richTextConsumers = [
  "ClassFeed.jsx",
  "PostView.jsx",
  "StudentHub.jsx",
  "components/ClassDetails.jsx",
  "components/StudentDetails.jsx",
];

const readSource = (relativePath) => readFileSync(
  path.join(sourceRoot, relativePath),
  "utf8",
);

describe("rich-text integration policy", () => {
  it.each(richTextConsumers)("routes %s through the canonical sanitizer", (relativePath) => {
    const source = readSource(relativePath);

    expect(source).toContain("richTextSecurity");
    expect(source).toMatch(/sanitizeRichText|createSanitizedRichTextContainer/);
    expect(source).not.toMatch(/ReactHtmlParser/);
  });

  it.each(richTextConsumers)("does not reparse DOM text with innerHTML in %s", (relativePath) => {
    const source = readSource(relativePath);

    expect(source).not.toMatch(/\.innerHTML\s*=/);
    expect(source).not.toMatch(/decodeHTML(?:Entities|HtmlEntities)/);
    expect(source).not.toMatch(/\.replace\(\/&lt;\/g,\s*["']<["']\)/);
  });

  it("sanitizes every HTML fragment before inserting it into TinyMCE", () => {
    const source = readSource("ClassFeed.jsx");
    const insertions = source.match(/editor\.insertContent\(/g) || [];
    const sanitizedInsertions = source.match(/editor\.insertContent\(sanitizeRichText\(/g) || [];

    expect(insertions.length).toBeGreaterThan(0);
    expect(sanitizedInsertions).toHaveLength(insertions.length);
  });

  it("rejects non-canonical image URLs before inserting them into TinyMCE", () => {
    const source = readSource("ClassFeed.jsx");

    expect(source).toContain("normalizeRichTextUrl(data.url, 'image')");
  });

  it("reads attachment metadata from the sanitized attachment container", () => {
    const source = readSource("PostView.jsx");

    expect(source).toContain("attachment.getAttribute('data-file-url')");
  });
});
