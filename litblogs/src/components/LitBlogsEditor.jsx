import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { EditorContent, useEditor } from "@tiptap/react";

import {
  EDITOR_UPLOAD_ACCEPT,
  editorAssetKind,
  extractEditorDataImages,
  insertEditorAsset,
  uploadEditorAsset,
} from "../editor/editorUploads.js";
import { createRichTextExtensions } from "../editor/richTextSchema.js";
import { MAX_POST_HTML_LENGTH } from "../utils/postRequestContract.js";
import { normalizeRichTextUrl, sanitizeRichText } from "../utils/richTextSecurity.js";
import { getEditorFontSizePx } from "../utils/userSettings.js";
import LitBlogsEditorToolbar from "./LitBlogsEditorToolbar.jsx";
import "../styles/litblogs-editor.css";
import "../styles/rich-text-content.css";

const sanitizeImportedHtml = (value) => sanitizeRichText(value || "", { mode: "editor" });
const sanitizeSerializedHtml = (value) => sanitizeRichText(value || "");
const UPLOAD_LABELS = Object.freeze({ image: "image", pdf: "PDF", video: "video" });
const SAFE_UPLOAD_ERRORS = new Set([
  "Choose a file with a safe file name.",
  "Choose a supported file type.",
  "Choose a supported upload type.",
  "Choose a valid file to upload.",
  "The selected file is empty or invalid.",
  "The selected file is too large.",
  "The server returned an invalid upload response.",
  "Upload failed. Please try again.",
]);
const DIALOG_FOCUSABLE_SELECTOR = [
  'a[href]',
  'button:not([disabled])',
  'input:not([disabled]):not([type="hidden"])',
  'select:not([disabled])',
  'textarea:not([disabled])',
  '[tabindex]:not([tabindex="-1"])',
].join(',');

const containDialogFocus = (event, dialog) => {
  if (event.key !== "Tab" || !dialog) return;
  const focusable = [...dialog.querySelectorAll(DIALOG_FOCUSABLE_SELECTOR)]
    .filter((element) => !element.hidden && element.getAttribute("aria-hidden") !== "true");
  if (!focusable.length) {
    event.preventDefault();
    dialog.focus();
    return;
  }

  const first = focusable[0];
  const last = focusable[focusable.length - 1];
  if (event.shiftKey && (document.activeElement === first || !dialog.contains(document.activeElement))) {
    event.preventDefault();
    last.focus();
  } else if (!event.shiftKey && document.activeElement === last) {
    event.preventDefault();
    first.focus();
  }
};

const transferFiles = (transfer) => {
  const files = [...(transfer?.files || [])];
  for (const item of transfer?.items || []) {
    if (item?.kind !== "file" || typeof item.getAsFile !== "function") continue;
    const file = item.getAsFile();
    if (file && !files.includes(file)) files.push(file);
  }
  return files;
};

