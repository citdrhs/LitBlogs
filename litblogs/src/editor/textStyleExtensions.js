import { Extension, getStyleProperty } from "@tiptap/core";
import Color from "@tiptap/extension-color";
import FontFamily from "@tiptap/extension-font-family";
import Highlight from "@tiptap/extension-highlight";
import { TextStyle } from "@tiptap/extension-text-style";
import {
  normalizeFontFamily,
  normalizeFontSize,
  normalizeImportedColor,
  normalizeImportedFontFamily,
  normalizeImportedFontSize,
  normalizePaletteColor,
} from "./editorContract.js";

const styleValue = (element, propertyName) => (
  getStyleProperty(element, propertyName) ?? element.style.getPropertyValue(propertyName)
);

const hasCanonicalTextStyle = (element) => (
  normalizeImportedColor(styleValue(element, "color"))
  || normalizeImportedFontFamily(styleValue(element, "font-family"))
  || normalizeImportedFontSize(styleValue(element, "font-size"))
);

const styleMark = (tagName, declarations) => {
  const element = document.createElement(tagName);
  const style = declarations.filter(Boolean).join("; ");
  // ProseMirror assigns string DOMOutputSpec styles through CSSOM, which turns
  // hex colors into rgb(...). A concrete element preserves the contract form.
  if (style) element.setAttribute("style", style);
  return { dom: element, contentDOM: element };
};

export const CanonicalTextStyle = TextStyle.extend({
  parseHTML() {
    const parentRules = this.parent?.() ?? [];
    return parentRules.map((rule) => ({
      ...rule,
      getAttrs: (element) => {
        const attributes = rule.getAttrs ? rule.getAttrs(element) : rule.attrs;
        if (attributes === false || !hasCanonicalTextStyle(element)) return false;
        return attributes ?? {};
      },
    }));
  },

  renderHTML({ mark }) {
    const color = normalizeImportedColor(mark.attrs.color);
    const fontFamily = normalizeImportedFontFamily(mark.attrs.fontFamily);
    const fontSize = normalizeImportedFontSize(mark.attrs.fontSize);
    return styleMark("span", [
      color && `color: ${color}`,
      fontFamily && `font-family: ${fontFamily}`,
      fontSize && `font-size: ${fontSize}`,
    ]);
  },
});

export const CanonicalColor = Color.extend({
  addGlobalAttributes() {
    return [{
      types: this.options.types,
      attributes: {
        color: {
          default: null,
          parseHTML: (element) => normalizeImportedColor(styleValue(element, "color")),
          renderHTML: ({ color }) => {
            const value = normalizeImportedColor(color);
            return value ? { style: `color: ${value}` } : {};
          },
        },
      },
    }];
  },

  addCommands() {
    return {
      setColor: (color) => ({ chain }) => {
        const value = normalizePaletteColor(color, "text");
        return value ? chain().setMark("textStyle", { color: value }).run() : false;
      },
      unsetColor: () => ({ chain }) => (
        chain().setMark("textStyle", { color: null }).removeEmptyTextStyle().run()
      ),
    };
  },
});

export const CanonicalFontFamily = FontFamily.extend({
  addGlobalAttributes() {
    return [{
      types: this.options.types,
      attributes: {
        fontFamily: {
          default: null,
          parseHTML: (element) => normalizeImportedFontFamily(styleValue(element, "font-family")),
          renderHTML: ({ fontFamily }) => {
            const value = normalizeImportedFontFamily(fontFamily);
            return value ? { style: `font-family: ${value}` } : {};
          },
        },
      },
    }];
  },

  addCommands() {
    return {
      setFontFamily: (fontFamily) => ({ chain }) => {
        const value = normalizeFontFamily(fontFamily);
        return value ? chain().setMark("textStyle", { fontFamily: value }).run() : false;
      },
      unsetFontFamily: () => ({ chain }) => (
        chain().setMark("textStyle", { fontFamily: null }).removeEmptyTextStyle().run()
      ),
    };
  },
});

export const CanonicalFontSize = Extension.create({
  name: "fontSize",

  addOptions() {
    return { types: ["textStyle"] };
  },

  addGlobalAttributes() {
    return [{
      types: this.options.types,
      attributes: {
        fontSize: {
          default: null,
          parseHTML: (element) => normalizeImportedFontSize(styleValue(element, "font-size")),
          renderHTML: ({ fontSize }) => {
            const value = normalizeImportedFontSize(fontSize);
            return value ? { style: `font-size: ${value}` } : {};
          },
        },
      },
    }];
  },

  addCommands() {
    return {
      setFontSize: (fontSize) => ({ chain }) => {
        const value = normalizeFontSize(fontSize);
        return value ? chain().setMark("textStyle", { fontSize: value }).run() : false;
      },
      unsetFontSize: () => ({ chain }) => (
        chain().setMark("textStyle", { fontSize: null }).removeEmptyTextStyle().run()
      ),
    };
  },
});

export const CanonicalHighlight = Highlight.extend({
  addAttributes() {
    return {
      color: {
        default: null,
        parseHTML: (element) => normalizeImportedColor(styleValue(element, "background-color")),
        renderHTML: ({ color }) => {
          const value = normalizeImportedColor(color);
          return value ? { style: `background-color: ${value}` } : {};
        },
      },
    };
  },

  parseHTML() {
    const parseBackground = (element) => {
      const rawColor = styleValue(element, "background-color");
      if (!rawColor) return {};
      const color = normalizeImportedColor(rawColor);
      return color ? { color } : false;
    };
    return [
      {
        tag: "mark",
        getAttrs: parseBackground,
      },
      {
        tag: "span[style]",
        consuming: false,
        getAttrs: (element) => {
          const rawColor = styleValue(element, "background-color");
          if (!rawColor) return false;
          return parseBackground(element);
        },
      },
    ];
  },

  renderHTML({ mark }) {
    const color = normalizeImportedColor(mark.attrs.color);
    return styleMark("mark", [color && `background-color: ${color}`]);
  },

  addCommands() {
    const commandAttributes = (attributes) => {
      if (!attributes || attributes.color === null || attributes.color === undefined) {
        return { color: null };
      }
      const color = normalizePaletteColor(attributes.color, "highlight");
      return color ? { color } : null;
    };
    return {
      setHighlight: (attributes) => ({ commands }) => {
        const normalized = commandAttributes(attributes);
        return normalized ? commands.setMark(this.name, normalized) : false;
      },
      toggleHighlight: (attributes) => ({ commands }) => {
        const normalized = commandAttributes(attributes);
        return normalized ? commands.toggleMark(this.name, normalized) : false;
      },
      unsetHighlight: () => ({ commands }) => commands.unsetMark(this.name),
    };
  },
});

export const isPaletteColorActive = (editor, kind, rawValue) => {
  const palette = kind === "highlight" ? "highlight" : "text";
  const expected = normalizePaletteColor(rawValue, palette);
  if (!editor || !expected) return false;
  const current = kind === "highlight"
    ? editor.getAttributes("highlight").color
    : editor.getAttributes("textStyle")[kind];
  return normalizePaletteColor(current, palette) === expected;
};
