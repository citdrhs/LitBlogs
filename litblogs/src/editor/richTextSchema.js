import CharacterCount from "@tiptap/extension-character-count";
import Link from "@tiptap/extension-link";
import Placeholder from "@tiptap/extension-placeholder";
import TextAlign from "@tiptap/extension-text-align";
import Underline from "@tiptap/extension-underline";
import StarterKit from "@tiptap/starter-kit";
import {
  isCanonicalUploadUrl,
  isExternalLink,
  normalizeLinkUrl,
  normalizePaletteColor,
  normalizeSafeText,
} from "./editorContract.js";
import { Attachment, CanonicalImage, Video } from "./mediaNodes.js";
import {
  CanonicalColor,
  CanonicalFontFamily,
  CanonicalFontSize,
  CanonicalHighlight,
  CanonicalTextStyle,
  isPaletteColorActive,
} from "./textStyleExtensions.js";
import {
  CanonicalTable,
  CanonicalTableCell,
  CanonicalTableHeader,
  CanonicalTableRow,
} from "./tableExtensions.js";

const SafeLink = Link.extend({
  addAttributes() {
    return {
      href: {
        default: null,
        parseHTML: (element) => normalizeLinkUrl(element.getAttribute("href")),
        rendered: false,
      },
      title: {
        default: null,
        parseHTML: (element) => normalizeSafeText(element.getAttribute("title"), 512),
        rendered: false,
      },
      target: { default: null, rendered: false },
      rel: { default: null, rendered: false },
    };
  },

  parseHTML() {
    return [{
      tag: "a[href]",
      getAttrs: (element) => (normalizeLinkUrl(element.getAttribute("href")) ? {} : false),
    }];
  },

  renderHTML({ mark }) {
    const href = normalizeLinkUrl(mark.attrs.href);
    if (!href) return ["span", {}, 0];
    const attributes = { href };
    const title = normalizeSafeText(mark.attrs.title, 512);
    if (title) attributes.title = title;
    if (isExternalLink(href)) {
      attributes.target = "_blank";
      attributes.rel = "noopener noreferrer";
    }
    return ["a", attributes, 0];
  },
});

export const createRichTextExtensions = ({
  placeholder = "Write something...",
  characterLimit,
} = {}) => [
  StarterKit.configure({
    heading: { levels: [1, 2, 3, 4, 5, 6] },
    link: false,
    trailingNode: false,
    underline: false,
  }),
  CanonicalTextStyle.configure({ mergeNestedSpanStyles: true }),
  CanonicalColor.configure({ types: ["textStyle"] }),
  CanonicalFontFamily.configure({ types: ["textStyle"] }),
  CanonicalFontSize.configure({ types: ["textStyle"] }),
  CanonicalHighlight.configure({ multicolor: true }),
  Underline,
  SafeLink.configure({
    autolink: false,
    linkOnPaste: false,
    openOnClick: false,
    HTMLAttributes: {},
    isAllowedUri: (url) => Boolean(normalizeLinkUrl(url)),
  }),
  TextAlign.configure({
    types: ["paragraph", "heading"],
    alignments: ["left", "center", "right", "justify"],
  }),
  CanonicalImage,
  Video,
  Attachment,
  CanonicalTable.configure({ resizable: false, renderWrapper: false }),
  CanonicalTableRow,
  CanonicalTableHeader,
  CanonicalTableCell,
  CharacterCount.configure(characterLimit ? { limit: characterLimit } : {}),
  Placeholder.configure({ placeholder }),
];

export {
  isCanonicalUploadUrl,
  isPaletteColorActive,
  normalizePaletteColor,
};
