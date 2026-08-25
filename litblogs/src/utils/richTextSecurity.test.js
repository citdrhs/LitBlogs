import { describe, expect, it, vi } from "vitest";

import {
  normalizeRichTextUrl,
  sanitizeRichText,
} from "./richTextSecurity.js";
import {
  HIGHLIGHT_COLOR_PALETTE,
  TEXT_COLOR_PALETTE,
} from "./richTextContract.js";

const parse = (html) => {
  const template = document.createElement("template");
  template.innerHTML = html;
  return template.content;
};

const objectUrl = (index, extension) => {
  const objectId = Number(index).toString(16).padStart(32, "0");
  return `/api/uploads/objects/${objectId.slice(0, 2)}/${objectId}.${extension}`;
};

const IMAGE_URL = objectUrl(0x11, "png");
const SECOND_IMAGE_URL = objectUrl(0x12, "png");
const VIDEO_URL = objectUrl(0x21, "mp4");
const SECOND_VIDEO_URL = objectUrl(0x22, "mp4");
const PDF_URL = objectUrl(0x31, "pdf");
const SECOND_PDF_URL = objectUrl(0x32, "pdf");
const PALETTE_RGB_CASES = [...TEXT_COLOR_PALETTE, ...HIGHLIGHT_COLOR_PALETTE]
  .filter(({ value }) => value !== null)
  .map(({ label, value }) => ({
    canonicalHex: value,
    label,
    rgbChannels: [1, 3, 5]
      .map((offset) => Number.parseInt(value.slice(offset, offset + 2), 16))
      .join(", "),
  }));

