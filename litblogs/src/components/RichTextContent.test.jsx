import { render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";

import RichTextContent from "./RichTextContent";

const RICH_FIXTURE = `
  <h2 style="color: rgb(29, 78, 216)">Reading response</h2>
  <p><span style="background-color: #fef3c7; font-size: 18.667px; font-family: Georgia, serif">Highlighted analysis</span></p>
  <ul><li><strong>Evidence</strong></li></ul>
  <script><p>dangerous subtree text</p></script>
`;

describe("RichTextContent", () => {
  it("renders canonical sanitized HTML without flattening allowed formatting", () => {
    render(<RichTextContent html={RICH_FIXTURE} testId="post-body" />);

    const content = screen.getByTestId("post-body");
    const heading = content.querySelector("h2");
    const highlighted = content.querySelector("p span");

    expect(content).toHaveClass("rich-text-content");
    expect(heading).toHaveTextContent("Reading response");
    expect(heading).toHaveStyle({ color: "#1d4ed8" });
    expect(highlighted).toHaveStyle({
      backgroundColor: "#fef3c7",
      fontSize: "18.667px",
    });
    expect(content.querySelector("ul li strong")).toHaveTextContent("Evidence");
    expect(content.querySelector("script")).toBeNull();
    expect(content).not.toHaveTextContent("dangerous subtree text");
  });

  it("keeps compact previews as rich DOM inside a visual clamp", () => {
    render(
      <RichTextContent
        html="<h3>Preview heading</h3><p><em>Formatted preview</em></p>"
        compact
        className="course-preview"
        testId="preview"
      />,
    );

    const preview = screen.getByTestId("preview");
    expect(preview).toHaveClass("rich-text-content", "rich-text-content--compact", "course-preview");
    expect(preview.querySelector("h3")).toHaveTextContent("Preview heading");
    expect(preview.querySelector("em")).toHaveTextContent("Formatted preview");
  });

  it("fails closed without logging or rendering malformed oversized content", () => {
    const oversized = `<p>${"x".repeat(1_000_001)}</p>`;

    render(<RichTextContent html={oversized} testId="oversized" />);

    expect(screen.getByTestId("oversized")).toBeEmptyDOMElement();
  });

  it("uses the same semantic output when sanitized again", () => {
    const { rerender } = render(<RichTextContent html={RICH_FIXTURE} testId="stable" />);
    const first = screen.getByTestId("stable").innerHTML;

    rerender(<RichTextContent html={first} testId="stable" />);

    expect(screen.getByTestId("stable").innerHTML).toBe(first);
  });
});
