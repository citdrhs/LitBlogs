import { act, fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";

import { FONT_FAMILIES, FONT_SIZES } from "../utils/richTextContract.js";
import LitBlogsEditorToolbar from "./LitBlogsEditorToolbar.jsx";

const createFakeEditor = ({
  active = {},
  attributes = {},
  canRun = {},
  words = 7,
} = {}) => {
  const calls = [];
  const listeners = new Map();

  const createChain = (dryRun) => {
    const pending = [];
    const chain = new Proxy({}, {
      get(_target, property) {
        if (property === "run") {
          return () => {
            const command = [...pending]
              .reverse()
              .find(({ name }) => name !== "focus")?.name;
            if (dryRun) return canRun[command] ?? true;
            calls.push(...pending);
            return true;
          };
        }
        return (...args) => {
          pending.push({ name: String(property), args });
          return chain;
        };
      },
    });
    return chain;
  };

  const editor = {
    active,
    attributes,
    calls,
    words,
    chain: vi.fn(() => createChain(false)),
    can: vi.fn(() => ({ chain: () => createChain(true) })),
    getAttributes: vi.fn((name) => editor.attributes[name] || {}),
    isActive: vi.fn((name, requestedAttributes) => {
      if (typeof name === "object") {
        return editor.active[`textAlign:${name.textAlign}`] || false;
      }
      if (name === "heading") {
        return editor.active[`heading:${requestedAttributes?.level}`] || false;
      }
      return editor.active[name] || false;
    }),
    storage: {
      characterCount: {
        words: () => editor.words,
      },
    },
    on: vi.fn((event, callback) => {
      const callbacks = listeners.get(event) || new Set();
      callbacks.add(callback);
      listeners.set(event, callbacks);
    }),
    off: vi.fn((event, callback) => listeners.get(event)?.delete(callback)),
    emit(event) {
      listeners.get(event)?.forEach((callback) => callback());
    },
  };

  return editor;
};

const expectCommand = (editor, name, args = []) => {
  expect(editor.calls).toContainEqual({ name: "focus", args: [] });
  expect(editor.calls).toContainEqual({ name, args });
  editor.calls.splice(0);
};

describe("LitBlogsEditorToolbar", () => {
  it("exposes selection-aware controls, exact editor choices, RGB palette state, and word count", () => {
    const editor = createFakeEditor({
      active: {
        bold: true,
        "heading:2": true,
        "textAlign:center": true,
      },
      attributes: {
        textStyle: {
          color: "rgb(29, 78, 216)",
          fontFamily: FONT_FAMILIES[2].cssValue,
          fontSize: FONT_SIZES[2].cssValue,
        },
        highlight: { color: "rgb(254, 243, 199)" },
      },
      words: 23,
    });

    render(<LitBlogsEditorToolbar editor={editor} />);

    expect(screen.getByRole("toolbar", { name: "Rich text formatting" })).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Bold" })).toHaveAttribute("aria-pressed", "true");
    expect(screen.getByRole("button", { name: "Heading 2" })).toHaveAttribute("aria-pressed", "true");
    expect(screen.getByRole("button", { name: "Align center" })).toHaveAttribute("aria-pressed", "true");
    expect(screen.getByRole("combobox", { name: "Font family" })).toHaveValue(FONT_FAMILIES[2].cssValue);
    expect(screen.getByRole("combobox", { name: "Font size" })).toHaveValue(FONT_SIZES[2].cssValue);
    expect(screen.getByRole("combobox", { name: "Font family" }).querySelectorAll("option")).toHaveLength(
      FONT_FAMILIES.length + 1,
    );
    expect(screen.getByRole("combobox", { name: "Font size" }).querySelectorAll("option")).toHaveLength(
      FONT_SIZES.length + 1,
    );
    expect(screen.getByRole("button", { name: "Text color: Blue" })).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Highlight color: Amber" })).toBeInTheDocument();
    expect(screen.getByRole("status")).toHaveTextContent("23 words");
    screen.getAllByRole("button").forEach((button) => expect(button).toHaveAttribute("type", "button"));
  });

  it("reports safe legacy font and size values honestly when they are outside the menus", () => {
    const editor = createFakeEditor({
      attributes: {
        textStyle: {
          fontFamily: "Legacy Serif, serif",
          fontSize: "18px",
        },
      },
    });

    render(<LitBlogsEditorToolbar editor={editor} />);

    const family = screen.getByRole("combobox", { name: "Font family" });
    const size = screen.getByRole("combobox", { name: "Font size" });
    expect(family).toHaveValue("Legacy Serif, serif");
    expect(within(family).getByRole("option", { name: "Custom font: Legacy Serif, serif" }))
      .toBeDisabled();
    expect(size).toHaveValue("18px");
    expect(within(size).getByRole("option", { name: "Custom size: 18px" })).toBeDisabled();
  });

  it.each([
    ["Paragraph", "setParagraph", []],
    ["Heading 1", "toggleHeading", [{ level: 1 }]],
    ["Heading 2", "toggleHeading", [{ level: 2 }]],
    ["Heading 3", "toggleHeading", [{ level: 3 }]],
    ["Heading 4", "toggleHeading", [{ level: 4 }]],
    ["Blockquote", "toggleBlockquote", []],
    ["Bold", "toggleBold", []],
    ["Italic", "toggleItalic", []],
    ["Underline", "toggleUnderline", []],
    ["Strikethrough", "toggleStrike", []],
    ["Clear formatting", "unsetAllMarks", []],
    ["Align left", "setTextAlign", ["left"]],
    ["Align center", "setTextAlign", ["center"]],
    ["Align right", "setTextAlign", ["right"]],
    ["Bulleted list", "toggleBulletList", []],
    ["Numbered list", "toggleOrderedList", []],
    ["Insert table", "insertTable", [{ rows: 3, cols: 3, withHeaderRow: true }]],
    ["Delete table", "deleteTable", []],
    ["Undo", "undo", []],
    ["Redo", "redo", []],
  ])("runs the %s command after restoring editor focus", (label, command, args) => {
    const editor = createFakeEditor();
    render(<LitBlogsEditorToolbar editor={editor} />);

    fireEvent.click(screen.getByRole("button", { name: label }));

    if (command === "unsetAllMarks") {
      expect(editor.calls).toContainEqual({ name: "clearNodes", args: [] });
    }
    expectCommand(editor, command, args);
  });

  it("applies and clears font, size, text-color, and highlight choices", () => {
    const editor = createFakeEditor();
    render(<LitBlogsEditorToolbar editor={editor} />);

    const family = screen.getByRole("combobox", { name: "Font family" });
    fireEvent.change(family, { target: { value: FONT_FAMILIES[4].cssValue } });
    expectCommand(editor, "setFontFamily", [FONT_FAMILIES[4].cssValue]);
    fireEvent.change(family, { target: { value: "" } });
    expectCommand(editor, "unsetFontFamily");

    const size = screen.getByRole("combobox", { name: "Font size" });
    fireEvent.change(size, { target: { value: FONT_SIZES[8].cssValue } });
    expectCommand(editor, "setFontSize", [FONT_SIZES[8].cssValue]);
    fireEvent.change(size, { target: { value: "" } });
    expectCommand(editor, "unsetFontSize");

    fireEvent.click(screen.getByRole("button", { name: /Text color:/ }));
    fireEvent.click(screen.getByRole("button", { name: "Blue #1d4ed8" }));
    expectCommand(editor, "setColor", ["#1d4ed8"]);

    fireEvent.click(screen.getByRole("button", { name: /Highlight color:/ }));
    fireEvent.click(screen.getByRole("button", { name: "Purple #ddd6fe" }));
    expectCommand(editor, "setHighlight", [{ color: "#ddd6fe" }]);
    fireEvent.click(screen.getByRole("button", { name: /Highlight color:/ }));
    fireEvent.click(screen.getByRole("button", { name: "Clear highlight" }));
    expectCommand(editor, "unsetHighlight");
  });

  it("exposes only font actions allowed at the current selection", () => {
    const editor = createFakeEditor({
      attributes: {
        textStyle: {
          fontFamily: "Legacy Serif, serif",
          fontSize: "18px",
        },
      },
      canRun: {
        setFontFamily: false,
        setFontSize: false,
        unsetFontFamily: true,
        unsetFontSize: true,
      },
    });
    render(<LitBlogsEditorToolbar editor={editor} />);

    const family = screen.getByRole("combobox", { name: "Font family" });
    const size = screen.getByRole("combobox", { name: "Font size" });
    expect(family).toBeEnabled();
    expect(size).toBeEnabled();
    expect(within(family).getByRole("option", { name: "Default font" })).toBeEnabled();
    expect(within(size).getByRole("option", { name: "Default size" })).toBeEnabled();
    FONT_FAMILIES.forEach(({ label }) => {
      expect(within(family).getByRole("option", { name: label })).toBeDisabled();
    });
    FONT_SIZES.forEach(({ label }) => {
      expect(within(size).getByRole("option", { name: label })).toBeDisabled();
    });

    fireEvent.change(family, { target: { value: FONT_FAMILIES[0].cssValue } });
    fireEvent.change(size, { target: { value: FONT_SIZES[0].cssValue } });
    expect(editor.calls).toEqual([]);
    fireEvent.change(family, { target: { value: "" } });
    expectCommand(editor, "unsetFontFamily");
    fireEvent.change(size, { target: { value: "" } });
    expectCommand(editor, "unsetFontSize");
  });

  it("provides a keyboard-operable safe link dialog with apply, remove, cancel, and focus return", async () => {
    const editor = createFakeEditor({
      active: { link: true },
      attributes: { link: { href: "/classes/42" } },
    });
    render(<LitBlogsEditorToolbar editor={editor} />);

    const trigger = screen.getByRole("button", { name: "Link" });
    expect(trigger).toHaveAttribute("aria-pressed", "true");
    fireEvent.click(trigger);
    const dialog = screen.getByRole("dialog", { name: "Edit link" });
    expect(dialog).not.toHaveAttribute("aria-modal", "true");
    within(dialog).getAllByRole("button").forEach((button) => {
      expect(button).toHaveAttribute("type", "button");
    });
    const input = within(dialog).getByRole("textbox", { name: "Link URL" });
    await waitFor(() => expect(input).toHaveFocus());

    fireEvent.change(input, { target: { value: "javascript:alert(1)" } });
    fireEvent.keyDown(input, { key: "Enter" });
    expect(within(dialog).getByRole("alert")).toHaveTextContent("Enter a safe HTTPS or local link");
    expect(editor.calls).not.toContainEqual(expect.objectContaining({ name: "setLink" }));

    fireEvent.change(input, { target: { value: "/lessons/today" } });
    fireEvent.keyDown(input, { key: "Enter" });
    expectCommand(editor, "setLink", [{ href: "/lessons/today" }]);
    await waitFor(() => expect(trigger).toHaveFocus());

    fireEvent.click(trigger);
    fireEvent.click(screen.getByRole("button", { name: "Remove link" }));
    expectCommand(editor, "unsetLink");
    await waitFor(() => expect(trigger).toHaveFocus());

    fireEvent.click(trigger);
    fireEvent.keyDown(screen.getByRole("dialog", { name: "Edit link" }), { key: "Escape" });
    expect(screen.queryByRole("dialog", { name: "Edit link" })).not.toBeInTheDocument();
    await waitFor(() => expect(trigger).toHaveFocus());
  });

  it("accepts safe local links through the native Apply action", () => {
    const editor = createFakeEditor();
    render(<LitBlogsEditorToolbar editor={editor} />);

    fireEvent.click(screen.getByRole("button", { name: "Link" }));
    const input = screen.getByRole("textbox", { name: "Link URL" });
    expect(input).toHaveAttribute("type", "text");
    fireEvent.change(input, { target: { value: "/classes/42?tab=posts" } });
    fireEvent.click(screen.getByRole("button", { name: "Apply link" }));

    expect(editor.calls).toContainEqual({
      name: "setLink",
      args: [{ href: "/classes/42?tab=posts" }],
    });
  });

  it("invokes first-party media callbacks without embedding upload behavior in the toolbar", () => {
    const editor = createFakeEditor();
    const onInsertImage = vi.fn();
    const onInsertVideo = vi.fn();
    const onInsertPdf = vi.fn();
    render(
      <LitBlogsEditorToolbar
        editor={editor}
        onInsertImage={onInsertImage}
        onInsertVideo={onInsertVideo}
        onInsertPdf={onInsertPdf}
      />,
    );

    fireEvent.click(screen.getByRole("button", { name: "Insert image" }));
    fireEvent.click(screen.getByRole("button", { name: "Insert video" }));
    fireEvent.click(screen.getByRole("button", { name: "Insert PDF attachment" }));

    expect(onInsertImage).toHaveBeenCalledWith(editor);
    expect(onInsertVideo).toHaveBeenCalledWith(editor);
    expect(onInsertPdf).toHaveBeenCalledWith(editor);
  });

  it("updates selection state and word count from editor events", () => {
    const editor = createFakeEditor({ words: 1 });
    render(<LitBlogsEditorToolbar editor={editor} />);

    expect(screen.getByRole("button", { name: "Bold" })).toHaveAttribute("aria-pressed", "false");
    expect(screen.getByRole("status")).toHaveTextContent("1 word");

    editor.active.bold = true;
    editor.words = 2;
    act(() => editor.emit("transaction"));

    expect(screen.getByRole("button", { name: "Bold" })).toHaveAttribute("aria-pressed", "true");
    expect(screen.getByRole("status")).toHaveTextContent("2 words");
  });

  it("honors both global disabled state and editor can() results", () => {
    const editor = createFakeEditor({
      canRun: {
        setFontFamily: false,
        setHighlight: false,
        setFontSize: false,
        setLink: false,
        unsetAllMarks: true,
        unsetFontFamily: true,
        unsetHighlight: true,
        unsetFontSize: true,
        // unsetLink can be a valid no-op at an atomic node; it must not make
        // the Link control available when there is no active link to remove.
        unsetLink: true,
        clearNodes: false,
        undo: false,
      },
    });
    const onInsertImage = vi.fn();
    const { rerender } = render(
      <LitBlogsEditorToolbar editor={editor} onInsertImage={onInsertImage} />,
    );

    expect(screen.getByRole("button", { name: "Undo" })).toBeDisabled();
    expect(screen.getByRole("button", { name: "Bold" })).toBeEnabled();
    expect(screen.getByRole("combobox", { name: "Font family" })).toBeDisabled();
    expect(screen.getByRole("combobox", { name: "Font size" })).toBeDisabled();
    expect(screen.getByRole("button", { name: "Link" })).toBeDisabled();
    expect(screen.getByRole("button", { name: /Highlight color:/ })).toBeDisabled();
    expect(screen.getByRole("button", { name: "Clear formatting" })).toBeDisabled();

    rerender(<LitBlogsEditorToolbar editor={editor} disabled onInsertImage={onInsertImage} />);

    screen.getAllByRole("button").forEach((button) => expect(button).toBeDisabled());
    screen.getAllByRole("combobox").forEach((select) => expect(select).toBeDisabled());
    fireEvent.click(screen.getByRole("button", { name: "Insert image" }));
    expect(onInsertImage).not.toHaveBeenCalled();
  });

  it("closes open link and color controls when disabled and does not reopen or run stale actions", () => {
    const editor = createFakeEditor();
    const { rerender } = render(<LitBlogsEditorToolbar editor={editor} />);

    fireEvent.click(screen.getByRole("button", { name: "Link" }));
    expect(screen.getByRole("dialog", { name: "Edit link" })).toBeInTheDocument();

    rerender(<LitBlogsEditorToolbar editor={editor} disabled />);
    expect(screen.queryByRole("dialog", { name: "Edit link" })).not.toBeInTheDocument();

    rerender(<LitBlogsEditorToolbar editor={editor} />);
    expect(screen.queryByRole("dialog", { name: "Edit link" })).not.toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: /Text color:/ }));
    const staleSwatch = screen.getByRole("button", { name: "Blue #1d4ed8" });
    editor.calls.splice(0);

    rerender(<LitBlogsEditorToolbar editor={editor} disabled />);
    expect(screen.queryByRole("dialog", { name: "Text color palette" })).not.toBeInTheDocument();
    expect(screen.getByRole("button", { name: /Text color:/ })).toBeDisabled();
    fireEvent.click(staleSwatch);
    expect(editor.calls).toEqual([]);
  });
});
