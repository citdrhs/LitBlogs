import { act, render, screen } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { sanitizeRichText } from "../utils/richTextSecurity.js";
import LitBlogsEditor from "./LitBlogsEditor.jsx";

const mocks = vi.hoisted(() => ({
  createRichTextExtensions: vi.fn(() => []),
  editor: null,
  options: null,
  toolbarProps: null,
  useEditor: vi.fn(),
}));

vi.mock("@tiptap/react", () => ({
  EditorContent: ({ editor: _editor, ...props }) => <div {...props} />,
  useEditor: (options, dependencies) => {
    mocks.options = options;
    mocks.useEditor(options, dependencies);
    return mocks.editor;
  },
}));

vi.mock("../editor/richTextSchema.js", () => ({
  createRichTextExtensions: (...args) => mocks.createRichTextExtensions(...args),
}));

vi.mock("./LitBlogsEditorToolbar.jsx", () => ({
  default: (props) => {
    mocks.toolbarProps = props;
    return <div role="toolbar" aria-label="Rich text formatting" />;
  },
}));

const createFakeEditor = (initialHtml) => {
  let html = initialHtml;
  const editor = {
    isEditable: true,
    commands: {
      setContent: vi.fn((nextHtml) => {
        html = nextHtml;
      }),
    },
    getHTML: vi.fn(() => html),
    setEditable: vi.fn((editable) => {
      editor.isEditable = editable;
    }),
    setHtml(nextHtml) {
      html = nextHtml;
    },
  };
  return editor;
};

beforeEach(() => {
  mocks.createRichTextExtensions.mockClear();
  mocks.useEditor.mockClear();
  mocks.options = null;
  mocks.toolbarProps = null;
  mocks.editor = createFakeEditor("<p>Initial</p>");
});

describe("LitBlogsEditor", () => {
  it("sanitizes initial and pasted HTML before parsing and canonicalizes every emitted update", () => {
    const onChange = vi.fn();
    const initial = '<p onclick="bad()">Initial<script>alert(1)</script></p>';
    render(<LitBlogsEditor value={initial} onChange={onChange} editorFontSize="large" />);

    expect(mocks.createRichTextExtensions).toHaveBeenCalledWith({
      placeholder: "Write something...",
    });
    expect(mocks.options.content).toBe(sanitizeRichText(initial, { mode: "editor" }));
    expect(mocks.options.editorProps.attributes).toMatchObject({
      "aria-label": "Post content",
      "aria-multiline": "true",
      role: "textbox",
      spellcheck: "true",
    });

    const pasted = '<img src="https://tracker.example/pixel.png"><p onmouseover="bad()">Paste</p>';
    expect(mocks.options.editorProps.transformPastedHTML(pasted)).toBe(
      sanitizeRichText(pasted, { mode: "editor" }),
    );

    mocks.editor.setHtml('<p style="color: rgb(29, 78, 216)">Changed</p><button>Remove</button>');
    act(() => mocks.options.onUpdate({ editor: mocks.editor }));

    expect(onChange).toHaveBeenCalledTimes(1);
    expect(onChange).toHaveBeenCalledWith(sanitizeRichText(mocks.editor.getHTML()));
  });

  it("does not reset the cursor or emit again for echoed output, but imports genuine external changes once", () => {
    const firstOnChange = vi.fn();
    const { rerender } = render(
      <LitBlogsEditor value="<p>Initial</p>" onChange={firstOnChange} editorFontSize="medium" />,
    );

    mocks.editor.setHtml("<p>Typed</p>");
    act(() => mocks.options.onUpdate({ editor: mocks.editor }));
    expect(firstOnChange).toHaveBeenLastCalledWith("<p>Typed</p>");

    rerender(<LitBlogsEditor value="<p>Typed</p>" onChange={firstOnChange} editorFontSize="medium" />);
    expect(mocks.editor.commands.setContent).not.toHaveBeenCalled();

    const nextOnChange = vi.fn();
    const external = '<h2 onclick="bad()">External</h2>';
    rerender(<LitBlogsEditor value={external} onChange={nextOnChange} editorFontSize="medium" />);
    expect(mocks.editor.commands.setContent).toHaveBeenCalledTimes(1);
    expect(mocks.editor.commands.setContent).toHaveBeenCalledWith(
      sanitizeRichText(external, { mode: "editor" }),
      { emitUpdate: false },
    );
    expect(nextOnChange).not.toHaveBeenCalled();

    rerender(
      <LitBlogsEditor
        value='<h2 class="unsafe">External</h2>'
        onChange={nextOnChange}
        editorFontSize="medium"
      />,
    );
    expect(mocks.editor.commands.setContent).toHaveBeenCalledTimes(1);

    mocks.editor.setHtml("<p>After callback change</p>");
    act(() => mocks.options.onUpdate({ editor: mocks.editor }));
    expect(nextOnChange).toHaveBeenCalledWith("<p>After callback change</p>");
    expect(firstOnChange).toHaveBeenCalledTimes(1);
  });

  it("updates editability, passes media callbacks through, and keeps visual size out of serialized HTML", () => {
    const onInsertImage = vi.fn();
    const onInsertVideo = vi.fn();
    const onInsertPdf = vi.fn();
    const { rerender } = render(
      <LitBlogsEditor
        value="<p>Initial</p>"
        onChange={vi.fn()}
        editorFontSize="large"
        onInsertImage={onInsertImage}
        onInsertVideo={onInsertVideo}
        onInsertPdf={onInsertPdf}
      />,
    );

    expect(screen.getByTestId("litblogs-editor")).toHaveStyle({ "--editor-font-size": "16px" });
    expect(screen.getByTestId("editor-canvas")).toBeInTheDocument();
    expect(screen.getByRole("toolbar", { name: "Rich text formatting" })).toBeInTheDocument();
    expect(document.querySelector("iframe")).toBeNull();
    expect(mocks.toolbarProps).toMatchObject({
      disabled: false,
      editor: mocks.editor,
      onInsertImage,
      onInsertPdf,
      onInsertVideo,
    });
    expect(mocks.editor.getHTML()).not.toContain("--editor-font-size");

    rerender(
      <LitBlogsEditor
        value="<p>Initial</p>"
        onChange={vi.fn()}
        editorFontSize="small"
        disabled
      />,
    );

    expect(mocks.editor.setEditable).toHaveBeenCalledWith(false);
    expect(mocks.toolbarProps.disabled).toBe(true);
    expect(screen.getByTestId("litblogs-editor")).toHaveStyle({ "--editor-font-size": "13px" });
  });

  it("suppresses duplicate canonical update callbacks", () => {
    const onChange = vi.fn();
    render(<LitBlogsEditor value="<p>Initial</p>" onChange={onChange} editorFontSize="medium" />);

    mocks.editor.setHtml("<p>Same canonical output</p>");
    act(() => mocks.options.onUpdate({ editor: mocks.editor }));
    act(() => mocks.options.onUpdate({ editor: mocks.editor }));

    expect(onChange).toHaveBeenCalledTimes(1);
  });
});
