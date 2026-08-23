import { readFileSync } from "node:fs";
import process from "node:process";
import { resolve } from "node:path";

import { describe, expect, it } from "vitest";

const classFeedSource = readFileSync(resolve(process.cwd(), "src", "ClassFeed.jsx"), "utf8");
const editorSource = readFileSync(
  resolve(process.cwd(), "src", "components", "LitBlogsEditor.jsx"),
  "utf8",
);
const attachmentNodeSource = readFileSync(
  resolve(process.cwd(), "src", "components", "EditorAttachmentNodeView.jsx"),
  "utf8",
);

describe("upload lifecycle frontend contract", () => {
  it("never deletes uploaded objects while editing unsaved post content", () => {
    expect(classFeedSource).not.toContain("deleteFileFromServer");
    expect(classFeedSource).not.toContain("deleteVideoFromServer");
    expect(classFeedSource).not.toMatch(/axios\.delete\([^\n]*upload/);
  });

  it("updates controlled editor state when a custom attachment is removed", () => {
    expect(attachmentNodeSource).toContain("onClick={deleteNode}");
    expect(editorSource).toContain("onUpdate: ({ editor: updatedEditor })");
    expect(editorSource).toContain("onChangeRef.current(canonicalHtml)");
  });

  it("keeps preview removal controls from submitting the post form", () => {
    expect(classFeedSource).toMatch(
      /<button\s+type="button"\s+onClick=\{\(\) => onRemove\('media', index\)\}/,
    );
    expect(classFeedSource).toMatch(
      /<button\s+type="button"\s+onClick=\{\(\) => onRemove\('files', index\)\}/,
    );
  });

  it("keeps composer item removal controls from submitting the post form", () => {
    expect(classFeedSource).toMatch(
      /codeSnippets\.map[\s\S]*?<button\s+type="button"\s+onClick=\{\(\) => \{/,
    );
    expect(classFeedSource).toMatch(
      /expandableLists\.map[\s\S]*?<button\s+type="button"\s+onClick=\{\(e\) => \{/,
    );
  });
});
