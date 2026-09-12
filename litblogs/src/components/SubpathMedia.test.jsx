import { fireEvent, render, screen } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";

const { openPdfViewerModal } = vi.hoisted(() => ({ openPdfViewerModal: vi.fn() }));
vi.mock("./PdfViewerModal", () => ({ openPdfViewerModal }));
vi.mock("@tiptap/react", () => ({
  NodeViewWrapper: ({ as: Element = "div", children, ...props }) => <Element {...props}>{children}</Element>,
  ReactNodeViewRenderer: vi.fn(),
}));

const IMAGE = "/api/uploads/objects/11/11111111111111111111111111111111.png";
const VIDEO = "/api/uploads/objects/22/22222222222222222222222222222222.mp4";
const PDF = "/api/uploads/objects/33/33333333333333333333333333333333.pdf";

afterEach(() => {
  vi.clearAllMocks();
  vi.unstubAllEnvs();
  vi.resetModules();
});

describe.each(["/", "/dren/"])("media display at %s", (base) => {
  const prefix = base === "/" ? "" : "/dren";
  const prepare = () => {
    vi.resetModules();
    vi.stubEnv("BASE_URL", base);
  };

  it("loads image, video, and PDF through the app prefix without changing canonical content", async () => {
    prepare();
    const { default: RichTextContent } = await import("./RichTextContent.jsx");
    const { sanitizeRichText } = await import("../utils/richTextSecurity.js");
    const html = `<img src="${IMAGE}" alt="Diagram"><video controls><source src="${VIDEO}" type="video/mp4"></video><div class="file-attachment" data-file-url="${PDF}" data-file-name="Reading.pdf" data-file-type="application/pdf"><span class="file-name">Reading.pdf</span></div>`;
    const canonical = sanitizeRichText(html, { mode: "render" });
    const { container, rerender } = render(<RichTextContent html={html} />);
    expect(screen.getByAltText("Diagram")).toHaveAttribute("src", `${prefix}${IMAGE}`);
    expect(container.querySelector("source")).toHaveAttribute("src", `${prefix}${VIDEO}`);
    fireEvent.click(screen.getByRole("button", { name: "Open PDF Reading.pdf" }));
    expect(openPdfViewerModal).toHaveBeenCalledWith({ fileUrl: `${prefix}${PDF}`, title: "Reading.pdf" });
    const displayed = container.firstChild.innerHTML;
    expect(sanitizeRichText(displayed, { mode: "render" })).toBe(canonical);
    rerender(<RichTextContent html={displayed} />);
    expect(screen.getByAltText("Diagram")).toHaveAttribute("src", `${prefix}${IMAGE}`);
  });

  it("prefixes editor DOM media while keeping node attributes and serialized HTML canonical", async () => {
    prepare();
    const { default: ImageView } = await import("./EditorImageNodeView.jsx");
    const { default: VideoView } = await import("./EditorVideoNodeView.jsx");
    const { CanonicalImage, Video } = await import("../editor/mediaNodes.js");
    const imageNode = { attrs: { src: IMAGE, alt: "Editor diagram" } };
    const videoNode = { attrs: { src: VIDEO, type: "video/mp4" } };
    const { container } = render(<><ImageView node={imageNode} /><VideoView node={videoNode} /><VideoView node={{ attrs: { src: VIDEO } }} /></>);
    expect(screen.getByAltText("Editor diagram")).toHaveAttribute("src", `${prefix}${IMAGE}`);
    expect(container.querySelector("source")).toHaveAttribute("src", `${prefix}${VIDEO}`);
    expect(container.querySelector("video[src]")).toHaveAttribute("src", `${prefix}${VIDEO}`);
    expect(imageNode.attrs.src).toBe(IMAGE);
    expect(videoNode.attrs.src).toBe(VIDEO);
    expect(JSON.stringify(CanonicalImage.config.renderHTML({ node: imageNode }))).toContain(IMAGE);
    expect(JSON.stringify(Video.config.renderHTML({ node: videoNode }))).toContain(VIDEO);
    expect(JSON.stringify(CanonicalImage.config.renderHTML({ node: imageNode }))).not.toContain("/dren/");
  });
});
