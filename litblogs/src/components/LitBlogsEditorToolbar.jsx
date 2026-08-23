import { useCallback, useEffect, useRef, useState } from "react";
import {
  FaAlignCenter,
  FaAlignLeft,
  FaAlignRight,
  FaBold,
  FaCaretDown,
  FaFilePdf,
  FaImage,
  FaItalic,
  FaLink,
  FaListOl,
  FaListUl,
  FaRedo,
  FaRemoveFormat,
  FaStrikethrough,
  FaTable,
  FaTrashAlt,
  FaUnderline,
  FaUndo,
  FaVideo,
} from "react-icons/fa";

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

const BLOCK_OPTIONS = Object.freeze([
  Object.freeze({ label: "Paragraph", shortLabel: "¶ Paragraph", value: "paragraph", command: "setParagraph" }),
  ...[1, 2, 3, 4].map((level) => Object.freeze({
    args: Object.freeze([{ level }]),
    label: `Heading ${level}`,
    shortLabel: `H${level}`,
    value: `heading-${level}`,
    command: "toggleHeading",
  })),
  Object.freeze({ label: "Quote", shortLabel: "❝ Quote", value: "blockquote", command: "toggleBlockquote" }),
]);

const ALIGNMENT_OPTIONS = Object.freeze([
  Object.freeze({ Icon: FaAlignLeft, label: "Align left", shortLabel: "Left", value: "left" }),
  Object.freeze({ Icon: FaAlignCenter, label: "Align center", shortLabel: "Center", value: "center" }),
  Object.freeze({ Icon: FaAlignRight, label: "Align right", shortLabel: "Right", value: "right" }),
]);

const AlignmentPicker = ({
  activeAlignment,
  disabled,
  disabledOptions,
  onChange,
}) => {
  const [open, setOpen] = useState(false);
  const containerRef = useRef(null);
  const triggerRef = useRef(null);
  const optionRefs = useRef([]);
  const activeIndex = Math.max(
    0,
    ALIGNMENT_OPTIONS.findIndex(({ value }) => value === activeAlignment),
  );
  const activeOption = ALIGNMENT_OPTIONS[activeIndex];
  const {
    center: centerDisabled,
    left: leftDisabled,
    right: rightDisabled,
  } = disabledOptions;

  const closeMenu = useCallback(({ restoreFocus = true } = {}) => {
    setOpen(false);
    if (restoreFocus) queueMicrotask(() => triggerRef.current?.focus());
  }, []);

  useEffect(() => {
    if (!disabled) return;
    setOpen(false);
  }, [disabled]);

  useEffect(() => {
    if (!open) return undefined;
    const activeOptionDisabled = activeOption.value === "left"
      ? leftDisabled
      : activeOption.value === "center"
        ? centerDisabled
        : rightDisabled;
    const preferredIndex = activeOptionDisabled
      ? ALIGNMENT_OPTIONS.findIndex(({ value }) => (
        value === "left" ? !leftDisabled : value === "center" ? !centerDisabled : !rightDisabled
      ))
      : activeIndex;
    optionRefs.current[preferredIndex]?.focus();

    const handlePointerDown = (event) => {
      if (!containerRef.current?.contains(event.target)) {
        closeMenu({ restoreFocus: false });
      }
    };
    document.addEventListener("pointerdown", handlePointerDown);
    return () => document.removeEventListener("pointerdown", handlePointerDown);
  }, [
    activeIndex,
    activeOption.value,
    centerDisabled,
    closeMenu,
    leftDisabled,
    open,
    rightDisabled,
  ]);

  const focusRelativeOption = (currentIndex, direction) => {
    const enabled = ALIGNMENT_OPTIONS
      .map(({ value }, index) => (disabledOptions[value] ? null : index))
      .filter((index) => index !== null);
    if (!enabled.length) return;
    const enabledPosition = enabled.indexOf(currentIndex);
    const nextPosition = enabledPosition < 0
      ? 0
      : (enabledPosition + direction + enabled.length) % enabled.length;
    optionRefs.current[enabled[nextPosition]]?.focus();
  };

  const chooseAlignment = (value) => {
    if (disabled || disabledOptions[value]) return;
    onChange(value);
    closeMenu();
  };

  const handleOptionKeyDown = (event, index, value) => {
    if (event.key === "Escape") {
      event.preventDefault();
      event.stopPropagation();
      closeMenu();
      return;
    }
    if (event.key === "Enter" || event.key === " ") {
      event.preventDefault();
      chooseAlignment(value);
      return;
    }
    if (!["ArrowDown", "ArrowUp", "Home", "End"].includes(event.key)) return;
    event.preventDefault();
    if (event.key === "Home" || event.key === "End") {
      const enabled = ALIGNMENT_OPTIONS
        .map(({ value: optionValue }, optionIndex) => (
          disabledOptions[optionValue] ? null : optionIndex
        ))
        .filter((optionIndex) => optionIndex !== null);
      optionRefs.current[event.key === "Home" ? enabled[0] : enabled.at(-1)]?.focus();
      return;
    }
    focusRelativeOption(index, event.key === "ArrowDown" ? 1 : -1);
  };

  const ActiveIcon = activeOption.Icon;
  const triggerLabel = `Text alignment: ${activeOption.shortLabel}`;

  return (
    <div
      ref={containerRef}
      className="litblogs-alignment-picker"
      onBlur={(event) => {
        if (!event.currentTarget.contains(event.relatedTarget)) {
          closeMenu({ restoreFocus: false });
        }
      }}
    >
      <button
        ref={triggerRef}
        type="button"
        className="litblogs-toolbar-button litblogs-toolbar-button--icon litblogs-toolbar-button--dropdown"
        aria-label={triggerLabel}
        aria-haspopup="menu"
        aria-expanded={open}
        disabled={disabled}
        title={triggerLabel}
        onClick={() => (open ? closeMenu({ restoreFocus: false }) : setOpen(true))}
        onKeyDown={(event) => {
          if (event.key !== "ArrowDown" && event.key !== "ArrowUp") return;
          event.preventDefault();
          setOpen(true);
        }}
      >
        <ActiveIcon aria-hidden="true" focusable="false" />
        <FaCaretDown aria-hidden="true" focusable="false" />
      </button>
      {open && !disabled && (
        <div className="litblogs-alignment-menu" role="menu" aria-label="Text alignment">
          {ALIGNMENT_OPTIONS.map(({ Icon, label, value }, index) => (
            <button
              key={value}
              ref={(element) => {
                optionRefs.current[index] = element;
              }}
              type="button"
              role="menuitemradio"
              aria-checked={activeAlignment === value}
              disabled={disabledOptions[value]}
              title={label}
              onClick={() => chooseAlignment(value)}
              onKeyDown={(event) => handleOptionKeyDown(event, index, value)}
            >
              <Icon aria-hidden="true" focusable="false" />
              <span>{label}</span>
            </button>
          ))}
        </div>
      )}
    </div>
  );
};

