import {
  Table,
  TableCell,
  TableHeader,
  TableRow,
} from "@tiptap/extension-table";
import { normalizeSafeText, normalizeSpan } from "./editorContract.js";

const cellAttributes = (includeScope = false) => {
  const attributes = {
    colspan: { default: 1 },
    rowspan: { default: 1 },
    colwidth: {
      default: null,
      parseHTML: () => null,
      rendered: false,
    },
  };
  if (includeScope) {
    attributes.scope = {
      default: null,
      parseHTML: (element) => {
        const value = element.getAttribute("scope")?.toLowerCase();
        return ["col", "colgroup", "row", "rowgroup"].includes(value) ? value : null;
      },
    };
  }
  return attributes;
};

const renderCell = (tagName, node, includeScope = false) => {
  const colspan = normalizeSpan(node.attrs.colspan);
  const rowspan = normalizeSpan(node.attrs.rowspan);
  const attributes = {};
  if (colspan > 1) attributes.colspan = colspan;
  if (rowspan > 1) attributes.rowspan = rowspan;
  if (includeScope) {
    const scope = normalizeSafeText(node.attrs.scope, 16)?.toLowerCase();
    if (["col", "colgroup", "row", "rowgroup"].includes(scope)) attributes.scope = scope;
  }
  return [tagName, attributes, 0];
};

export const CanonicalTable = Table.extend({
  renderHTML() {
    return ["table", {}, ["tbody", 0]];
  },
});

export const CanonicalTableRow = TableRow.extend({
  renderHTML() {
    return ["tr", {}, 0];
  },
});

export const CanonicalTableCell = TableCell.extend({
  addAttributes() {
    return cellAttributes();
  },
  renderHTML({ node }) {
    return renderCell("td", node);
  },
});

export const CanonicalTableHeader = TableHeader.extend({
  addAttributes() {
    return cellAttributes(true);
  },
  renderHTML({ node }) {
    return renderCell("th", node, true);
  },
});
