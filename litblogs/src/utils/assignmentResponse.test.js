// @vitest-environment jsdom

import { describe, expect, it } from "vitest";

import {
  assignmentContentForEditing,
  assignmentContentForEditor,
  hasAssignmentResponse,
} from "./assignmentResponse.js";
import { sanitizeRichText } from "./richTextSecurity.js";

describe("assignment response format compatibility", () => {
  it("preserves literal legacy plain text when opening the rich editor", () => {
    expect(assignmentContentForEditor("Use <img> literally\nNext & final", "plain"))
      .toBe("<p>Use &lt;img&gt; literally</p><p>Next &amp; final</p>");
  });

  it("keeps long legacy plain responses editable without rich-editor truncation", () => {
    const content = "a".repeat(100_000);
    expect(assignmentContentForEditing(content, "plain")).toEqual({
      content,
      contentFormat: "plain",
    });
  });

  it("protects literal legacy video markup from media recovery", () => {
    const plain = 'Describe <video src="/api/uploads/objects/ab/abababababababababababababababab.mp4"> literally';
    const html = assignmentContentForEditor(plain, "plain");
    expect(html).toContain("<code>");
    expect(sanitizeRichText(html, { mode: "editor" })).not.toContain("<video");
    expect(sanitizeRichText(html)).not.toContain("<video");
    expect(sanitizeRichText(html)).toContain("&lt;video");
  });

  it("accepts media-only rich responses but rejects empty editor markup", () => {
    const imageUrl = `/api/uploads/objects/ab/${"ab".repeat(16)}.png`;
    expect(hasAssignmentResponse(`<p><img src="${imageUrl}" alt="Diagram"></p>`)).toBe(true);
    expect(hasAssignmentResponse("<p><br></p>")).toBe(false);
    expect(hasAssignmentResponse("<p>   </p>")).toBe(false);
  });

  it("strips unsafe HTML from rich content before importing it", () => {
    expect(assignmentContentForEditor('<p>Answer</p><script>alert(1)</script>', "rich"))
      .not.toContain("<script");
  });
});