describe("sanitizeRichText", () => {
  it.each([
    `<img src="${IMAGE_URL}" onerror="window.__xss = true"><script>window.__xss = true</script>`,
    `&lt;img src=&quot;${IMAGE_URL}&quot; onerror=&quot;window.__xss = true&quot;&gt;&lt;script&gt;window.__xss = true&lt;/script&gt;`,
    '<a href="java&#x73;cript:window.__xss=true" onclick="window.__xss=true">Open</a>',
  ])("removes executable markup from actual and entity-encoded input", (payload) => {
    const fragment = parse(sanitizeRichText(payload));

    expect(fragment.querySelector("script, style, iframe, object, embed, form")).toBeNull();
    expect(fragment.querySelector("[onerror], [onclick], [onload]")).toBeNull();
    expect(fragment.querySelector('a[href^="javascript:"]')).toBeNull();
  });

  it("preserves supported typography while removing active or layout-breaking CSS", () => {
    const fragment = parse(sanitizeRichText(`
      <h2>Reading response</h2>
      <p style="font-family: Georgia, serif; color: #123456; background-color: rgb(250, 250, 250); font-size: 18px; text-align: center; position: fixed; inset: 0; background-image: url(javascript:alert(1))">
        <strong>Careful</strong> analysis
      </p>
    `));
    const paragraph = fragment.querySelector("p");

    expect(fragment.querySelector("h2")?.textContent).toBe("Reading response");
    expect(paragraph?.style.fontFamily).toContain("Georgia");
    expect(paragraph?.style.color).not.toBe("");
    expect(paragraph?.style.backgroundColor).not.toBe("");
    expect(paragraph?.style.fontSize).toBe("18px");
    expect(paragraph?.style.textAlign).toBe("center");
    expect(paragraph?.style.position).toBe("");
    expect(paragraph?.style.backgroundImage).toBe("");
  });

  it("normalizes legacy encoded media without rehydrating event handlers", () => {
    const fragment = parse(sanitizeRichText(`
      &lt;figure class=&quot;video-container&quot;&gt;
        &lt;video controls preload=&quot;metadata&quot; onplay=&quot;window.__xss=true&quot;&gt;
          &lt;source src=&quot;${VIDEO_URL}&quot; type=&quot;video/mp4&quot; onerror=&quot;window.__xss=true&quot;&gt;
        &lt;/video&gt;
      &lt;/figure&gt;
      <img src="${IMAGE_URL}" alt="Book cover" onerror="window.__xss=true">
    `));

    expect(fragment.querySelector("figure.video-container video[controls]")).not.toBeNull();
    expect(fragment.querySelector("source")?.getAttribute("src")).toBe(
      VIDEO_URL,
    );
    expect(fragment.querySelector("img")?.getAttribute("src")).toBe(
      IMAGE_URL,
    );
    expect(fragment.querySelector("[onplay], [onerror]")).toBeNull();
  });

  it("stays non-executable across repeated legacy entity normalization", () => {
    let normalized = `
      &lt;video controls&gt;&lt;source src=&quot;${VIDEO_URL}&quot; type=&quot;video/mp4&quot;&gt;&lt;/video&gt;
      &amp;lt;img src=&amp;quot;${IMAGE_URL}&amp;quot; onerror=&amp;quot;window.__xss=true&amp;quot;&amp;gt;
    `;

    for (let pass = 0; pass < 4; pass += 1) {
      normalized = sanitizeRichText(normalized, { mode: "editor" });
      const fragment = parse(normalized);

      expect(fragment.querySelector("script, style, iframe, object, embed, form")).toBeNull();
      expect(fragment.querySelector("[onerror], [onclick], [onload], [onplay]")).toBeNull();
    }
  });

  it("recovers many legacy media nodes without full-document replacement loops", () => {
    const legacyNodes = Array.from({ length: 256 }, (_, index) => (
      `<span>&lt;video src=&quot;${objectUrl(index + 0x100, "mp4")}&quot; controls&gt;&lt;/video&gt;</span>`
    )).join("");
    const replaceSpy = vi.spyOn(String.prototype, "replace");
    try {
      const fragment = parse(sanitizeRichText(legacyNodes));
      const markerReplacementCalls = replaceSpy.mock.calls.filter(([pattern]) => (
        typeof pattern === "string" && pattern.startsWith("<!--rich-text-legacy-media-")
      ));

      expect(fragment.querySelectorAll("video")).toHaveLength(256);
      expect(markerReplacementCalls).toHaveLength(0);
    } finally {
      replaceSpy.mockRestore();
    }
  });

  it("bounds legacy media recovery work for adversarial many-node content", () => {
    const legacyNodes = Array.from({ length: 300 }, (_, index) => (
      `<span>&lt;video src=&quot;${objectUrl(index + 0x300, "mp4")}&quot; controls&gt;&lt;/video&gt;</span>`
    )).join("");
    const fragment = parse(sanitizeRichText(legacyNodes));

    expect(fragment.querySelectorAll("video")).toHaveLength(256);
    expect(fragment.textContent).toContain("<video src=");
  });

  it("fails closed before parsing oversized rich text", () => {
    const parserSpy = vi.spyOn(DOMParser.prototype, "parseFromString");
    try {
      const sanitized = sanitizeRichText("x".repeat(1_000_001));

      expect(sanitized).toBe("");
      expect(parserSpy).not.toHaveBeenCalled();
    } finally {
      parserSpy.mockRestore();
    }
  });

  it("recovers legacy media without activating escaped code or links", () => {
    const fragment = parse(sanitizeRichText(`
      <pre><code>&lt;div class=&quot;example&quot;&gt;Sample markup&lt;/div&gt;</code></pre>
      &lt;a href=&quot;https://tracker.example/private&quot;&gt;Escaped link&lt;/a&gt;
      &lt;figure class=&quot;video-container&quot;&gt;
        &lt;video controls&gt;
          &lt;source src=&quot;${VIDEO_URL}&quot; type=&quot;video/mp4&quot;&gt;
        &lt;/video&gt;
      &lt;/figure&gt;
    `));

    expect(fragment.querySelector("figure.video-container video source")?.getAttribute("src")).toBe(
      VIDEO_URL,
    );
    expect(fragment.querySelector("pre code div")).toBeNull();
    expect(fragment.querySelector("pre code")?.textContent).toContain("<div");
    expect(fragment.querySelector("a")).toBeNull();
    expect(fragment.textContent).toContain("<a href=");
  });

  it("keeps encoded video examples inert inside code blocks", () => {
    const fragment = parse(sanitizeRichText(`
      <pre><code>&lt;video src=&quot;${VIDEO_URL}&quot; controls&gt;&lt;/video&gt;</code></pre>
    `));

    expect(fragment.querySelector("pre code video")).toBeNull();
    expect(fragment.querySelector("pre code")?.textContent).toContain("<video");
  });

  it("removes unsafe navigation, media, and attachment URLs", () => {
    const fragment = parse(sanitizeRichText(`
      <a href="javascript:alert(1)" target="_blank">Bad link</a>
      <img src="data:text/html,<script>alert(1)</script>">
      <video><source src="https://tracker.example/video.mp4"></video>
      <div class="file-attachment" data-file-url="//tracker.example/private.pdf">
        <button class="remove-btn editor-only" data-file-url="javascript:alert(1)">Remove</button>
      </div>
    `, { mode: "editor" }));

    expect(fragment.querySelector("a")?.hasAttribute("href")).toBe(false);
    expect(fragment.querySelector("img")?.hasAttribute("src")).toBe(false);
    expect(fragment.querySelector("source")).toBeNull();
    expect(fragment.querySelector(".file-attachment")?.hasAttribute("data-file-url")).toBe(false);
    expect(fragment.querySelector("button")?.hasAttribute("data-file-url")).toBe(false);
  });

  it("keeps attacker media URLs out of the resource-loading DOM parser", () => {
    const parserSpy = vi.spyOn(DOMParser.prototype, "parseFromString");
    try {
      const sanitized = sanitizeRichText(`
        <img src="https://tracker.example/private-image.png">
        <video src="https://tracker.example/private-video.mp4" controls></video>
        <video><source src="https://tracker.example/private-source.mp4"></video>
      `);
      const parserInputs = parserSpy.mock.calls.map(([input]) => String(input)).join("\n");
      const fragment = parse(sanitized);

      expect(parserInputs).not.toContain("tracker.example");
      expect(fragment.querySelector("img")?.hasAttribute("src")).toBe(false);
      expect(fragment.querySelector("video")?.hasAttribute("src")).toBe(false);
      expect(fragment.querySelector("source")).toBeNull();
    } finally {
      parserSpy.mockRestore();
    }
  });

  it("normalizes direct video sources to canonical local uploads", () => {
    const fragment = parse(sanitizeRichText(`
      <video id="safe" src="${VIDEO_URL}" controls></video>
      <video id="external" src="https://tracker.example/pixel.mp4" controls></video>
      <video id="data" src="data:video/mp4;base64,AAAA" controls></video>
    `));
    const videos = fragment.querySelectorAll("video");

    expect(videos[0]?.getAttribute("src")).toBe(VIDEO_URL);
    expect(videos[1]?.hasAttribute("src")).toBe(false);
    expect(videos[2]?.hasAttribute("src")).toBe(false);
  });

  it("drops pathological layout values while retaining bounded formatting", () => {
    const fragment = parse(sanitizeRichText(`
      <p id="unsafe" style="font-size: 999999999px; width: 999999999px; height: 999999999px; margin: 999999999px; max-width: 999999999px">Oversized</p>
      <p id="safe" style="font-size: 18px; width: 100%; max-width: 600px; margin: 12px 0">Bounded</p>
      <img src="${IMAGE_URL}" width="999999999px" height="999999999px">
      <img src="${SECOND_IMAGE_URL}" width="100%" height="4096px">
    `));
    const paragraphs = fragment.querySelectorAll("p");
    const images = fragment.querySelectorAll("img");

    expect(paragraphs[0]?.style.fontSize).toBe("");
    expect(paragraphs[0]?.style.width).toBe("");
    expect(paragraphs[0]?.style.height).toBe("");
    expect(paragraphs[0]?.style.margin).toBe("");
    expect(paragraphs[0]?.style.maxWidth).toBe("");
    expect(paragraphs[1]?.style.fontSize).toBe("18px");
    expect(paragraphs[1]?.style.width).toBe("100%");
    expect(paragraphs[1]?.style.maxWidth).toBe("600px");
    expect(paragraphs[1]?.style.margin).toBe("12px 0px");
    expect(images[0]?.hasAttribute("width")).toBe(false);
    expect(images[0]?.hasAttribute("height")).toBe(false);
    expect(images[1]?.getAttribute("width")).toBe("100%");
    expect(images[1]?.getAttribute("height")).toBe("4096px");
  });

  it("keeps safe links and strips editor-only controls from display output", () => {
    const fragment = parse(sanitizeRichText(`
      <a href="https://school.example/library" target="_blank">Library</a>
      <div class="file-attachment" data-file-url="${PDF_URL}">
        <button class="remove-btn editor-only" type="button" data-file-url="${PDF_URL}" onclick="alert(1)">Remove</button>
      </div>
    `));
    const link = fragment.querySelector("a");

    expect(link?.getAttribute("href")).toBe("https://school.example/library");
    expect(link?.getAttribute("target")).toBe("_blank");
    expect(link?.getAttribute("rel")).toBe("noopener noreferrer");
    expect(fragment.querySelector(".editor-only, button")).toBeNull();
    expect(fragment.querySelector(".file-attachment")?.getAttribute("data-file-url")).toBe(
      PDF_URL,
    );
  });

  it("retains inert editor controls without inline code", () => {
    const fragment = parse(sanitizeRichText(`
      <button class="remove-btn editor-only" type="button" data-file-url="${PDF_URL}" onclick="alert(1)">Remove</button>
    `, { mode: "editor" }));
    const button = fragment.querySelector("button");

    expect(button).not.toBeNull();
    expect(button?.getAttribute("type")).toBe("button");
    expect(button?.getAttribute("data-file-url")).toBe(
      PDF_URL,
    );
    expect(button?.hasAttribute("onclick")).toBe(false);
  });

  it("retains only safe local metadata for the trusted PDF renderer", () => {
    const safeFragment = parse(sanitizeRichText(`
      <div data-inline-pdf-viewer="true" data-pdf-url="${PDF_URL}" data-pdf-title="Course reading"></div>
    `, { mode: "editor" }));
    const unsafeFragment = parse(sanitizeRichText(`
      <div data-inline-pdf-viewer="true" data-pdf-url="javascript:alert(1)" data-pdf-title="Course reading"></div>
    `, { mode: "editor" }));

    expect(safeFragment.querySelector("div.file-attachment")?.getAttribute("data-file-url")).toBe(PDF_URL);
    expect(safeFragment.querySelector("div.file-attachment")?.getAttribute("data-file-name")).toBe("Course reading");
    expect(safeFragment.querySelector("div.file-attachment")?.getAttribute("data-file-type")).toBe("pdf");
    expect(safeFragment.querySelector("[data-inline-pdf-viewer], [data-pdf-url], [data-pdf-title]")).toBeNull();
    expect(unsafeFragment.querySelector("div")?.hasAttribute("data-pdf-url")).toBe(false);
  });

  it("drops dangerous subtrees wholly while unwrapping harmless unsupported containers", () => {
    const fragment = parse(sanitizeRichText(`
      <iframe><img src="${IMAGE_URL}">hidden frame text</iframe>
      <form><p>hidden form text</p></form>
      <svg><title>hidden svg text</title></svg>
      <section><strong>kept wrapper text</strong></section>
    `));

    expect(fragment.querySelector("iframe, form, svg, img")).toBeNull();
    expect(fragment.textContent).not.toContain("hidden frame text");
    expect(fragment.textContent).not.toContain("hidden form text");
    expect(fragment.textContent).not.toContain("hidden svg text");
    expect(fragment.querySelector("section")).toBeNull();
    expect(fragment.querySelector("strong")?.textContent).toBe("kept wrapper text");
  });

  it("preserves HTML5 foster-parented content in canonical order", () => {
    const sanitized = sanitizeRichText(
      "<table>before<div>inside</div><tr><td>x</td></tr>after</table>",
    );
    const fragment = parse(sanitized);

    expect(fragment.querySelector("div")?.textContent).toBe("inside");
    expect(fragment.querySelector("table tbody tr td")?.textContent).toBe("x");
    expect(fragment.textContent).toContain("before");
    expect(fragment.textContent).toContain("after");
    for (const value of ["before", "inside", "after", "x"]) {
      expect(sanitized.split(value)).toHaveLength(2);
    }
  });

  it.each(["plaintext", "xmp", "textarea", "title"])(
    "does not add synthetic markup to an unclosed %s element",
    (tag) => {
      expect(sanitizeRichText(`<${tag}>hello`)).toBe("hello");
    },
  );

  it.each(["iframe", "script", "style"])(
    "drops an unclosed dangerous %s subtree and its swallowed content",
    (tag) => {
      expect(sanitizeRichText(`<${tag}>hidden<p>swallowed`)).toBe("");
    },
  );

  it.each([
    ["8pt", "10.667px"], ["10pt", "13.333px"], ["12pt", "16px"],
    ["14pt", "18.667px"], ["16pt", "21.333px"], ["18pt", "24px"],
    ["24pt", "32px"], ["36pt", "48px"], ["48pt", "64px"],
  ])("normalizes contract point size %s to %s", (legacyValue, cssValue) => {
    const fragment = parse(sanitizeRichText(
      `<span style="font-size: ${legacyValue} !important">Sized</span>`,
    ));
    const span = fragment.querySelector("span");

    expect(span?.style.fontSize).toBe(cssValue);
    expect(span?.style.getPropertyPriority("font-size")).toBe("");
  });

  it.each(PALETTE_RGB_CASES)(
    "normalizes the $label palette RGB alias to $canonicalHex",
    ({ canonicalHex, rgbChannels }) => {
      const fragment = parse(sanitizeRichText(
        `<span style="color: rgba(${rgbChannels}, 1)">Palette</span>`,
      ));

      expect(fragment.querySelector("span")?.getAttribute("style")).toContain(
        `color: ${canonicalHex}`,
      );
    },
  );

  it.each([
    ["transparent", "transparent"],
    ["rgb(10%, 20%, 30%)", "rgb(26, 51, 77)"],
    ["#1234", "rgba(17, 34, 51, 0.266667)"],
    ["rgba(1, 2, 3, .3333333)", "rgba(1, 2, 3, 0.333333)"],
    ["hsl(0, 0%, 50%)", "rgb(128, 128, 128)"],
    ["rebeccapurple", "rebeccapurple"],
    ["currentcolor", "currentcolor"],
    ["canvastext", "canvastext"],
    ["buttontext", "buttontext"],
    ["activeborder", "activeborder"],
    ["buttonhighlight", "buttonhighlight"],
    ["threedface", "threedface"],
    ["windowtext", "windowtext"],
    ["rgba(1, 2, 3, 50%)", "rgba(1, 2, 3, 0.5)"],
    ["rgba(1, 2, 3, 33.333333%)", "rgba(1, 2, 3, 0.333333)"],
    ["hsl(120deg, 100%, 50%)", "rgb(0, 255, 0)"],
    ["hsl(0, 50%, 33.333333%)", "rgb(128, 43, 43)"],
    ["hsl(0, -1%, 50%)", "rgb(128, 128, 128)"],
    ["rgb(49.999%, 0%, 12.345678%)", "rgb(127, 0, 31)"],
    ["rgb(0.196078%, 0%, 0%)", "rgb(1, 0, 0)"],
    ["rgba(12.345678%, 50%, 99.9%, 99.999999%)", "rgb(31, 128, 255)"],
  ])("canonicalizes safe legacy CSS color %s", (legacyColor, canonicalColor) => {
    const fragment = parse(sanitizeRichText(
      `<span style="color: ${legacyColor}">Legacy color</span>`,
    ));

    expect(fragment.querySelector("span")?.getAttribute("style")).toContain(
      `color: ${canonicalColor}`,
    );
  });

  it.each([
    "rgb(10% 20% 30% / 50%)",
    "hsl(.5turn, 100%, 50%)",
    "hsl(2.094395rad, 100%, 50%)",
    "hsl(200grad, 100%, 50%)",
    "rgb(1e2, 0, 0)",
    "rgba(1e2, 0, 0, 5e-1)",
    "rgb(.5, 1.5, 2.5)",
  ])("rejects unsupported CSS color syntax %s consistently", (color) => {
    const fragment = parse(sanitizeRichText(
      `<span style="color: ${color}">Modern color</span>`,
    ));

    expect(fragment.querySelector("span")?.hasAttribute("style")).toBe(false);
  });

  it("normalizes legacy aliases, font attributes, palette aliases, and mixed classes", () => {
    const fragment = parse(sanitizeRichText(`
      <b>bold</b><i>italic</i><del>deleted</del><strike>struck</strike>
      <font color="rgba(17, 24, 39, 1)" face="Legacy Serif" size="12pt">legacy font</font>
      <p class="aligncenter unsafe mceNonEditable" align="center"
         style="color: RGB(18, 52, 86); background-color: navy; font-family: Legacy Serif, serif; font-size: 9pt">
        paragraph
      </p>
      <pre><code class="language-python unsafe">print('safe')</code></pre>
    `));
    const fontSpan = [...fragment.querySelectorAll("span")].find((node) => node.textContent === "legacy font");
    const paragraph = fragment.querySelector("p");
    const code = fragment.querySelector("code");

    expect(fragment.querySelector("b, i, del, strike, font")).toBeNull();
    expect(fragment.querySelector("strong")?.textContent).toBe("bold");
    expect(fragment.querySelector("em")?.textContent).toBe("italic");
    expect(fragment.querySelectorAll("s")).toHaveLength(2);
    expect(fontSpan?.getAttribute("style")).toContain("color: #111827");
    expect(fontSpan?.style.fontFamily).toBe("Legacy Serif");
    expect(fontSpan?.style.fontSize).toBe("16px");
    expect(paragraph?.className).toBe("aligncenter");
    expect(paragraph?.hasAttribute("align")).toBe(false);
    expect(paragraph?.style.color).toBe("rgb(18, 52, 86)");
    expect(paragraph?.style.backgroundColor).toBe("navy");
    expect(paragraph?.style.fontFamily).toBe("Legacy Serif, serif");
    expect(paragraph?.style.fontSize).toBe("");
    expect(code?.className).toBe("language-python");
  });

  it("hoists safe canonical metadata before removing display controls and respects parent precedence", () => {
    const fragment = parse(sanitizeRichText(`
      <div class="file-attachment mceNonEditable" data-file-url="${PDF_URL}" data-file-name="Parent.pdf" data-file-type="pdf" contenteditable="false">
        <div class="file-actions"><button class="remove-btn editor-only" data-file-url="${SECOND_PDF_URL}" onclick="bad()">Remove parent</button></div>
      </div>
      <div class="file-attachment mceNonEditable" data-file-name="Child.pdf" data-file-type="pdf">
        <button class="remove-btn editor-only" data-file-url="${SECOND_PDF_URL}">Remove child</button>
      </div>
      <figure class="video-container mceNonEditable" contenteditable="false">
        <video controls preload="AUTO"><source src="https://bad.example/video.mp4" type="text/html"></video>
        <div class="video-data" data-video-url="${VIDEO_URL}" data-video-type="VIDEO/MP4"></div>
        <div class="video-delete-overlay editor-only-control"><button class="video-delete-btn" data-video-url="${VIDEO_URL}">Delete video</button></div>
      </figure>
    `));
    const attachments = fragment.querySelectorAll("div.file-attachment");
    const source = fragment.querySelector("figure.video-container video source");

    expect(attachments[0]?.getAttribute("data-file-url")).toBe(PDF_URL);
    expect(attachments[1]?.getAttribute("data-file-url")).toBe(SECOND_PDF_URL);
    expect(source?.getAttribute("src")).toBe(VIDEO_URL);
    expect(source?.getAttribute("type")).toBe("video/mp4");
    expect(fragment.querySelector("button, .file-actions, .video-data, .video-delete-overlay")).toBeNull();
    expect(fragment.textContent).not.toContain("Remove parent");
    expect(fragment.textContent).not.toContain("Remove child");
    expect(fragment.textContent).not.toContain("Delete video");
    expect(fragment.querySelector("[contenteditable], [data-video-url], [data-video-type]")).toBeNull();
  });

  it("retains only inert TinyMCE removal controls in editor mode", () => {
    const fragment = parse(sanitizeRichText(`
      <div class="file-attachment mceNonEditable" data-file-name="Reading.pdf" data-file-type="pdf" contenteditable="false">
        <div class="file-actions"><button class="remove-btn editor-only unsafe" data-file-url="${PDF_URL}" onclick="bad()">Remove</button></div>
      </div>
      <figure class="video-container mceNonEditable" contenteditable="false">
        <video controls><source src="${VIDEO_URL}" type="video/mp4"></video>
        <div class="video-delete-overlay editor-only-control"><button class="video-delete-btn" data-video-url="${VIDEO_URL}" onfocus="bad()">×</button></div>
      </figure>
    `, { mode: "editor" }));
    const fileButton = fragment.querySelector("button.remove-btn.editor-only");
    const videoButton = fragment.querySelector("button.video-delete-btn");

    expect(fileButton?.getAttribute("type")).toBe("button");
    expect(fileButton?.getAttribute("data-file-url")).toBe(PDF_URL);
    expect(fileButton?.hasAttribute("onclick")).toBe(false);
    expect(fileButton?.classList.contains("unsafe")).toBe(false);
    expect(videoButton?.getAttribute("type")).toBe("button");
    expect(videoButton?.getAttribute("data-video-url")).toBe(VIDEO_URL);
    expect(videoButton?.hasAttribute("onfocus")).toBe(false);
    expect(fragment.querySelector("div.file-attachment")?.getAttribute("contenteditable")).toBe("false");
    expect(fragment.querySelector("figure.video-container")?.getAttribute("contenteditable")).toBe("false");
  });

  it("enforces per-tag attributes and semantic link, MIME, preload, and orphan-source rules", () => {
    const fragment = parse(sanitizeRichText(`
      <span href="https://school.example/wrong" src="${IMAGE_URL}" data-file-url="${PDF_URL}" colspan="2">Scoped</span>
      <a href="https://school.example/library" target="_blank" rel="opener">External</a>
      <a href="/classes/42?tab=posts#one" target="_self" rel="opener">Local</a>
      <a href="https://user:pass@school.example/private" target="_blank">Credential</a>
      <a href="lessons/today">Relative</a>
      <a href="//school.example/private">Scheme relative</a>
      <video src="${VIDEO_URL}" preload="metadata" controls></video>
      <video preload="auto"><source src="${SECOND_VIDEO_URL}" type="VIDEO/MP4"></video>
      <source src="${VIDEO_URL}" type="video/mp4">
      <table><tbody><tr><td colspan="0" rowspan="101">Bad</td><th scope="bad" colspan="2">Head</th></tr></tbody></table>
    `));
    const links = fragment.querySelectorAll("a");
    const videos = fragment.querySelectorAll("video");
    const sources = fragment.querySelectorAll("source");

    expect([...fragment.querySelector("span").attributes]).toHaveLength(0);
    expect(links[0]?.getAttribute("href")).toBe("https://school.example/library");
    expect(links[0]?.getAttribute("target")).toBe("_blank");
    expect(links[0]?.getAttribute("rel")).toBe("noopener noreferrer");
    expect(links[1]?.getAttribute("href")).toBe("/classes/42?tab=posts#one");
    expect(links[1]?.hasAttribute("target")).toBe(false);
    expect(links[2]?.hasAttribute("href")).toBe(false);
    expect(links[3]?.getAttribute("href")).toBe("lessons/today");
    expect(links[4]?.hasAttribute("href")).toBe(false);
    expect(videos[0]?.getAttribute("preload")).toBe("metadata");
    expect(videos[1]?.hasAttribute("preload")).toBe(false);
    expect(sources).toHaveLength(1);
    expect(sources[0]?.getAttribute("src")).toBe(SECOND_VIDEO_URL);
    expect(sources[0]?.getAttribute("type")).toBe("video/mp4");
    expect(fragment.querySelector("td")?.hasAttribute("colspan")).toBe(false);
    expect(fragment.querySelector("td")?.hasAttribute("rowspan")).toBe(false);
    expect(fragment.querySelector("th")?.getAttribute("colspan")).toBe("2");
    expect(fragment.querySelector("th")?.hasAttribute("scope")).toBe(false);
  });

  it("normalizes every source-bearing video to one editor-stable asset", () => {
    const once = sanitizeRichText(`
      <video controls><source src="${VIDEO_URL}"></video>
      <video controls>
        <source src="${VIDEO_URL}" type="text/html">
        <source src="${SECOND_VIDEO_URL}" type="video/webm">
        <source src="${VIDEO_URL}" type="video/mp4">
      </video>
    `);
    const fragment = parse(once);
    const videos = fragment.querySelectorAll("video");
    const sources = fragment.querySelectorAll("source");

    expect(videos).toHaveLength(2);
    expect(videos[0]?.getAttribute("src")).toBe(VIDEO_URL);
    expect(videos[0]?.querySelector("source")).toBeNull();
    expect(videos[1]?.hasAttribute("src")).toBe(false);
    expect(sources).toHaveLength(1);
    expect(sources[0]?.getAttribute("src")).toBe(SECOND_VIDEO_URL);
    expect(sources[0]?.getAttribute("type")).toBe("video/webm");
    expect(sanitizeRichText(once)).toBe(once);
  });

  it("is idempotent after canonical normalization", () => {
    const raw = `<b style="color: rgba(17, 24, 39, 1); font-size: 12pt !important">Text</b>`;
    const once = sanitizeRichText(raw);
    const twice = sanitizeRichText(once);

    expect(twice).toBe(once);
  });

  it.each(["0", "-0"])(
    "rejects unitless %s for font size while retaining zero-capable layout properties",
    (zero) => {
      const once = sanitizeRichText(
        `<span style="font-size:${zero}">Text</span><p style="margin:${zero};width:${zero}">Box</p>`,
      );

      expect(once).toContain("<span>Text</span>");
      expect(once).toContain('<p style="margin: 0px; width: 0px;">Box</p>');
      expect(once).not.toContain("font-size");
      expect(sanitizeRichText(once)).toBe(once);
    },
  );

  it("normalizes safe legacy declarations containing CSS comments idempotently", () => {
    const once = sanitizeRichText(
      '<span style="color:r/**/ed;font-size:1/**/8px">Commented style</span>',
    );

    expect(once).toContain('style="color: red; font-size: 18px;"');
    expect(sanitizeRichText(once)).toBe(once);
  });

  it("reparses unwrapped content-model-sensitive nodes before returning canonical HTML", () => {
    const once = sanitizeRichText("<li><section><li>x</li></section>");

    expect(once).toBe("<li></li><li>x</li>");
    expect(sanitizeRichText(once)).toBe(once);
  });

  it("recovers foster-parented escaped video markup on the first canonical pass", () => {
    const once = sanitizeRichText(
      `<table>&lt;video src=&quot;${VIDEO_URL}&quot;&gt;</table>`,
    );

    expect(once).toContain(`<video src="${VIDEO_URL}"></video>`);
    expect(once).not.toContain("&lt;video");
    expect(sanitizeRichText(once)).toBe(once);
  });

  it("removes foster-parented escaped orphan sources on the first canonical pass", () => {
    const once = sanitizeRichText(
      `<table>&lt;source src=&quot;${VIDEO_URL}&quot; type=&quot;video/mp4&quot;&gt;</table>`,
    );

    expect(once).not.toContain("source");
    expect(once).not.toContain(VIDEO_URL);
    expect(sanitizeRichText(once)).toBe(once);
  });
});

