import { fireEvent, render, screen } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";

import EditorAttachmentNodeView from "./EditorAttachmentNodeView.jsx";
import EditorImageNodeView from "./EditorImageNodeView.jsx";
import EditorVideoNodeView from "./EditorVideoNodeView.jsx";
import { Attachment, CanonicalImage, Video } from "../editor/mediaNodes.js";

vi.mock("@tiptap/react", async (importOriginal) => {
  const actual = await importOriginal();
  return {
    ...actual,
    NodeViewWrapper: ({ as: Element = "div", children, ...props }) => (
      <Element {...props}>{children}</Element>
    ),
  };
});

const IMAGE_URL = "/api/uploads/objects/11/11111111111111111111111111111111.png";
const VIDEO_URL = "/api/uploads/objects/22/22222222222222222222222222222222.mp4";
const PDF_URL = "/api/uploads/objects/33/33333333333333333333333333333333.pdf";

const defaultProps = (attrs, overrides = {}) => ({
  deleteNode: vi.fn(),
  editor: { isEditable: true },
  node: { attrs },
  selected: true,
  updateAttributes: vi.fn(),
  ...overrides,
});

describe("editor-only rich media NodeViews", () => {
  beforeEach(() => {
    vi.clearAllMocks();
  });

  it.each([CanonicalImage, Video, Attachment])(
    "registers a React NodeView for %s",
    (extension) => {
      expect(extension.config.addNodeView).toEqual(expect.any(Function));
      expect(extension.config.addNodeView()).toEqual(expect.any(Function));
    },
  );

  it("edits image alt text, width, and alignment through transactions", () => {
    const props = defaultProps({
      alt: "Original diagram",
      class: "img-fluid",
      height: null,
      src: IMAGE_URL,
      title: null,
      width: null,
    });
    render(<EditorImageNodeView {...props} />);

    expect(screen.getByRole("img", { name: "Original diagram" })).toHaveAttribute("src", IMAGE_URL);
    fireEvent.change(screen.getByRole("textbox", { name: "Image description" }), {
      target: { value: "Updated diagram" },
    });
    fireEvent.change(screen.getByRole("combobox", { name: "Image width" }), {
      target: { value: "50%" },
    });
    fireEvent.click(screen.getByRole("button", { name: "Center image" }));

    expect(props.updateAttributes).toHaveBeenCalledWith({ alt: "Updated diagram" });
    expect(props.updateAttributes).toHaveBeenCalledWith({ height: null, width: "50%" });
    expect(props.updateAttributes).toHaveBeenCalledWith({ class: "img-fluid mx-auto d-block" });
  });

  it("supports exact pixel width and height plus a one-click dimension reset", () => {
    const props = defaultProps({
      alt: "Diagram",
      class: "img-fluid",
      height: "360",
      src: IMAGE_URL,
      width: "640",
    });
    render(<EditorImageNodeView {...props} />);

    expect(screen.getByRole("combobox", { name: "Image width" })).toHaveValue("custom");
    expect(screen.getByRole("spinbutton", { name: "Custom image width (pixels)" })).toHaveValue(640);
    expect(screen.getByRole("spinbutton", { name: "Custom image height (pixels)" })).toHaveValue(360);
    fireEvent.change(screen.getByRole("spinbutton", { name: "Custom image width (pixels)" }), {
      target: { value: "720" },
    });
    fireEvent.change(screen.getByRole("spinbutton", { name: "Custom image height (pixels)" }), {
      target: { value: "405" },
    });
    fireEvent.click(screen.getByRole("button", { name: "Reset image dimensions" }));

    expect(props.updateAttributes).toHaveBeenCalledWith({ width: "720" });
    expect(props.updateAttributes).toHaveBeenCalledWith({ height: "405" });
    expect(props.updateAttributes).toHaveBeenCalledWith({ height: null, width: null });
  });

  it("prevents image-description Enter from submitting the outer post form", () => {
    const onSubmit = vi.fn((event) => event.preventDefault());
    const props = defaultProps({ alt: "Diagram", class: "img-fluid", src: IMAGE_URL });
    render(
      <form onSubmit={onSubmit}>
        <EditorImageNodeView {...props} />
      </form>,
    );

    const description = screen.getByRole("textbox", { name: "Image description" });
    expect(fireEvent.keyDown(description, { key: "Enter", code: "Enter" })).toBe(false);
    expect(onSubmit).not.toHaveBeenCalled();
    expect(fireEvent.keyDown(description, {
      key: "Enter",
      code: "Enter",
      isComposing: true,
    })).toBe(true);
  });

  it("removes an image node without deleting the uploaded object", () => {
    const props = defaultProps({ alt: "Diagram", class: "img-fluid", src: IMAGE_URL });
    render(<EditorImageNodeView {...props} />);

    fireEvent.click(screen.getByRole("button", { name: "Remove image from post" }));
    expect(props.deleteNode).toHaveBeenCalledTimes(1);
  });

  it("renders video controls and an editor-only remove action", () => {
    const props = defaultProps({
      height: null,
      preload: "metadata",
      src: VIDEO_URL,
      type: "video/mp4",
      width: null,
    });
    const { container } = render(<EditorVideoNodeView {...props} />);

    const video = container.querySelector("video");
    expect(video).toHaveAttribute("controls");
    expect(video).toHaveAttribute("preload", "metadata");
    expect(video.querySelector("source")).toHaveAttribute("src", VIDEO_URL);
    expect(video.querySelector("source")).toHaveAttribute("type", "video/mp4");

    fireEvent.click(screen.getByRole("button", { name: "Remove video from post" }));
    expect(props.deleteNode).toHaveBeenCalledTimes(1);
  });

  it("renders a PDF attachment without an editor-time download request", () => {
    const props = defaultProps({
      name: "Course reading.pdf",
      size: "1.5 MB",
      type: "application/pdf",
      url: PDF_URL,
    });
    render(<EditorAttachmentNodeView {...props} />);

    expect(screen.getByText("Course reading.pdf")).toBeInTheDocument();
    expect(screen.getByText("1.5 MB")).toBeInTheDocument();
    expect(screen.queryByRole("link")).not.toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: "Remove PDF from post" }));
    expect(props.deleteNode).toHaveBeenCalledTimes(1);
  });

  it.each([
    [EditorImageNodeView, { alt: "Diagram", class: "img-fluid", src: IMAGE_URL }, "Remove image from post"],
    [EditorVideoNodeView, { src: VIDEO_URL, type: "video/mp4" }, "Remove video from post"],
    [EditorAttachmentNodeView, { name: "Reading.pdf", type: "application/pdf", url: PDF_URL }, "Remove PDF from post"],
  ])("hides %p editing controls when read-only", (Component, attrs, removeLabel) => {
    render(<Component {...defaultProps(attrs, { editor: { isEditable: false } })} />);
    expect(screen.queryByRole("button", { name: removeLabel })).not.toBeInTheDocument();
  });

  it("uses explicit button types for every NodeView action", () => {
    const views = [
      render(<EditorImageNodeView {...defaultProps({ alt: "Diagram", src: IMAGE_URL })} />),
      render(<EditorVideoNodeView {...defaultProps({ src: VIDEO_URL, type: "video/mp4" })} />),
      render(<EditorAttachmentNodeView {...defaultProps({ name: "Reading.pdf", url: PDF_URL })} />),
    ];

    for (const view of views) {
      expect([...view.container.querySelectorAll("button")]).not.toHaveLength(0);
      for (const button of view.container.querySelectorAll("button")) {
        expect(button).toHaveAttribute("type", "button");
      }
    }
  });
});
