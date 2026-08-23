import { afterEach, describe, expect, it } from "vitest";
import { Editor } from "@tiptap/core";
import {
  FONT_FAMILIES,
  FONT_SIZES,
  HIGHLIGHT_COLOR_PALETTE,
  PALETTE_RGB_ALIASES,
  TEXT_COLOR_PALETTE,
} from "../utils/richTextContract.js";
import {
  createRichTextExtensions,
  isCanonicalUploadUrl,
  isPaletteColorActive,
  normalizePaletteColor,
} from "./richTextSchema.js";

const IMAGE_URL = "/api/uploads/objects/11/11111111111111111111111111111111.png";
const VIDEO_URL = "/api/uploads/objects/22/22222222222222222222222222222222.mp4";
const PDF_URL = "/api/uploads/objects/33/33333333333333333333333333333333.pdf";

const editors = [];

const createEditor = (content) => {
  const editor = new Editor({
    element: document.createElement("div"),
    extensions: createRichTextExtensions({ placeholder: "Write something" }),
    content,
  });
  editors.push(editor);
  return editor;
};

const parseHtml = (html) => new DOMParser().parseFromString(html, "text/html");

afterEach(() => {
  editors.splice(0).forEach((editor) => editor.destroy());
});

describe("createRichTextExtensions", () => {
  it("installs one canonical extension for every first-party schema capability", () => {
    const names = createRichTextExtensions().map((extension) => extension.name);

    expect(new Set(names).size).toBe(names.length);
    expect(names).toEqual(expect.arrayContaining([
      "starterKit",
      "textStyle",
      "color",
      "fontFamily",
      "fontSize",
      "highlight",
      "underline",
      "link",
      "textAlign",
      "image",
      "video",
      "attachment",
      "table",
      "tableRow",
      "tableCell",
      "tableHeader",
      "characterCount",
      "placeholder",
    ]));
  });

  it.each(FONT_SIZES)(
    "normalizes legacy $legacyValue font sizes to canonical $cssValue",
    ({ legacyValue, cssValue }) => {
      const editor = createEditor(`<p><span style="font-size: ${legacyValue}">Sized</span></p>`);
      const html = editor.getHTML();

      expect(html).toMatch(new RegExp(`style="font-size: ${cssValue.replace(".", "\\.")};?"`));
      expect(editor.getAttributes("textStyle").fontSize).toBe(cssValue);
    },
  );

  it("drops font sizes outside the nine-value contract", () => {
    const editor = createEditor('<p><span style="font-size: 11pt">Unsupported</span></p>');

    expect(editor.getHTML()).toBe("<p>Unsupported</p>");
  });

  it("merges nested imported text styles into one canonical span", () => {
    const editor = createEditor(`
      <p><span style="color: rgb(17, 24, 39)"><span style="font-size: 12pt">Nested</span></span></p>
    `);

    expect(editor.getHTML()).toBe(
      '<p><span style="color: #111827; font-size: 16px">Nested</span></p>',
    );
  });

  it("rejects unsupported style commands and stores supported aliases canonically", () => {
    const editor = createEditor("<p>Text</p>");
    editor.commands.setTextSelection({ from: 1, to: 5 });
    const before = editor.getHTML();

    expect(editor.commands.setColor("red")).toBe(false);
    expect(editor.commands.setFontFamily("Comic Sans MS")).toBe(false);
    expect(editor.commands.setFontSize("11pt")).toBe(false);
    expect(editor.commands.setHighlight({ color: "yellow" })).toBe(false);
    expect(editor.getHTML()).toBe(before);

    expect(editor.commands.setColor("rgb(17, 24, 39)")).toBe(true);
    expect(editor.getAttributes("textStyle").color).toBe("#111827");
  });

  it("preserves safe non-menu legacy colors and font families without activating a palette swatch", () => {
    const editor = createEditor(`
      <p><span style="color: RGB(18, 52, 86); font-family: Legacy Serif, serif">Legacy</span>
      <mark style="background-color: navy">Highlight</mark></p>
    `);
    const html = editor.getHTML();

    expect(html).toContain('style="color: rgb(18, 52, 86); font-family: Legacy Serif, serif"');
    expect(html).toContain('<mark style="background-color: navy">Highlight</mark>');
    editor.commands.setTextSelection(2);
    expect(isPaletteColorActive(editor, "color", "#111827")).toBe(false);
  });

  it("preserves a sanitizer-admitted legacy span background as a canonical highlight", () => {
    const editor = createEditor(`
      <p><span style="color: RGB(18, 52, 86); background-color: navy; font-family: Legacy Serif, serif">
        Legacy
      </span></p>
    `);
    const once = editor.getHTML();
    const documentNode = parseHtml(once);
    const textStyle = documentNode.querySelector("span");
    const highlight = documentNode.querySelector("mark");

    expect(textStyle?.getAttribute("style")).toBe(
      "color: rgb(18, 52, 86); font-family: Legacy Serif, serif",
    );
    expect(highlight?.getAttribute("style")).toBe("background-color: navy");
    expect(highlight?.textContent.trim()).toBe("Legacy");
    expect(createEditor(once).getHTML()).toBe(once);
  });

  it.each([
    ["transparent", "transparent"],
    ["rgb(10%, 20%, 30%)", "rgb(26, 51, 77)"],
    ["#1234", "rgba(17, 34, 51, 0.266667)"],
    ["rgba(1, 2, 3, .3333333)", "rgba(1, 2, 3, 0.333333)"],
    ["hsl(0, 0%, 50%)", "rgb(128, 128, 128)"],
    ["rebeccapurple", "rebeccapurple"],
    ["currentcolor", "currentcolor"],
  ])("round-trips the sanitizer-admitted legacy CSS color %s as %s", (input, expected) => {
    const editor = createEditor(`
      <p><span style="color: ${input}">Foreground</span>
      <mark style="background-color: ${input}">Background</mark></p>
    `);
    const once = editor.getHTML();
    const documentNode = parseHtml(once);

    expect(documentNode.querySelector("span")?.getAttribute("style")).toContain(
      `color: ${expected}`,
    );
    expect(documentNode.querySelector("mark")?.getAttribute("style")).toContain(
      `background-color: ${expected}`,
    );
    expect(createEditor(once).getHTML()).toBe(once);
  });

  it.each([
    ["18px", "18px"],
    ["150%", "150%"],
    ["1.25em", "1.25em"],
    ["1.5rem", "1.5rem"],
  ])("preserves the bounded non-menu font size %s", (input, expected) => {
    const editor = createEditor(`<p><span style="font-size: ${input}">Legacy size</span></p>`);

    expect(editor.getHTML()).toContain(`style="font-size: ${expected}"`);
    expect(editor.getAttributes("textStyle").fontSize).toBe(expected);
  });

  it.each(TEXT_COLOR_PALETTE)(
    "round-trips the $label text palette RGB alias as lowercase hex",
    ({ value }) => {
      const rgb = Object.entries(PALETTE_RGB_ALIASES)
        .find(([, canonical]) => canonical === value)?.[0];
      const editor = createEditor(`<p><span style="color: ${rgb}">Color</span></p>`);
      const html = editor.getHTML();

      expect(normalizePaletteColor(rgb, "text")).toBe(value);
      expect(html).toMatch(new RegExp(`style="color: ${value};?"`));
      expect(isPaletteColorActive(editor, "color", value)).toBe(true);
    },
  );

  it.each(HIGHLIGHT_COLOR_PALETTE.filter(({ value }) => value !== null))(
    "round-trips the $label highlight RGB alias as style-only lowercase hex",
    ({ value }) => {
      const rgb = Object.entries(PALETTE_RGB_ALIASES)
        .find(([, canonical]) => canonical === value)?.[0];
      const editor = createEditor(`<p><mark style="background-color: ${rgb}" data-color="red">Highlight</mark></p>`);
      const html = editor.getHTML();
      const mark = parseHtml(editor.getHTML()).querySelector("mark");

      expect(normalizePaletteColor(rgb, "highlight")).toBe(value);
      expect(html).toMatch(new RegExp(`style="background-color: ${value};?"`));
      expect(mark?.hasAttribute("data-color")).toBe(false);
      expect(isPaletteColorActive(editor, "highlight", value)).toBe(true);
    },
  );

  it.each(FONT_FAMILIES)(
    "round-trips the $label font family using its contract CSS value",
    ({ cssValue }) => {
      const editor = createEditor(`<p><span style='font-family: ${cssValue}'>Family</span></p>`);
      const span = parseHtml(editor.getHTML()).querySelector("span");

      expect(span?.style.fontFamily).toBe(cssValue);
      expect(editor.getAttributes("textStyle").fontFamily).toBe(cssValue);
    },
  );

  it("preserves headings 1-6, lists, code, underline, and supported alignment", () => {
    const editor = createEditor(`
      <h1>One</h1><h2>Two</h2><h3>Three</h3><h4>Four</h4><h5>Five</h5><h6>Six</h6>
      <ul><li><p>Bullet</p></li></ul><ol><li><p>Number</p></li></ol>
      <blockquote><p>Quote</p></blockquote><pre><code>const safe = true</code></pre>
      <p style="text-align: center"><u>Centered</u></p>
    `);
    const documentNode = parseHtml(editor.getHTML());

    [1, 2, 3, 4, 5, 6].forEach((level) => {
      expect(documentNode.querySelector(`h${level}`)).not.toBeNull();
    });
    expect(documentNode.querySelector("ul li p")?.textContent).toBe("Bullet");
    expect(documentNode.querySelector("ol li p")?.textContent).toBe("Number");
    expect(documentNode.querySelector("pre code")?.textContent).toBe("const safe = true");
    const alignedParagraph = [...documentNode.querySelectorAll("p")]
      .find((paragraph) => paragraph.style.textAlign === "center");
    expect(alignedParagraph?.querySelector("u")?.textContent).toBe("Centered");
  });

  it("keeps safe links and removes unsafe or credential-bearing hrefs", () => {
    const insecureSameOrigin = new URL("/insecure", document.baseURI);
    insecureSameOrigin.protocol = "http:";
    const editor = createEditor(`
      <p>
        <a href="https://school.example/library" target="_blank" title="Library">External</a>
        <a href="/classes/42?tab=posts#one">Local</a>
        <a href="lessons/today">Relative</a>
        <a href="#section-two">Fragment</a>
        <a href="?tab=comments">Query</a>
        <a href="javascript:alert(1)">Script</a>
        <a href="https://user:pass@school.example/private">Credential</a>
        <a href="//tracker.example/private">Scheme relative</a>
        <a href="${insecureSameOrigin.href}">Absolute HTTP</a>
      </p>
    `);
    const documentNode = parseHtml(editor.getHTML());
    const links = [...documentNode.querySelectorAll("a")];

    expect(links.map((link) => link.getAttribute("href"))).toEqual([
      "https://school.example/library",
      "/classes/42?tab=posts#one",
      "lessons/today",
      "#section-two",
      "?tab=comments",
    ]);
    expect(links[0]?.getAttribute("target")).toBe("_blank");
    expect(links[0]?.getAttribute("rel")).toBe("noopener noreferrer");
    expect(documentNode.body.textContent).toMatch(
      /Script\s+Credential\s+Scheme relative\s+Absolute HTTP/,
    );
  });

  it("renders canonical image attributes and rejects remote or malformed upload URLs", () => {
    const editor = createEditor(`
      <img src="${IMAGE_URL}" alt="Book cover" title="Reading" width="640" height="480"
        class="post-image img-fluid aligncenter unsafe mceNonEditable">
      <img src="https://tracker.example/pixel.png" alt="Remote">
      <img src="/api/uploads/objects/ff/11111111111111111111111111111111.png" alt="Wrong prefix">
    `);
    const documentNode = parseHtml(editor.getHTML());
    const images = [...documentNode.querySelectorAll("img")];

    expect(images).toHaveLength(1);
    expect(images[0]?.outerHTML).toBe(
      `<img src="${IMAGE_URL}" alt="Book cover" title="Reading" width="640" height="480" class="post-image img-fluid aligncenter">`,
    );
  });

  it("normalizes canonical and approved legacy video envelopes to one atomic node", () => {
    const canonical = createEditor(`
      <figure class="video-container"><video controls preload="metadata" width="640" height="360">
        <source src="${VIDEO_URL}" type="VIDEO/MP4">
      </video></figure>
    `);
    const legacy = createEditor(`
      <div class="video-wrapper mceNonEditable" data-video-url="${VIDEO_URL}" data-video-type="VIDEO/MP4">
        <button class="video-delete-btn editor-only" data-video-url="${VIDEO_URL}">Delete</button>
      </div>
    `);

    [
      [canonical, ` width="640" height="360"`],
      [legacy, ""],
    ].forEach(([editor, dimensions]) => {
      const documentNode = parseHtml(editor.getHTML());
      const figure = documentNode.querySelector("figure.video-container");
      expect(figure?.outerHTML).toBe(
        `<figure class="video-container"><video controls="" preload="metadata"${dimensions}><source src="${VIDEO_URL}" type="video/mp4"></video></figure>`,
      );
      expect(documentNode.querySelector("button, [data-video-url], [contenteditable]")).toBeNull();
    });
  });

  it("preserves backend-generated direct video sources without inventing a MIME type", () => {
    const editor = createEditor(`<video controls src="${VIDEO_URL}"></video>`);
    const once = editor.getHTML();

    expect(once).toBe(
      `<figure class="video-container"><video controls="" preload="metadata" src="${VIDEO_URL}"></video></figure>`,
    );
    expect(createEditor(once).getHTML()).toBe(once);
    expect(once.match(new RegExp(VIDEO_URL, "g"))).toHaveLength(1);
  });

  it("normalizes canonical and approved legacy PDF attachments without editor controls", () => {
    const canonical = createEditor(`
      <div class="file-attachment" data-file-url="${PDF_URL}" data-file-name="Reading.pdf"
        data-file-size="42 KB" data-file-type="application/pdf"></div>
    `);
    const legacy = createEditor(`
      <div class="file-attachment mceNonEditable" data-file-name="Reading.pdf" data-file-size="42 KB" data-file-type="pdf">
        <div class="file-actions"><button class="remove-btn editor-only" data-file-url="${PDF_URL}">Remove</button></div>
      </div>
    `);

    [canonical, legacy].forEach((editor) => {
      const documentNode = parseHtml(editor.getHTML());
      const attachment = documentNode.querySelector("div.file-attachment");
      expect(attachment?.getAttribute("data-file-url")).toBe(PDF_URL);
      expect(attachment?.getAttribute("data-file-name")).toBe("Reading.pdf");
      expect(attachment?.getAttribute("data-file-size")).toBe("42 KB");
      expect(attachment?.getAttribute("data-file-type")).toBe("application/pdf");
      expect(attachment?.querySelector(".file-name")?.textContent).toBe("Reading.pdf");
      expect(documentNode.querySelector("button, .file-actions, .mceNonEditable")).toBeNull();
    });
  });

  it("preserves backend-generated attachment anchors as one canonical atomic attachment", () => {
    const editor = createEditor(
      `<a class="file-attachment" href="${PDF_URL}" title="Course reading">Reading.pdf</a>`,
    );
    const once = editor.getHTML();
    const documentNode = parseHtml(once);

    expect(documentNode.querySelector("a.file-attachment")).toBeNull();
    expect(documentNode.querySelector("div.file-attachment")?.getAttribute("data-file-url")).toBe(PDF_URL);
    expect(documentNode.querySelector(".file-name")?.textContent).toBe("Course reading");
    expect(once.match(new RegExp(PDF_URL, "g"))).toHaveLength(1);
    expect(createEditor(once).getHTML()).toBe(once);
  });

  it("uses visible backend attachment anchor text when no title metadata exists", () => {
    const editor = createEditor(`<a class="file-attachment" href="${PDF_URL}">Reading.pdf</a>`);
    const documentNode = parseHtml(editor.getHTML());

    expect(documentNode.querySelector(".file-name")?.textContent).toBe("Reading.pdf");
    expect(documentNode.querySelector(".file-attachment")?.getAttribute("data-file-url")).toBe(PDF_URL);
  });

  it("serializes only canonical table structure and supported cell attributes", () => {
    const editor = createEditor(`
      <table style="min-width: 500px"><colgroup><col style="min-width: 250px"></colgroup><tbody><tr>
        <th colspan="2" rowspan="1" colwidth="250,250" scope="col" style="text-align: center"><p>Head</p></th>
        <td colspan="1" rowspan="2" colwidth="250"><p>Cell</p></td>
      </tr></tbody></table>
    `);
    const documentNode = parseHtml(editor.getHTML());
    const table = documentNode.querySelector("table");

    expect(table?.outerHTML).toBe(
      '<table><tbody><tr><th colspan="2" scope="col"><p>Head</p></th><td rowspan="2"><p>Cell</p></td></tr></tbody></table>',
    );
    expect(table?.querySelector("colgroup, col")).toBeNull();
    expect(table?.outerHTML).not.toMatch(/colwidth|min-width|style=/);
  });

  it("keeps invalid media and attachment URLs out of serialized HTML", () => {
    const editor = createEditor(`
      <figure class="video-container"><video><source src="javascript:alert(1)" type="video/mp4"></video></figure>
      <div class="video-data" data-video-url="https://tracker.example/video.mp4" data-video-type="video/mp4"></div>
      <div class="file-attachment" data-file-url="/uploads/files/42/private.pdf" data-file-name="Bad.pdf" data-file-type="pdf"></div>
    `);
    const html = editor.getHTML();

    expect(html).not.toMatch(/javascript:|tracker\.example|\/uploads\/files\//);
    expect(parseHtml(html).querySelector("figure, video, source, .file-attachment")).toBeNull();
  });

  it("rejects invalid media commands before they can change the document", () => {
    const editor = createEditor("<p>Safe</p>");
    const before = editor.getHTML();

    expect(editor.commands.setImage({ src: "https://tracker.example/pixel.png" })).toBe(false);
    expect(editor.commands.setVideo({ src: "javascript:alert(1)", type: "video/mp4" })).toBe(false);
    expect(editor.commands.setAttachment({
      url: "/uploads/files/42/private.pdf",
      name: "Private.pdf",
      type: "application/pdf",
    })).toBe(false);
    expect(editor.getHTML()).toBe(before);
  });

  it("inserts canonical image, video, and attachment nodes through their commands", () => {
    const imageEditor = createEditor("<p></p>");
    const videoEditor = createEditor("<p></p>");
    const attachmentEditor = createEditor("<p></p>");

    expect(imageEditor.commands.setImage({ src: IMAGE_URL, alt: "Cover" })).toBe(true);
    expect(videoEditor.commands.setVideo({ src: VIDEO_URL, type: "VIDEO/MP4" })).toBe(true);
    expect(attachmentEditor.commands.setAttachment({
      url: PDF_URL,
      name: "Reading.pdf",
      size: "42 KB",
      type: "pdf",
    })).toBe(true);

    expect(parseHtml(imageEditor.getHTML()).querySelector("img")?.getAttribute("src")).toBe(IMAGE_URL);
    expect(parseHtml(videoEditor.getHTML()).querySelector("source")?.getAttribute("src")).toBe(VIDEO_URL);
    expect(
      parseHtml(attachmentEditor.getHTML())
        .querySelector(".file-attachment")
        ?.getAttribute("data-file-url"),
    ).toBe(PDF_URL);
  });

  it.each([
    IMAGE_URL,
    VIDEO_URL,
    PDF_URL,
  ])("recognizes the canonical upload object URL %s", (url) => {
    expect(isCanonicalUploadUrl(url)).toBe(true);
  });

  it.each([
    "https://school.example/api/uploads/objects/11/11111111111111111111111111111111.png",
    "/uploads/objects/11/11111111111111111111111111111111.png",
    "/api/uploads/files/11/11111111111111111111111111111111.png",
    "/api/uploads/objects/ff/11111111111111111111111111111111.png",
    "/api/uploads/objects/11/11111111111111111111111111111111.png?download=1",
    "/api/uploads/objects/11/11111111111111111111111111111111.PNG",
  ])("rejects the non-canonical upload URL %s", (url) => {
    expect(isCanonicalUploadUrl(url)).toBe(false);
  });

  it("is idempotent after parsing and canonical serialization", () => {
    const raw = `
      <h5 style="text-align: right">Legacy heading</h5>
      <p><span style="font-size: 12pt; color: rgb(17, 24, 39); font-family: Georgia, 'Times New Roman', Times, serif">Text</span></p>
      <figure class="video-container mceNonEditable" contenteditable="false"><video controls>
        <source src="${VIDEO_URL}" type="VIDEO/MP4"></video><button class="video-delete-btn">Delete</button></figure>
      <div class="file-attachment mceNonEditable" data-file-url="${PDF_URL}" data-file-name="Reading.pdf" data-file-size="42 KB" data-file-type="pdf"></div>
    `;
    const once = createEditor(raw).getHTML();
    const twice = createEditor(once).getHTML();

    expect(twice).toBe(once);
  });
});