describe("normalizeRichTextUrl", () => {
  it.each([
    [IMAGE_URL, "image", IMAGE_URL],
    [PDF_URL, "attachment", PDF_URL],
    [`/litblogs${VIDEO_URL}`, "video", VIDEO_URL],
    ["https://school.example/library", "link", "https://school.example/library"],
  ])("normalizes the safe %s URL", (url, kind, expected) => {
    expect(normalizeRichTextUrl(url, kind)).toBe(expected);
  });

  it.each([
    ["javascript:alert(1)", "link"],
    ["java\nscript:alert(1)", "link"],
    ["data:text/html,<script>alert(1)</script>", "image"],
    ["vbscript:msgbox(1)", "link"],
    ["blob:https://school.example/id", "image"],
    ["file:///etc/passwd", "link"],
    ["https:///evil.example/path", "link"],
    ["https:////evil.example/path", "link"],
    ["/safe/%FF", "link"],
    ["/%C0%AE%C0%AE/admin", "link"],
    ["//tracker.example/file.pdf", "attachment"],
    ["\\\\tracker.example\\file.pdf", "attachment"],
    ["https://tracker.example/video.mp4", "video"],
    ["https://tracker.example/pixel.png", "image"],
    ["/uploads/files/42/reading.pdf", "attachment"],
    ["/api/uploads/files/42/reading.pdf", "attachment"],
    ["/uploads/files/42/../1/private.pdf", "attachment"],
    ["/uploads/files/42/%2e%2e/1/private.pdf", "attachment"],
    ["/uploads/files/42/reading.pdf::$DATA", "attachment"],
    ["/uploads/files/42/read%3Asecret.pdf", "attachment"],
    ["/uploads/files/42/read%ZZing.pdf", "attachment"],
  ])("rejects the unsafe %s URL for %s", (url, kind) => {
    expect(normalizeRichTextUrl(url, kind)).toBeNull();
  });
});
