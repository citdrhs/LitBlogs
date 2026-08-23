import { act, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";

import LitBlogsEditor from "./LitBlogsEditor.jsx";

const mocks = vi.hoisted(() => ({
  createRichTextExtensions: vi.fn(() => []),
  editor: null,
  options: null,
  toolbarProps: null,
  uploadEditorAsset: vi.fn(),
  insertEditorAsset: vi.fn(() => true),
  editorAssetKind: vi.fn(),
  extractEditorDataImages: vi.fn(() => ({ files: [], rejected: false })),
}));

vi.mock("@tiptap/react", () => ({
  EditorContent: ({ editor: _editor, ...props }) => <div {...props} />,
  useEditor: (options) => {
    mocks.options = options;
    return mocks.editor;
  },
}));

vi.mock("../editor/richTextSchema.js", () => ({
  createRichTextExtensions: (...args) => mocks.createRichTextExtensions(...args),
}));

vi.mock("../editor/editorUploads.js", () => ({
  EDITOR_UPLOAD_ACCEPT: {
    image: "image-accept",
    pdf: "pdf-accept",
    video: "video-accept",
  },
  editorAssetKind: (...args) => mocks.editorAssetKind(...args),
  extractEditorDataImages: (...args) => mocks.extractEditorDataImages(...args),
  insertEditorAsset: (...args) => mocks.insertEditorAsset(...args),
  uploadEditorAsset: (...args) => mocks.uploadEditorAsset(...args),
}));

vi.mock("./LitBlogsEditorToolbar.jsx", () => ({
  default: (props) => {
    mocks.toolbarProps = props;
    return (
      <div role="toolbar" aria-label="Rich text formatting">
        <button type="button" disabled={props.disabled} onClick={() => props.onInsertImage?.(props.editor)}>Choose image</button>
        <button type="button" disabled={props.disabled} onClick={() => props.onInsertVideo?.(props.editor)}>Choose video</button>
        <button type="button" disabled={props.disabled} onClick={() => props.onInsertPdf?.(props.editor)}>Choose PDF</button>
      </div>
    );
  },
}));

const makeFile = (name, type) => new File([new Uint8Array(4)], name, { type });

const createFakeEditor = () => ({
  isEditable: true,
  commands: { setContent: vi.fn() },
  getHTML: vi.fn(() => "<p>Initial</p>"),
  setEditable: vi.fn(),
});

beforeEach(() => {
  vi.clearAllMocks();
  mocks.editor = createFakeEditor();
  mocks.editorAssetKind.mockImplementation((file) => {
    if (["image/bmp", "image/gif", "image/jpeg", "image/png", "image/webp"].includes(file.type)) {
      return "image";
    }
    if (file.type.startsWith("video/")) return "video";
    if (file.type === "application/pdf") return "pdf";
    return null;
  });
  mocks.extractEditorDataImages.mockReturnValue({ files: [], rejected: false });
  mocks.uploadEditorAsset.mockImplementation(async ({ kind, file, onProgress }) => {
    onProgress?.(50);
    return {
      kind,
      mimeType: file.type,
      name: file.name,
      size: file.size,
      url: `/api/uploads/objects/aa/${"a".repeat(32)}.${kind === "pdf" ? "pdf" : "png"}`,
    };
  });
});

describe("LitBlogsEditor uploads", () => {
  it.each([
    ["image", "Choose image", "image-accept", "diagram.png", "image/png"],
    ["video", "Choose video", "video-accept", "lesson.mp4", "video/mp4"],
    ["pdf", "Choose PDF", "pdf-accept", "reading.pdf", "application/pdf"],
  ])("uploads and inserts a selected %s", async (kind, button, accept, name, type) => {
    render(<LitBlogsEditor value="<p>Initial</p>" onChange={vi.fn()} />);
    const input = screen.getByTestId(`editor-${kind}-input`);
    const click = vi.spyOn(input, "click");

    fireEvent.click(screen.getByRole("button", { name: button }));
    if (kind === "image") {
      expect(screen.getByRole("dialog", { name: "Insert image" })).toBeInTheDocument();
      fireEvent.click(screen.getByRole("button", { name: "Upload from computer" }));
    }
    expect(click).toHaveBeenCalledTimes(1);
    expect(input).toHaveAttribute("accept", accept);

    const file = makeFile(name, type);
    fireEvent.change(input, { target: { files: [file] } });

    await waitFor(() => expect(mocks.uploadEditorAsset).toHaveBeenCalledWith(expect.objectContaining({
      file,
      kind,
      onProgress: expect.any(Function),
      signal: expect.any(AbortSignal),
    })));
    expect(mocks.insertEditorAsset).toHaveBeenCalledWith(
      mocks.editor,
      expect.objectContaining({ kind, name }),
    );
    expect(input).toHaveValue("");
  });

  it("inserts only an authorized school image URL without fetching it", () => {
    const safeUrl = `/api/uploads/objects/aa/${"a".repeat(32)}.png`;
    render(<LitBlogsEditor value="" onChange={vi.fn()} />);

    fireEvent.click(screen.getByRole("button", { name: "Choose image" }));
    fireEvent.change(screen.getByRole("textbox", { name: "School image URL" }), {
      target: { value: safeUrl },
    });
    fireEvent.change(screen.getByRole("textbox", { name: "Image description" }), {
      target: { value: "Cell diagram" },
    });
    fireEvent.click(screen.getByRole("button", { name: "Insert school image" }));

    expect(mocks.insertEditorAsset).toHaveBeenCalledWith(mocks.editor, {
      kind: "image",
      mimeType: "",
      name: "Cell diagram",
      size: 0,
      url: safeUrl,
    });
    expect(mocks.uploadEditorAsset).not.toHaveBeenCalled();
    expect(screen.queryByRole("dialog", { name: "Insert image" })).not.toBeInTheDocument();
  });

  it("accepts canonical relative image paths without native URL-field rejection", () => {
    render(<LitBlogsEditor value="" onChange={vi.fn()} />);
    fireEvent.click(screen.getByRole("button", { name: "Choose image" }));

    const url = screen.getByRole("textbox", { name: "School image URL" });
    expect(url).toHaveAttribute("type", "text");
    expect(url).toHaveAttribute("inputmode", "url");
  });

  it("does not insert or publish while Enter belongs to an IME composition", () => {
    const onPostSubmit = vi.fn((event) => event.preventDefault());
    const safeUrl = `/api/uploads/objects/aa/${"a".repeat(32)}.png`;
    render(
      <form onSubmit={onPostSubmit}>
        <LitBlogsEditor value="" onChange={vi.fn()} />
      </form>,
    );
    fireEvent.click(screen.getByRole("button", { name: "Choose image" }));
    const url = screen.getByRole("textbox", { name: "School image URL" });
    fireEvent.change(url, { target: { value: safeUrl } });

    fireEvent.keyDown(url, { key: "Enter", code: "Enter", isComposing: true });

    expect(mocks.insertEditorAsset).not.toHaveBeenCalled();
    expect(onPostSubmit).not.toHaveBeenCalled();
    expect(screen.getByRole("dialog", { name: "Insert image" })).toBeInTheDocument();
  });

  it("uses non-composing image-dialog Enter for insertion without publishing the post", () => {
    const onPostSubmit = vi.fn((event) => event.preventDefault());
    const safeUrl = `/api/uploads/objects/aa/${"a".repeat(32)}.png`;
    render(
      <form onSubmit={onPostSubmit}>
        <LitBlogsEditor value="" onChange={vi.fn()} />
      </form>,
    );
    fireEvent.click(screen.getByRole("button", { name: "Choose image" }));
    fireEvent.change(screen.getByRole("textbox", { name: "School image URL" }), {
      target: { value: safeUrl },
    });

    fireEvent.keyDown(screen.getByRole("textbox", { name: "Image description" }), {
      key: "Enter",
      code: "Enter",
    });

    expect(mocks.insertEditorAsset).toHaveBeenCalledWith(
      mocks.editor,
      expect.objectContaining({ kind: "image", url: safeUrl }),
    );
    expect(onPostSubmit).not.toHaveBeenCalled();
    expect(screen.queryByRole("dialog", { name: "Insert image" })).not.toBeInTheDocument();
  });

  it("keeps the image dialog open and rejects a remote image URL", () => {
    render(<LitBlogsEditor value="" onChange={vi.fn()} />);
    fireEvent.click(screen.getByRole("button", { name: "Choose image" }));
    fireEvent.change(screen.getByRole("textbox", { name: "School image URL" }), {
      target: { value: "https://tracker.example/pixel.png" },
    });
    fireEvent.click(screen.getByRole("button", { name: "Insert school image" }));

    expect(mocks.insertEditorAsset).not.toHaveBeenCalled();
    expect(screen.getByRole("dialog", { name: "Insert image" })).toBeInTheDocument();
    expect(screen.getByRole("alert")).toHaveTextContent(
      "Images must use an upload from this school site.",
    );
  });

  it("traps focus in the image dialog and restores the image button on Escape", () => {
    render(<LitBlogsEditor value="" onChange={vi.fn()} />);
    const invoker = screen.getByRole("button", { name: "Choose image" });
    invoker.focus();
    fireEvent.click(invoker);

    const dialog = screen.getByRole("dialog", { name: "Insert image" });
    const upload = screen.getByRole("button", { name: "Upload from computer" });
    const url = screen.getByRole("textbox", { name: "School image URL" });
    const insert = screen.getByRole("button", { name: "Insert school image" });
    expect(url).toHaveFocus();

    insert.focus();
    fireEvent.keyDown(insert, { key: "Tab" });
    expect(upload).toHaveFocus();

    upload.focus();
    fireEvent.keyDown(upload, { key: "Tab", shiftKey: true });
    expect(insert).toHaveFocus();

    fireEvent.keyDown(dialog, { key: "Escape" });
    expect(screen.queryByRole("dialog", { name: "Insert image" })).not.toBeInTheDocument();
    expect(invoker).toHaveFocus();
  });

  it("contains editor-owned submit events inside a surrounding post form", () => {
    const onPostSubmit = vi.fn((event) => event.preventDefault());
    render(
      <form onSubmit={onPostSubmit}>
        <LitBlogsEditor value="" onChange={vi.fn()} />
      </form>,
    );

    fireEvent.submit(screen.getByRole("toolbar", { name: "Rich text formatting" }));

    expect(onPostSubmit).not.toHaveBeenCalled();
  });

  it("shows bounded progress and a generic failure without leaking a file name", async () => {
    let rejectUpload;
    mocks.uploadEditorAsset.mockImplementation(({ onProgress }) => {
      onProgress(42.4);
      return new Promise((_resolve, reject) => {
        rejectUpload = reject;
      });
    });
    render(<LitBlogsEditor value="" onChange={vi.fn()} />);

    fireEvent.change(screen.getByTestId("editor-pdf-input"), {
      target: { files: [makeFile("private-teacher-notes.pdf", "application/pdf")] },
    });
    expect(await screen.findByRole("status")).toHaveTextContent("Uploading PDF… 42%");

    await act(async () => rejectUpload(new Error("Upload failed. Please try again.")));
    expect(await screen.findByRole("alert")).toHaveTextContent("Upload failed. Please try again.");
    expect(screen.getByRole("alert")).not.toHaveTextContent("private-teacher-notes");
  });

  it("uploads clipboard files but leaves safe text paste to ProseMirror", async () => {
    render(<LitBlogsEditor value="" onChange={vi.fn()} />);
    const image = makeFile("pasted.png", "image/png");
    const fileEvent = {
      clipboardData: { files: [image], items: [] },
      preventDefault: vi.fn(),
    };

    expect(mocks.options.editorProps.handlePaste(null, fileEvent)).toBe(true);
    expect(fileEvent.preventDefault).toHaveBeenCalledTimes(1);
    await waitFor(() => expect(mocks.uploadEditorAsset).toHaveBeenCalledWith(
      expect.objectContaining({ file: image, kind: "image" }),
    ));

    const textEvent = {
      clipboardData: { files: [], items: [], getData: () => "Safe text" },
      preventDefault: vi.fn(),
    };
    expect(mocks.options.editorProps.handlePaste(null, textEvent)).toBe(false);
    expect(textEvent.preventDefault).not.toHaveBeenCalled();
  });

  it("uploads an HTML-only data image while preserving surrounding rich paste", async () => {
    const image = makeFile("pasted-image.png", "image/png");
    mocks.extractEditorDataImages.mockReturnValue({ files: [image], rejected: false });
    render(<LitBlogsEditor value="" onChange={vi.fn()} />);
    const html = '<p><strong>Diagram</strong></p><img src="data:image/png;base64,AQIDBA==">';
    const pasteEvent = {
      clipboardData: {
        files: [],
        items: [],
        getData: vi.fn((type) => (type === "text/html" ? html : "")),
      },
      preventDefault: vi.fn(),
    };

    expect(mocks.options.editorProps.handlePaste(null, pasteEvent)).toBe(false);
    expect(pasteEvent.preventDefault).not.toHaveBeenCalled();
    expect(mocks.extractEditorDataImages).toHaveBeenCalledWith(html);
    const sanitized = mocks.options.editorProps.transformPastedHTML(html);
    expect(sanitized).toContain("<strong>Diagram</strong>");
    expect(sanitized).not.toContain("data:image");
    await waitFor(() => expect(mocks.uploadEditorAsset).toHaveBeenCalledWith(
      expect.objectContaining({ file: image, kind: "image" }),
    ));
  });

  it("uploads supported dropped files, rejects unsupported files, and never fetches remote HTML", async () => {
    render(<LitBlogsEditor value="" onChange={vi.fn()} />);
    const video = makeFile("lesson.mp4", "video/mp4");
    const dropEvent = {
      dataTransfer: { files: [video] },
      preventDefault: vi.fn(),
    };
    expect(mocks.options.editorProps.handleDrop(null, dropEvent, null, false)).toBe(true);
    await waitFor(() => expect(mocks.uploadEditorAsset).toHaveBeenCalledWith(
      expect.objectContaining({ file: video, kind: "video" }),
    ));

    mocks.uploadEditorAsset.mockClear();
    const remoteEvent = {
      clipboardData: {
        files: [],
        items: [],
        getData: () => '<img src="https://tracker.example/pixel.png">',
      },
      preventDefault: vi.fn(),
    };
    expect(mocks.options.editorProps.handlePaste(null, remoteEvent)).toBe(false);
    expect(mocks.uploadEditorAsset).not.toHaveBeenCalled();

    const unsupported = makeFile("vector.svg", "image/svg+xml");
    const unsupportedEvent = {
      dataTransfer: { files: [unsupported] },
      preventDefault: vi.fn(),
    };
    expect(mocks.options.editorProps.handleDrop(null, unsupportedEvent, null, false)).toBe(true);
    expect(await screen.findByRole("alert")).toHaveTextContent("supported image, video, or PDF");
    expect(mocks.uploadEditorAsset).not.toHaveBeenCalled();
  });

  it("aborts an in-flight upload on unmount", async () => {
    let capturedSignal;
    mocks.uploadEditorAsset.mockImplementation(({ signal }) => {
      capturedSignal = signal;
      return new Promise(() => {});
    });
    const { unmount } = render(<LitBlogsEditor value="" onChange={vi.fn()} />);
    fireEvent.change(screen.getByTestId("editor-image-input"), {
      target: { files: [makeFile("diagram.png", "image/png")] },
    });
    await waitFor(() => expect(capturedSignal).toBeInstanceOf(AbortSignal));

    unmount();
    expect(capturedSignal.aborted).toBe(true);
  });

  it("aborts and never inserts an upload when the editor becomes disabled", async () => {
    let capturedSignal;
    let resolveUpload;
    const onUploadStateChange = vi.fn();
    mocks.uploadEditorAsset.mockImplementation(({ signal }) => {
      capturedSignal = signal;
      return new Promise((resolve) => {
        resolveUpload = resolve;
      });
    });
    const { rerender } = render(
      <LitBlogsEditor value="" onChange={vi.fn()} onUploadStateChange={onUploadStateChange} />,
    );
    fireEvent.change(screen.getByTestId("editor-image-input"), {
      target: { files: [makeFile("diagram.png", "image/png")] },
    });
    await waitFor(() => expect(capturedSignal).toBeInstanceOf(AbortSignal));
    expect(onUploadStateChange).toHaveBeenLastCalledWith(true);

    rerender(
      <LitBlogsEditor
        value=""
        onChange={vi.fn()}
        onUploadStateChange={onUploadStateChange}
        disabled
      />,
    );
    expect(capturedSignal.aborted).toBe(true);
    await act(async () => resolveUpload({
      kind: "image",
      mimeType: "image/png",
      name: "diagram.png",
      size: 4,
      url: `/api/uploads/objects/aa/${"a".repeat(32)}.png`,
    }));

    expect(mocks.insertEditorAsset).not.toHaveBeenCalled();
    await waitFor(() => expect(onUploadStateChange).toHaveBeenLastCalledWith(false));
  });

  it("keeps a mixed-file rejection visible while uploading supported files", async () => {
    render(<LitBlogsEditor value="" onChange={vi.fn()} />);
    const supported = makeFile("diagram.png", "image/png");
    const unsupported = makeFile("vector.svg", "image/svg+xml");
    const dropEvent = {
      dataTransfer: { files: [supported, unsupported], items: [] },
      preventDefault: vi.fn(),
    };

    expect(mocks.options.editorProps.handleDrop(null, dropEvent, null, false)).toBe(true);
    await waitFor(() => expect(mocks.uploadEditorAsset).toHaveBeenCalledWith(
      expect.objectContaining({ file: supported, kind: "image" }),
    ));
    expect(await screen.findByRole("alert")).toHaveTextContent(
      "Choose a supported image, video, or PDF file.",
    );
  });

  it("uses explicit buttons and disables all upload entry points with the editor", () => {
    render(<LitBlogsEditor value="" onChange={vi.fn()} disabled />);
    expect(screen.getByRole("button", { name: "Choose image" })).toBeDisabled();
    expect(screen.getByRole("button", { name: "Choose video" })).toBeDisabled();
    expect(screen.getByRole("button", { name: "Choose PDF" })).toBeDisabled();
    expect(screen.getByTestId("editor-image-input")).toBeDisabled();
    expect(screen.getByTestId("editor-video-input")).toBeDisabled();
    expect(screen.getByTestId("editor-pdf-input")).toBeDisabled();
  });
});
