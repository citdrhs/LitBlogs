// @vitest-environment node

import { readFileSync } from "node:fs";
import { dirname, join } from "node:path";
import { fileURLToPath } from "node:url";

import { describe, expect, it } from "vitest";

const sourceRoot = join(dirname(fileURLToPath(import.meta.url)), "..");
const legacyStyles = readFileSync(join(sourceRoot, "LitBlogs.css"), "utf8");

describe("legacy application styles", () => {
  it("does not retain editor-specific selectors or TinyMCE skin hooks", () => {
    expect(legacyStyles).not.toMatch(
      /\.(?:html-content|post-content|raw-content(?:-wrapper)?|preserve-styles|tinymce-content|custom-font|preserved-heading|rich-text-content|prose|h[1-6])\b/i,
    );
    expect(legacyStyles).not.toMatch(/tinymce|\.tox-|\.mce-/i);
  });

  it("cannot override canonical document formatting or native video controls", () => {
    expect(legacyStyles).not.toMatch(/video::-(?:webkit|moz)-media-controls/i);
    expect(legacyStyles).not.toMatch(/\[(?:style|data-(?:font|font-family|color))[^\]]*\]/i);
    expect(legacyStyles).not.toMatch(/(?:^|,)\s*h[1-6](?:\s|,|\{)/im);
    expect(legacyStyles).not.toMatch(/\b(?:color|font-family|font-size|background-color)\s*:\s*attr\(/i);
  });
});
