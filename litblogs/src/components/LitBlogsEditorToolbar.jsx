import { useEffect, useRef, useState } from "react";

import {
  FONT_FAMILIES,
  FONT_SIZES,
  HIGHLIGHT_COLOR_PALETTE,
  PALETTE_RGB_ALIASES,
  TEXT_COLOR_PALETTE,
} from "../utils/richTextContract.js";
import { normalizeRichTextUrl } from "../utils/richTextSecurity.js";
import LitBlogsColorPalette from "./LitBlogsColorPalette.jsx";

const normalizeActiveColor = (value) => {
  if (typeof value !== "string") return null;
  const normalized = value.trim().toLowerCase();
  return PALETTE_RGB_ALIASES[normalized] || normalized || null;
};

const getWordCount = (editor) => {
  const words = editor?.storage?.characterCount?.words?.();
  return Number.isFinite(words) && words >= 0 ? words : 0;
};

const canRunCommand = (editor, disabled, command, args = [], afterCommand) => {
  if (!editor || disabled) return false;
  try {
    const chain = editor.can().chain().focus();
    if (typeof chain[command] !== "function") return false;
    const commandChain = chain[command](...args);
    if (typeof afterCommand === "function") afterCommand(commandChain);
    return Boolean(commandChain.run());
  } catch {
    return false;
  }
};

const runCommand = (editor, disabled, command, args = [], afterCommand) => {
  if (!canRunCommand(editor, disabled, command, args, afterCommand)) return false;
  const chain = editor.chain().focus();
  if (typeof chain[command] !== "function") return false;
  const commandChain = chain[command](...args);
  if (typeof afterCommand === "function") afterCommand(commandChain);
  return commandChain.run();
};

const clearNodesAfter = (chain) => chain.clearNodes();

const ToolbarButton = ({
  active,
  children,
  disabled,
  label,
  onClick,
}) => (
  <button
    type="button"
    className="litblogs-toolbar-button"
    aria-label={label}
    aria-pressed={typeof active === "boolean" ? active : undefined}
    disabled={disabled}
    onClick={onClick}
  >
    {children}
  </button>
);

