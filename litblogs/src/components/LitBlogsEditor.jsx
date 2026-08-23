import { useEffect, useMemo, useRef } from "react";
import { EditorContent, useEditor } from "@tiptap/react";

import { createRichTextExtensions } from "../editor/richTextSchema.js";
import { sanitizeRichText } from "../utils/richTextSecurity.js";
import { getEditorFontSizePx } from "../utils/userSettings.js";
import LitBlogsEditorToolbar from "./LitBlogsEditorToolbar.jsx";
import "../styles/litblogs-editor.css";
import "../styles/rich-text-content.css";

const sanitizeImportedHtml = (value) => sanitizeRichText(value || "", { mode: "editor" });
const sanitizeSerializedHtml = (value) => sanitizeRichText(value || "");

const LitBlogsEditor = ({
  value = "",
  onChange,
  editorFontSize = "medium",
  disabled = false,
  onInsertImage,
  onInsertVideo,
  onInsertPdf,
}) => {
  const onChangeRef = useRef(onChange);
  const initialContentRef = useRef(null);
  const lastImportedRef = useRef(null);
  const lastEmittedRef = useRef(null);

  if (initialContentRef.current === null) {
    initialContentRef.current = sanitizeImportedHtml(value);
    lastImportedRef.current = initialContentRef.current;
  }

  useEffect(() => {
    onChangeRef.current = onChange;
  }, [onChange]);

  const extensions = useMemo(() => createRichTextExtensions({
    placeholder: "Write something...",
  }), []);

  const editor = useEditor({
    extensions,
    content: initialContentRef.current,
    editable: !disabled,
    editorProps: {
      attributes: {
        "aria-label": "Post content",
        "aria-multiline": "true",
        class: "litblogs-editor__document rich-text-content",
        role: "textbox",
        spellcheck: "true",
      },
      transformPastedHTML: sanitizeImportedHtml,
    },
    onUpdate: ({ editor: updatedEditor }) => {
      const canonicalHtml = sanitizeSerializedHtml(updatedEditor.getHTML());
      if (canonicalHtml === lastEmittedRef.current) return;
      lastEmittedRef.current = canonicalHtml;
      lastImportedRef.current = canonicalHtml;
      if (typeof onChangeRef.current === "function") {
        onChangeRef.current(canonicalHtml);
      }
    },
  }, [extensions]);

  useEffect(() => {
    if (!editor) return;
    const shouldBeEditable = !disabled;
    if (editor.isEditable !== shouldBeEditable) {
      editor.setEditable(shouldBeEditable);
    }
  }, [disabled, editor]);

  useEffect(() => {
    if (!editor) return;
    const incomingHtml = sanitizeImportedHtml(value);
    const currentHtml = sanitizeSerializedHtml(editor.getHTML());
    if (
      incomingHtml === lastEmittedRef.current
      || incomingHtml === currentHtml
      || incomingHtml === lastImportedRef.current
    ) {
      lastImportedRef.current = incomingHtml;
      return;
    }

    editor.commands.setContent(incomingHtml, { emitUpdate: false });
    lastImportedRef.current = incomingHtml;
    lastEmittedRef.current = null;
  }, [editor, value]);

  const editorFontSizePx = getEditorFontSizePx(editorFontSize);

  return (
    <div
      className={`litblogs-editor${disabled ? " litblogs-editor--disabled" : ""}`}
      data-testid="litblogs-editor"
      aria-disabled={disabled || undefined}
      style={{ "--editor-font-size": `${editorFontSizePx}px` }}
    >
      <LitBlogsEditorToolbar
        editor={editor}
        disabled={disabled}
        onInsertImage={onInsertImage}
        onInsertVideo={onInsertVideo}
        onInsertPdf={onInsertPdf}
      />
      <EditorContent
        className="litblogs-editor__canvas"
        data-testid="editor-canvas"
        editor={editor}
      />
    </div>
  );
};

export default LitBlogsEditor;
