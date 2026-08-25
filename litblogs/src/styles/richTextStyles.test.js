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

  it("keeps the authored foreground color on highlighted text", () => {
    const contentStyles = readStyle("rich-text-content.css");
    const markRule = contentStyles.match(
      /\.rich-text-content mark\s*\{(?<body>[^}]*)\}/,
    )?.groups?.body || "";

    expect(markRule).toMatch(/\bcolor\s*:\s*inherit\s*;/);
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

  it("styles upload feedback and selected editor-only media controls", () => {
    const editorStyles = readStyle("litblogs-editor.css");

    [
      ".litblogs-editor__upload-status",
      ".litblogs-editor__upload-error",
      ".litblogs-media-node.is-selected",
      ".litblogs-media-node__controls",
    ].forEach((selector) => expect(editorStyles).toContain(selector));
  });

  it("keeps editor media wrappers layout-neutral until selection chrome is painted", () => {
    const editorStyles = readStyle("litblogs-editor.css");
    const baseRule = editorStyles.match(/\.litblogs-media-node\s*\{(?<body>[^}]*)\}/)?.groups?.body || "";

    expect(baseRule).toContain("margin-inline: 0");
    expect(baseRule).not.toMatch(/\bpadding\s*:/);
    expect(baseRule).not.toMatch(/\bborder\s*:/);
    expect(editorStyles).toContain(".rich-text-content .litblogs-media-node.is-selected");
    expect(editorStyles).toContain("outline:");
  });

  it("themes only explicitly dark rich-text surfaces", () => {
    const contentStyles = readStyle("rich-text-content.css");

    expect(contentStyles).not.toContain(".dark .rich-text-content");
    expect(contentStyles).toContain(".rich-text-content--dark");
    expect(contentStyles).toContain("var(--rich-text-surface)");
  });

  it("keeps explicit media dimensions effective while unconstrained media stays responsive", () => {
    const contentStyles = readStyle("rich-text-content.css");
    const sharedMediaRule = contentStyles.match(
      /\.rich-text-content img,\s*\.rich-text-content video\s*\{(?<body>[^}]*)\}/,
    )?.groups?.body || "";

    expect(sharedMediaRule).not.toMatch(/\bheight\s*:\s*auto/);
    expect(contentStyles).toContain(".rich-text-content img:not([height])");
    expect(contentStyles).toContain(".rich-text-content video:not([height])");
    expect(contentStyles).toContain(
      ".rich-text-content figure.video-container video:not([width])",
    );
    expect(contentStyles).toContain(".rich-text-content img[width][height]");
    expect(contentStyles).toContain(".rich-text-content video[width][height]");
    expect(contentStyles).toContain(
      "aspect-ratio: attr(width type(<number>)) / attr(height type(<number>))",
    );
  });

  it("keeps the mobile link editor inside the toolbar flow", () => {
    const editorStyles = readStyle("litblogs-editor.css");
    const mobileRules = editorStyles.match(
      /@media \(max-width: 480px\)\s*\{(?<body>[\s\S]*)\}\s*$/,
    )?.groups?.body || "";
    const mobileLinkRule = mobileRules.match(
      /\.litblogs-link-dialog\s*\{(?<body>[^}]*)\}/,
    )?.groups?.body || "";

    expect(mobileLinkRule).toMatch(/\bposition\s*:\s*static\s*;/);
    expect(mobileLinkRule).toMatch(/\bwidth\s*:\s*100%\s*;/);
  });

  it("budgets the mobile toolbar for compact inline groups and icon actions", () => {
    const editorStyles = readStyle("litblogs-editor.css");
    const mobileRules = editorStyles.match(
      /@media \(max-width: 480px\)\s*\{(?<body>[\s\S]*)\}\s*$/,
    )?.groups?.body || "";
    const mobileToolbarRule = mobileRules.match(
      /\.litblogs-editor-toolbar\s*\{(?<body>[^}]*)\}/,
    )?.groups?.body || "";
    const mobileGroupRule = mobileRules.match(
      /\.litblogs-toolbar-group\s*\{(?<body>[^}]*)\}/,
    )?.groups?.body || "";

    expect(editorStyles).toContain(".litblogs-toolbar-button--icon svg");
    expect(editorStyles).toContain(".litblogs-alignment-menu");
    expect(mobileToolbarRule).toMatch(/\bmax-height\s*:\s*9rem\s*;/);
    expect(mobileGroupRule).toMatch(/\bwidth\s*:\s*auto\s*;/);
    expect(mobileGroupRule).not.toMatch(/\bwidth\s*:\s*100%\s*;/);
  });
});
