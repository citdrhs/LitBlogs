// @vitest-environment node

import { readFileSync } from "node:fs";
import { dirname, join } from "node:path";
import { fileURLToPath } from "node:url";

import { describe, expect, it } from "vitest";

const stylesRoot = dirname(fileURLToPath(import.meta.url));
const readStyle = (name) => readFileSync(join(stylesRoot, name), "utf8");

describe("shared rich-text styles", () => {
  it("never overrides sanitized inline formatting with priority rules", () => {
    const contentStyles = readStyle("rich-text-content.css");

    expect(contentStyles).not.toMatch(/!important/i);
    expect(contentStyles).not.toMatch(/\[style(?:\]|[*^$|~]?=)[^{]*\{[^}]*\bcolor\s*:/i);
    expect(contentStyles).not.toMatch(/tinymce|\.tox-|\.mce-/i);
  });

  it("defines one document surface for every canonical content family", () => {
    const contentStyles = readStyle("rich-text-content.css");

    [
      ".rich-text-content h1",
      ".rich-text-content blockquote",
      ".rich-text-content ul",
      ".rich-text-content table",
      ".rich-text-content pre",
      ".rich-text-content img",
      ".rich-text-content figure.video-container",
      ".rich-text-content .file-attachment",
      ".rich-text-content--compact",
    ].forEach((selector) => expect(contentStyles).toContain(selector));
  });

  it("renders actual palette colors and explicit white/none treatments", () => {
    const editorStyles = readStyle("litblogs-editor.css");

    expect(editorStyles).toContain("background: var(--swatch-color)");
    expect(editorStyles).toContain("background: var(--selected-color)");
    expect(editorStyles).toContain(".litblogs-color-swatch--light");
    expect(editorStyles).toContain(".litblogs-color-swatch--none");
    expect(editorStyles).toContain("repeating-conic-gradient");
    expect(editorStyles).not.toMatch(/tinymce|\.tox-|\.mce-/i);
  });
});