const LitBlogsEditorToolbar = ({
  editor,
  disabled = false,
  onInsertImage,
  onInsertVideo,
  onInsertPdf,
}) => {
  const [, setRevision] = useState(0);
  const [linkOpen, setLinkOpen] = useState(false);
  const [linkValue, setLinkValue] = useState("");
  const [linkError, setLinkError] = useState("");
  const linkButtonRef = useRef(null);
  const linkInputRef = useRef(null);
  const globallyDisabled = disabled || !editor;
  const canSetFontFamily = canRunCommand(
    editor,
    disabled,
    "setFontFamily",
    [FONT_FAMILIES[0].cssValue],
  );
  const canUnsetFontFamily = canRunCommand(editor, disabled, "unsetFontFamily");
  const canSetFontSize = canRunCommand(
    editor,
    disabled,
    "setFontSize",
    [FONT_SIZES[0].cssValue],
  );
  const canUnsetFontSize = canRunCommand(editor, disabled, "unsetFontSize");
  const canSetLink = canRunCommand(editor, disabled, "setLink", [{ href: "/" }]);
  const canUnsetLink = canRunCommand(editor, disabled, "unsetLink");
  const canSetHighlight = canRunCommand(
    editor,
    disabled,
    "setHighlight",
    [{ color: "#fef3c7" }],
  );
  const canUnsetHighlight = canRunCommand(editor, disabled, "unsetHighlight");
  const hasActiveLink = editor?.isActive("link") || false;
  const linkDisabled = globallyDisabled
    || (!canSetLink && !(hasActiveLink && canUnsetLink));

  useEffect(() => {
    if (!editor) return undefined;
    const refresh = () => setRevision((revision) => revision + 1);
    editor.on("selectionUpdate", refresh);
    editor.on("transaction", refresh);
    return () => {
      editor.off("selectionUpdate", refresh);
      editor.off("transaction", refresh);
    };
  }, [editor]);

  useEffect(() => {
    if (linkOpen) linkInputRef.current?.focus();
  }, [linkOpen]);

  useEffect(() => {
    if (!linkDisabled) return;
    setLinkOpen(false);
    setLinkError("");
  }, [linkDisabled]);

  const isActive = (name, attributes) => editor?.isActive(name, attributes) || false;
  const activeTextStyle = editor?.getAttributes("textStyle") || {};
  const activeHighlight = editor?.getAttributes("highlight") || {};
  const activeFontFamily = activeTextStyle.fontFamily || "";
  const activeFontSize = activeTextStyle.fontSize || "";
  const activeTextColor = normalizeActiveColor(activeTextStyle.color);
  const activeHighlightColor = normalizeActiveColor(activeHighlight.color);
  const customFontFamily = activeFontFamily
    && !FONT_FAMILIES.some(({ cssValue }) => cssValue === activeFontFamily);
  const customFontSize = activeFontSize
    && !FONT_SIZES.some(({ cssValue }) => cssValue === activeFontSize);
  const fontFamilyDisabled = globallyDisabled
    || (!canSetFontFamily && !(activeFontFamily && canUnsetFontFamily));
  const fontSizeDisabled = globallyDisabled
    || (!canSetFontSize && !(activeFontSize && canUnsetFontSize));
  const highlightDisabled = globallyDisabled || !canSetHighlight || !canUnsetHighlight;
  const words = getWordCount(editor);

  const commandDisabled = (command, args, afterCommand) => (
    !canRunCommand(editor, disabled, command, args, afterCommand)
  );
  const command = (commandName, args = [], afterCommand) => () => {
    runCommand(editor, disabled, commandName, args, afterCommand);
  };

  const closeLinkDialog = () => {
    setLinkOpen(false);
    setLinkError("");
    queueMicrotask(() => linkButtonRef.current?.focus());
  };

  const openLinkDialog = () => {
    if (linkDisabled) return;
    setLinkValue(editor.getAttributes("link")?.href || "");
    setLinkError("");
    setLinkOpen(true);
  };

  const applyLink = () => {
    const safeHref = normalizeRichTextUrl(linkValue, "link");
    if (!safeHref) {
      setLinkError("Enter a safe HTTPS or local link");
      return;
    }
    if (!canRunCommand(editor, disabled, "setLink", [{ href: safeHref }])) {
      setLinkError("Link formatting is unavailable here");
      return;
    }
    runCommand(editor, disabled, "extendMarkRange", ["link"], (chain) => {
      chain.setLink({ href: safeHref });
    });
    closeLinkDialog();
  };

  const removeLink = () => {
    if (!canRunCommand(editor, disabled, "unsetLink")) return;
    runCommand(editor, disabled, "extendMarkRange", ["link"], (chain) => {
      chain.unsetLink();
    });
    closeLinkDialog();
  };

  const handleLinkKeyDown = (event) => {
    if (event.key === "Escape") {
      event.preventDefault();
      closeLinkDialog();
    } else if (event.key === "Enter" && event.target === linkInputRef.current) {
      event.preventDefault();
      applyLink();
    }
  };

  const invokeMediaCallback = (callback) => {
    if (globallyDisabled || typeof callback !== "function") return;
    editor.chain().focus().run();
    callback(editor);
  };

  return (
    <div
      className="litblogs-editor-toolbar"
      role="toolbar"
      aria-label="Rich text formatting"
      aria-disabled={globallyDisabled || undefined}
    >
      <div className="litblogs-toolbar-group" role="group" aria-label="Blocks">
        <ToolbarButton
          active={isActive("paragraph")}
          label="Paragraph"
          disabled={commandDisabled("setParagraph")}
          onClick={command("setParagraph")}
        >
          Paragraph
        </ToolbarButton>
        {[1, 2, 3, 4].map((level) => (
          <ToolbarButton
            key={level}
            active={isActive("heading", { level })}
            label={`Heading ${level}`}
            disabled={commandDisabled("toggleHeading", [{ level }])}
            onClick={command("toggleHeading", [{ level }])}
          >
            H{level}
          </ToolbarButton>
        ))}
        <ToolbarButton
          active={isActive("blockquote")}
          label="Blockquote"
          disabled={commandDisabled("toggleBlockquote")}
          onClick={command("toggleBlockquote")}
        >
          Quote
        </ToolbarButton>
      </div>

      <div className="litblogs-toolbar-group" role="group" aria-label="Typography">
        <label className="litblogs-toolbar-field">
          <span className="litblogs-visually-hidden">Font family</span>
          <select
            aria-label="Font family"
            value={activeFontFamily}
            disabled={fontFamilyDisabled}
            onChange={(event) => {
              const nextValue = event.target.value;
              runCommand(
                editor,
                disabled,
                nextValue ? "setFontFamily" : "unsetFontFamily",
                nextValue ? [nextValue] : [],
              );
            }}
          >
            <option value="" disabled={Boolean(activeFontFamily) && !canUnsetFontFamily}>
              Default font
            </option>
            {customFontFamily && (
              <option value={activeFontFamily} disabled>
                Custom font: {activeFontFamily}
              </option>
            )}
            {FONT_FAMILIES.map(({ label, cssValue }) => (
              <option key={label} value={cssValue} disabled={!canSetFontFamily}>{label}</option>
            ))}
          </select>
        </label>
        <label className="litblogs-toolbar-field">
          <span className="litblogs-visually-hidden">Font size</span>
          <select
            aria-label="Font size"
            value={activeFontSize}
            disabled={fontSizeDisabled}
            onChange={(event) => {
              const nextValue = event.target.value;
              runCommand(
                editor,
                disabled,
                nextValue ? "setFontSize" : "unsetFontSize",
                nextValue ? [nextValue] : [],
              );
            }}
          >
            <option value="" disabled={Boolean(activeFontSize) && !canUnsetFontSize}>
              Default size
            </option>
            {customFontSize && (
              <option value={activeFontSize} disabled>
                Custom size: {activeFontSize}
              </option>
            )}
            {FONT_SIZES.map(({ label, cssValue }) => (
              <option key={label} value={cssValue} disabled={!canSetFontSize}>{label}</option>
            ))}
          </select>
        </label>
        <LitBlogsColorPalette
          key={`text-color-${globallyDisabled || commandDisabled("setColor", ["#111827"]) ? "disabled" : "enabled"}`}
          label="Text color"
          colors={TEXT_COLOR_PALETTE}
          value={activeTextColor}
          disabled={globallyDisabled || commandDisabled("setColor", ["#111827"])}
          onChange={(value) => runCommand(
            editor,
            disabled,
            value ? "setColor" : "unsetColor",
            value ? [value] : [],
          )}
        />
        <LitBlogsColorPalette
          key={`highlight-color-${highlightDisabled ? "disabled" : "enabled"}`}
          label="Highlight color"
          colors={HIGHLIGHT_COLOR_PALETTE}
          value={activeHighlightColor}
          disabled={highlightDisabled}
          onChange={(value) => runCommand(
            editor,
            disabled,
            value ? "setHighlight" : "unsetHighlight",
            value ? [{ color: value }] : [],
          )}
        />
      </div>

      <div className="litblogs-toolbar-group" role="group" aria-label="Marks">
        {[
          ["Bold", "bold", "toggleBold"],
          ["Italic", "italic", "toggleItalic"],
          ["Underline", "underline", "toggleUnderline"],
          ["Strikethrough", "strike", "toggleStrike"],
        ].map(([label, mark, commandName]) => (
          <ToolbarButton
            key={label}
            active={isActive(mark)}
            label={label}
            disabled={commandDisabled(commandName)}
            onClick={command(commandName)}
          >
            {label}
          </ToolbarButton>
        ))}
        <ToolbarButton
          label="Clear formatting"
          disabled={commandDisabled("unsetAllMarks", [], clearNodesAfter)}
          onClick={command("unsetAllMarks", [], clearNodesAfter)}
        >
          Clear
        </ToolbarButton>
        <button
          ref={linkButtonRef}
          type="button"
          className="litblogs-toolbar-button"
          aria-label="Link"
          aria-pressed={isActive("link")}
          aria-haspopup="dialog"
          aria-expanded={linkOpen && !linkDisabled}
          disabled={linkDisabled}
          onClick={openLinkDialog}
        >
          Link
        </button>
      </div>

      <div className="litblogs-toolbar-group" role="group" aria-label="Alignment and lists">
        {[
          ["Align left", "left"],
          ["Align center", "center"],
          ["Align right", "right"],
        ].map(([label, alignment]) => (
          <ToolbarButton
            key={alignment}
            active={isActive({ textAlign: alignment })}
            label={label}
            disabled={commandDisabled("setTextAlign", [alignment])}
            onClick={command("setTextAlign", [alignment])}
          >
            {label}
          </ToolbarButton>
        ))}
        <ToolbarButton
          active={isActive("bulletList")}
          label="Bulleted list"
          disabled={commandDisabled("toggleBulletList")}
          onClick={command("toggleBulletList")}
        >
          Bullets
        </ToolbarButton>
        <ToolbarButton
          active={isActive("orderedList")}
          label="Numbered list"
          disabled={commandDisabled("toggleOrderedList")}
          onClick={command("toggleOrderedList")}
        >
          Numbered
        </ToolbarButton>
      </div>

      <div className="litblogs-toolbar-group" role="group" aria-label="Insert">
        <ToolbarButton
          label="Insert table"
          disabled={commandDisabled("insertTable", [{ rows: 3, cols: 3, withHeaderRow: true }])}
          onClick={command("insertTable", [{ rows: 3, cols: 3, withHeaderRow: true }])}
        >
          Table
        </ToolbarButton>
        <ToolbarButton
          label="Delete table"
          disabled={commandDisabled("deleteTable")}
          onClick={command("deleteTable")}
        >
          Delete table
        </ToolbarButton>
        <ToolbarButton
          label="Insert image"
          disabled={globallyDisabled || typeof onInsertImage !== "function"}
          onClick={() => invokeMediaCallback(onInsertImage)}
        >
          Image
        </ToolbarButton>
        <ToolbarButton
          label="Insert video"
          disabled={globallyDisabled || typeof onInsertVideo !== "function"}
          onClick={() => invokeMediaCallback(onInsertVideo)}
        >
          Video
        </ToolbarButton>
        <ToolbarButton
          label="Insert PDF attachment"
          disabled={globallyDisabled || typeof onInsertPdf !== "function"}
          onClick={() => invokeMediaCallback(onInsertPdf)}
        >
          PDF
        </ToolbarButton>
      </div>

      <div className="litblogs-toolbar-group" role="group" aria-label="History">
        <ToolbarButton
          label="Undo"
          disabled={commandDisabled("undo")}
          onClick={command("undo")}
        >
          Undo
        </ToolbarButton>
        <ToolbarButton
          label="Redo"
          disabled={commandDisabled("redo")}
          onClick={command("redo")}
        >
          Redo
        </ToolbarButton>
      </div>

      <span className="litblogs-editor-word-count" role="status" aria-live="polite">
        {words} {words === 1 ? "word" : "words"}
      </span>

      {linkOpen && !linkDisabled && (
        <div
          className="litblogs-link-dialog"
          role="dialog"
          aria-label="Edit link"
          onKeyDown={handleLinkKeyDown}
        >
          <form
            onSubmit={(event) => {
              event.preventDefault();
              applyLink();
            }}
          >
            <label>
              <span>Link URL</span>
              <input
                ref={linkInputRef}
                type="text"
                inputMode="url"
                disabled={!canSetLink}
                value={linkValue}
                aria-describedby={linkError ? "litblogs-link-error" : undefined}
                onChange={(event) => {
                  setLinkValue(event.target.value);
                  setLinkError("");
                }}
              />
            </label>
            {linkError && (
              <div id="litblogs-link-error" role="alert">{linkError}</div>
            )}
            <div className="litblogs-link-dialog__actions">
              <button type="button" disabled={!canSetLink} onClick={applyLink}>Apply link</button>
              <button
                type="button"
                disabled={!isActive("link") || !canUnsetLink}
                onClick={removeLink}
              >
                Remove link
              </button>
              <button type="button" onClick={closeLinkDialog}>Cancel</button>
            </div>
          </form>
        </div>
      )}
    </div>
  );
};

export default LitBlogsEditorToolbar;