const ToolbarButton = ({
  active,
  children,
  disabled,
  label,
  onClick,
}) => (
  <button
    type="button"
    className="litblogs-toolbar-button litblogs-toolbar-button--icon"
    aria-label={label}
    aria-pressed={typeof active === "boolean" ? active : undefined}
    disabled={disabled}
    title={label}
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
  const blockOptions = BLOCK_OPTIONS.map((option) => ({
    ...option,
    disabled: commandDisabled(option.command, option.args || []),
  }));
  const activeHeading = [1, 2, 3, 4].find((level) => (
    isActive("heading", { level })
  ));
  const activeBlock = activeHeading
    ? `heading-${activeHeading}`
    : isActive("blockquote")
      ? "blockquote"
      : "paragraph";
  const disabledAlignments = Object.fromEntries(
    ALIGNMENT_OPTIONS.map(({ value }) => [
      value,
      commandDisabled("setTextAlign", [value]),
    ]),
  );
  const activeAlignment = ALIGNMENT_OPTIONS.find(({ value }) => (
    isActive({ textAlign: value })
  ))?.value || "left";

  const closeLinkDialog = ({ restoreFocus = true } = {}) => {
    setLinkOpen(false);
    setLinkError("");
    if (restoreFocus) {
      queueMicrotask(() => linkButtonRef.current?.focus());
    }
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
      event.stopPropagation();
      closeLinkDialog();
    } else if (event.key === "Enter" && event.target === linkInputRef.current) {
      event.preventDefault();
      applyLink();
    }
  };

  const handleLinkBlur = (event) => {
    if (!event.currentTarget.contains(event.relatedTarget)) {
      closeLinkDialog({ restoreFocus: false });
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
        <label className="litblogs-toolbar-field litblogs-toolbar-field--block">
          <span className="litblogs-visually-hidden">Block style</span>
          <select
            aria-label="Block style"
            title="Block style"
            value={activeBlock}
            disabled={globallyDisabled || blockOptions.every((option) => option.disabled)}
            onChange={(event) => {
              const option = blockOptions.find(({ value }) => value === event.target.value);
              if (!option || option.disabled) return;
              runCommand(editor, disabled, option.command, option.args || []);
            }}
          >
            {blockOptions.map((option) => (
              <option key={option.value} value={option.value} disabled={option.disabled}>
                {option.shortLabel}
              </option>
            ))}
          </select>
        </label>
      </div>

      <div className="litblogs-toolbar-group" role="group" aria-label="Typography">
        <label className="litblogs-toolbar-field litblogs-toolbar-field--font-family">
          <span className="litblogs-visually-hidden">Font family</span>
          <select
            aria-label="Font family"
            title="Font family"
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
        <label className="litblogs-toolbar-field litblogs-toolbar-field--font-size">
          <span className="litblogs-visually-hidden">Font size</span>
          <select
            aria-label="Font size"
            title="Font size"
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
          ["Bold", "bold", "toggleBold", FaBold],
          ["Italic", "italic", "toggleItalic", FaItalic],
          ["Underline", "underline", "toggleUnderline", FaUnderline],
          ["Strikethrough", "strike", "toggleStrike", FaStrikethrough],
        ].map(([label, mark, commandName, Icon]) => (
          <ToolbarButton
            key={label}
            active={isActive(mark)}
            label={label}
            disabled={commandDisabled(commandName)}
            onClick={command(commandName)}
          >
            <Icon aria-hidden="true" focusable="false" />
          </ToolbarButton>
        ))}
        <ToolbarButton
          label="Clear formatting"
          disabled={commandDisabled("unsetAllMarks", [], clearNodesAfter)}
          onClick={command("unsetAllMarks", [], clearNodesAfter)}
        >
          <FaRemoveFormat aria-hidden="true" focusable="false" />
        </ToolbarButton>
        <button
          ref={linkButtonRef}
          type="button"
          className="litblogs-toolbar-button litblogs-toolbar-button--icon"
          aria-label="Link"
          aria-pressed={isActive("link")}
          aria-haspopup="dialog"
          aria-expanded={linkOpen && !linkDisabled}
          disabled={linkDisabled}
          title="Link"
          onClick={openLinkDialog}
        >
          <FaLink aria-hidden="true" focusable="false" />
        </button>
      </div>

      <div className="litblogs-toolbar-group" role="group" aria-label="Alignment and lists">
        <AlignmentPicker
          activeAlignment={activeAlignment}
          disabled={globallyDisabled || Object.values(disabledAlignments).every(Boolean)}
          disabledOptions={disabledAlignments}
          onChange={(alignment) => runCommand(editor, disabled, "setTextAlign", [alignment])}
        />
        <ToolbarButton
          active={isActive("bulletList")}
          label="Bulleted list"
          disabled={commandDisabled("toggleBulletList")}
          onClick={command("toggleBulletList")}
        >
          <FaListUl aria-hidden="true" focusable="false" />
        </ToolbarButton>
        <ToolbarButton
          active={isActive("orderedList")}
          label="Numbered list"
          disabled={commandDisabled("toggleOrderedList")}
          onClick={command("toggleOrderedList")}
        >
          <FaListOl aria-hidden="true" focusable="false" />
        </ToolbarButton>
      </div>

      <div className="litblogs-toolbar-group" role="group" aria-label="Insert">
        <ToolbarButton
          label="Insert table"
          disabled={commandDisabled("insertTable", [{ rows: 3, cols: 3, withHeaderRow: true }])}
          onClick={command("insertTable", [{ rows: 3, cols: 3, withHeaderRow: true }])}
        >
          <FaTable aria-hidden="true" focusable="false" />
        </ToolbarButton>
        <ToolbarButton
          label="Delete table"
          disabled={commandDisabled("deleteTable")}
          onClick={command("deleteTable")}
        >
          <FaTrashAlt aria-hidden="true" focusable="false" />
        </ToolbarButton>
        <ToolbarButton
          label="Insert image"
          disabled={globallyDisabled || typeof onInsertImage !== "function"}
          onClick={() => invokeMediaCallback(onInsertImage)}
        >
          <FaImage aria-hidden="true" focusable="false" />
        </ToolbarButton>
        <ToolbarButton
          label="Insert video"
          disabled={globallyDisabled || typeof onInsertVideo !== "function"}
          onClick={() => invokeMediaCallback(onInsertVideo)}
        >
          <FaVideo aria-hidden="true" focusable="false" />
        </ToolbarButton>
        <ToolbarButton
          label="Insert PDF attachment"
          disabled={globallyDisabled || typeof onInsertPdf !== "function"}
          onClick={() => invokeMediaCallback(onInsertPdf)}
        >
          <FaFilePdf aria-hidden="true" focusable="false" />
        </ToolbarButton>
      </div>

      <div className="litblogs-toolbar-group" role="group" aria-label="History">
        <ToolbarButton
          label="Undo"
          disabled={commandDisabled("undo")}
          onClick={command("undo")}
        >
          <FaUndo aria-hidden="true" focusable="false" />
        </ToolbarButton>
        <ToolbarButton
          label="Redo"
          disabled={commandDisabled("redo")}
          onClick={command("redo")}
        >
          <FaRedo aria-hidden="true" focusable="false" />
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
          onBlur={handleLinkBlur}
          onKeyDown={handleLinkKeyDown}
        >
          <div className="litblogs-link-dialog__fields">
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
          </div>
        </div>
      )}
    </div>
  );
};

export default LitBlogsEditorToolbar;