const LitBlogsEditor = ({
  value = "",
  onChange,
  editorFontSize = "medium",
  disabled = false,
  onUploadStateChange,
  onContentLimitChange,
  onInsertImage,
  onInsertVideo,
  onInsertPdf,
}) => {
  const onChangeRef = useRef(onChange);
  const onUploadStateChangeRef = useRef(onUploadStateChange);
  const onContentLimitChangeRef = useRef(onContentLimitChange);
  const editorRef = useRef(null);
  const editorRootRef = useRef(null);
  const imageInputRef = useRef(null);
  const imageDialogRef = useRef(null);
  const imageDialogInvokerRef = useRef(null);
  const imageUrlInputRef = useRef(null);
  const videoInputRef = useRef(null);
  const pdfInputRef = useRef(null);
  const activeUploadsRef = useRef(new Set());
  const transferHandlerRef = useRef(() => false);
  const mountedRef = useRef(true);
  const disabledRef = useRef(disabled);
  const initialContentRef = useRef(null);
  const lastImportedRef = useRef(null);
  const lastEmittedRef = useRef(null);
  const [uploadError, setUploadError] = useState("");
  const [uploadState, setUploadState] = useState(null);
  const [imageDialogOpen, setImageDialogOpen] = useState(false);
  const [imageUrl, setImageUrl] = useState("");
  const [imageDescription, setImageDescription] = useState("");

  const closeImageDialog = useCallback(() => {
    setImageDialogOpen(false);
    const returnTarget = imageDialogInvokerRef.current;
    imageDialogInvokerRef.current = null;
    if (
      returnTarget?.isConnected
      && !returnTarget.disabled
      && typeof returnTarget.focus === "function"
    ) {
      returnTarget.focus();
    } else {
      editorRootRef.current?.focus();
    }
  }, []);

  if (initialContentRef.current === null) {
    initialContentRef.current = sanitizeImportedHtml(value);
    lastImportedRef.current = initialContentRef.current;
  }

  useEffect(() => {
    onChangeRef.current = onChange;
  }, [onChange]);

  onUploadStateChangeRef.current = onUploadStateChange;
  onContentLimitChangeRef.current = onContentLimitChange;
  disabledRef.current = disabled;

  const reportContentLimit = useCallback((rawHtml) => {
    const length = typeof rawHtml === "string" ? rawHtml.length : 0;
    onContentLimitChangeRef.current?.({
      length,
      limit: MAX_POST_HTML_LENGTH,
      overLimit: length > MAX_POST_HTML_LENGTH,
    });
  }, []);

  useEffect(() => {
    const activeUploads = activeUploadsRef.current;
    mountedRef.current = true;
    return () => {
      mountedRef.current = false;
      for (const controller of activeUploads) controller.abort();
      activeUploads.clear();
      onUploadStateChangeRef.current?.(false);
    };
  }, []);

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
      handlePaste: (_view, event) => transferHandlerRef.current(event, false),
      handleDrop: (_view, event, _slice, moved) => transferHandlerRef.current(event, moved),
    },
    onUpdate: ({ editor: updatedEditor }) => {
      const rawHtml = updatedEditor.getHTML();
      reportContentLimit(rawHtml);
      if (rawHtml.length > MAX_POST_HTML_LENGTH) return;
      const canonicalHtml = sanitizeSerializedHtml(rawHtml);
      if (canonicalHtml === lastEmittedRef.current) return;
      lastEmittedRef.current = canonicalHtml;
      lastImportedRef.current = canonicalHtml;
      if (typeof onChangeRef.current === "function") {
        onChangeRef.current(canonicalHtml);
      }
    },
  }, [extensions]);

  editorRef.current = editor;

  useEffect(() => {
    if (editor) reportContentLimit(editor.getHTML());
  }, [editor, reportContentLimit]);

  const runUpload = useCallback(async (kind, file) => {
    if (disabledRef.current || !editorRef.current || !mountedRef.current) return false;
    const controller = new AbortController();
    activeUploadsRef.current.add(controller);
    onUploadStateChangeRef.current?.(true);
    setUploadState({ kind, progress: 0 });
    try {
      const asset = await uploadEditorAsset({
        file,
        kind,
        signal: controller.signal,
        onProgress: (progress) => {
          if (!mountedRef.current || controller.signal.aborted) return;
          setUploadState({
            kind,
            progress: Math.max(0, Math.min(100, Math.round(progress))),
          });
        },
      });
      if (!mountedRef.current || controller.signal.aborted || disabledRef.current) return false;
      if (!insertEditorAsset(editorRef.current, asset)) {
        setUploadError("The uploaded file could not be added to the post.");
        return false;
      }
      return true;
    } catch (error) {
      if (controller.signal.aborted || error?.name === "AbortError" || error?.code === "ERR_CANCELED") {
        return false;
      }
      if (mountedRef.current) {
        setUploadError(
          SAFE_UPLOAD_ERRORS.has(error?.message)
            ? error.message
            : "Upload failed. Please try again.",
        );
      }
      return false;
    } finally {
      activeUploadsRef.current.delete(controller);
      if (mountedRef.current && activeUploadsRef.current.size === 0) {
        setUploadState(null);
        onUploadStateChangeRef.current?.(false);
      }
    }
  }, []);

  transferHandlerRef.current = (event, moved = false) => {
    if (moved) return false;
    const transfer = event?.clipboardData || event?.dataTransfer;
    const files = transferFiles(transfer);
    const hasTransferredFiles = files.length > 0;
    const extracted = hasTransferredFiles || typeof transfer?.getData !== "function"
      ? { files: [], rejected: false }
      : extractEditorDataImages(transfer.getData("text/html"));
    const preserveRichPaste = !hasTransferredFiles
      && (extracted.files.length > 0 || extracted.rejected);
    files.push(...extracted.files);
    if (!files.length && !extracted.rejected) return false;
    if (disabledRef.current) {
      if (!preserveRichPaste) event.preventDefault();
      return !preserveRichPaste;
    }

    const supported = [];
    let rejected = extracted.rejected;
    for (const file of files) {
      const kind = editorAssetKind(file);
      if (kind) supported.push([kind, file]);
      else rejected = true;
    }
    setUploadError(rejected ? "Choose a supported image, video, or PDF file." : "");
    void (async () => {
      for (const [kind, file] of supported) await runUpload(kind, file);
    })();
    if (preserveRichPaste) return false;
    event.preventDefault();
    return true;
  };

  useEffect(() => {
    if (!editor) return;
    const shouldBeEditable = !disabled;
    if (editor.isEditable !== shouldBeEditable) {
      editor.setEditable(shouldBeEditable);
    }
  }, [disabled, editor]);

  useEffect(() => {
    if (!disabled) return;
    for (const controller of activeUploadsRef.current) controller.abort();
    if (imageDialogOpen) closeImageDialog();
  }, [closeImageDialog, disabled, imageDialogOpen]);

  useEffect(() => {
    if (imageDialogOpen) imageUrlInputRef.current?.focus();
  }, [imageDialogOpen]);

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
    reportContentLimit(editor.getHTML());
    lastImportedRef.current = incomingHtml;
    lastEmittedRef.current = null;
  }, [editor, reportContentLimit, value]);

  const editorFontSizePx = getEditorFontSizePx(editorFontSize);
  const chooseImage = onInsertImage || (() => {
    imageDialogInvokerRef.current = document.activeElement;
    setUploadError("");
    setImageUrl("");
    setImageDescription("");
    setImageDialogOpen(true);
  });
  const chooseVideo = onInsertVideo || (() => videoInputRef.current?.click());
  const choosePdf = onInsertPdf || (() => pdfInputRef.current?.click());

  const uploadFromInput = (kind) => (event) => {
    const file = event.target.files?.[0];
    event.target.value = "";
    if (file) {
      setUploadError("");
      void runUpload(kind, file);
    }
  };

  const insertSchoolImage = () => {
    const normalizedUrl = normalizeRichTextUrl(imageUrl, "image");
    if (!normalizedUrl) {
      setUploadError("Images must use an upload from this school site.");
      return;
    }
    const name = imageDescription.trim() || "School image";
    if (!insertEditorAsset(editorRef.current, {
      kind: "image",
      mimeType: "",
      name,
      size: 0,
      url: normalizedUrl,
    })) {
      setUploadError("The image could not be added to the post.");
      return;
    }
    setUploadError("");
    closeImageDialog();
  };

  return (
    <div
      ref={editorRootRef}
      className={`litblogs-editor${disabled ? " litblogs-editor--disabled" : ""}`}
      data-testid="litblogs-editor"
      aria-disabled={disabled || undefined}
      aria-busy={Boolean(uploadState) || undefined}
      tabIndex={-1}
      onSubmit={(event) => {
        event.preventDefault();
        event.stopPropagation();
      }}
      style={{ "--editor-font-size": `${editorFontSizePx}px` }}
    >
      <LitBlogsEditorToolbar
        editor={editor}
        disabled={disabled}
        onInsertImage={chooseImage}
        onInsertVideo={chooseVideo}
        onInsertPdf={choosePdf}
      />
      {imageDialogOpen && (
        <div
          ref={imageDialogRef}
          className="litblogs-editor__image-dialog"
          role="dialog"
          aria-modal="true"
          aria-labelledby="litblogs-insert-image-title"
          onKeyDown={(event) => {
            if (event.key === "Escape") {
              event.preventDefault();
              event.stopPropagation();
              closeImageDialog();
              return;
            }
            if (
              event.key === "Enter"
              && event.target.matches("input")
              && !event.isComposing
              && !event.nativeEvent?.isComposing
            ) {
              event.preventDefault();
              event.stopPropagation();
              insertSchoolImage();
              return;
            }
            containDialogFocus(event, imageDialogRef.current);
          }}
        >
          <h3 id="litblogs-insert-image-title">Insert image</h3>
          <p>Upload a new image, or reuse an image already uploaded to this school site.</p>
          <button
            type="button"
            onClick={() => {
              closeImageDialog();
              imageInputRef.current?.click();
            }}
          >
            Upload from computer
          </button>
          <label>
            <span>School image URL</span>
            <input
              ref={imageUrlInputRef}
              type="text"
              inputMode="url"
              value={imageUrl}
              onChange={(event) => setImageUrl(event.target.value)}
              placeholder="/api/uploads/objects/…"
            />
          </label>
          <label>
            <span>Image description</span>
            <input
              type="text"
              maxLength={512}
              value={imageDescription}
              onChange={(event) => setImageDescription(event.target.value)}
            />
          </label>
          <div className="litblogs-editor__image-dialog-actions">
            <button type="button" onClick={closeImageDialog}>
              Cancel image
            </button>
            <button type="button" onClick={insertSchoolImage}>
              Insert school image
            </button>
          </div>
        </div>
      )}
      <input
        ref={imageInputRef}
        hidden
        type="file"
        accept={EDITOR_UPLOAD_ACCEPT.image}
        data-testid="editor-image-input"
        disabled={disabled}
        onChange={uploadFromInput("image")}
      />
      <input
        ref={videoInputRef}
        hidden
        type="file"
        accept={EDITOR_UPLOAD_ACCEPT.video}
        data-testid="editor-video-input"
        disabled={disabled}
        onChange={uploadFromInput("video")}
      />
      <input
        ref={pdfInputRef}
        hidden
        type="file"
        accept={EDITOR_UPLOAD_ACCEPT.pdf}
        data-testid="editor-pdf-input"
        disabled={disabled}
        onChange={uploadFromInput("pdf")}
      />
      {uploadState && (
        <div className="litblogs-editor__upload-status" role="status" aria-live="polite">
          Uploading {UPLOAD_LABELS[uploadState.kind]}… {uploadState.progress}%
        </div>
      )}
      {uploadError && (
        <div className="litblogs-editor__upload-error" role="alert">
          {uploadError}
        </div>
      )}
      <EditorContent
        className="litblogs-editor__canvas"
        data-testid="editor-canvas"
        editor={editor}
      />
    </div>
  );
};

export default LitBlogsEditor;
