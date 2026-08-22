import { describe, expect, it, vi } from "vitest";

import {
  normalizeRichTextUrl,
  sanitizeRichText,
} from "./richTextSecurity.js";

const parse = (html) => {
  const template = document.createElement("template");
  template.innerHTML = html;
  return template.content;
};

describe("sanitizeRichText", () => {
  it.each([
    '<img src="/uploads/images/42/photo.png" onerror="window.__xss = true"><script>window.__xss = true</script>',
    '&lt;img src=&quot;/uploads/images/42/photo.png&quot; onerror=&quot;window.__xss = true&quot;&gt;&lt;script&gt;window.__xss = true&lt;/script&gt;',
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
          &lt;source src=&quot;/uploads/videos/42/book-talk.mp4&quot; type=&quot;video/mp4&quot; onerror=&quot;window.__xss=true&quot;&gt;
        &lt;/video&gt;
      &lt;/figure&gt;
      <img src="/uploads/images/42/cover.png" alt="Book cover" onerror="window.__xss=true">
    `));

    expect(fragment.querySelector("figure.video-container video[controls]")).not.toBeNull();
    expect(fragment.querySelector("source")?.getAttribute("src")).toBe(
      "/api/uploads/videos/42/book-talk.mp4",
    );
    expect(fragment.querySelector("img")?.getAttribute("src")).toBe(
      "/api/uploads/images/42/cover.png",
    );
    expect(fragment.querySelector("[onplay], [onerror]")).toBeNull();
  });

  it("stays non-executable across repeated legacy entity normalization", () => {
    let normalized = `
      &lt;video controls&gt;&lt;source src=&quot;/uploads/videos/42/book-talk.mp4&quot; type=&quot;video/mp4&quot;&gt;&lt;/video&gt;
      &amp;lt;img src=&amp;quot;/uploads/images/42/cover.png&amp;quot; onerror=&amp;quot;window.__xss=true&amp;quot;&amp;gt;
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
      `<span>&lt;video src=&quot;/api/uploads/videos/42/video-${index}.mp4&quot; controls&gt;&lt;/video&gt;</span>`
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
      `<span>&lt;video src=&quot;/api/uploads/videos/42/bounded-${index}.mp4&quot; controls&gt;&lt;/video&gt;</span>`
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
          &lt;source src=&quot;/uploads/videos/42/book-talk.mp4&quot; type=&quot;video/mp4&quot;&gt;
        &lt;/video&gt;
      &lt;/figure&gt;
    `));

    expect(fragment.querySelector("figure.video-container video source")?.getAttribute("src")).toBe(
      "/api/uploads/videos/42/book-talk.mp4",
    );
    expect(fragment.querySelector("pre code div")).toBeNull();
    expect(fragment.querySelector("pre code")?.textContent).toContain("<div");
    expect(fragment.querySelector("a")).toBeNull();
    expect(fragment.textContent).toContain("<a href=");
  });

  it("keeps encoded video examples inert inside code blocks", () => {
    const fragment = parse(sanitizeRichText(`
      <pre><code>&lt;video src=&quot;/uploads/videos/42/example.mp4&quot; controls&gt;&lt;/video&gt;</code></pre>
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
    expect(fragment.querySelector("source")?.hasAttribute("src")).toBe(false);
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
      expect(fragment.querySelector("source")?.hasAttribute("src")).toBe(false);
    } finally {
      parserSpy.mockRestore();
    }
  });

  it("normalizes direct video sources to canonical local uploads", () => {
    const fragment = parse(sanitizeRichText(`
      <video id="safe" src="/uploads/videos/42/book-talk.mp4" controls></video>
      <video id="external" src="https://tracker.example/pixel.mp4" controls></video>
      <video id="data" src="data:video/mp4;base64,AAAA" controls></video>
    `));
    const videos = fragment.querySelectorAll("video");

    expect(videos[0]?.getAttribute("src")).toBe("/api/uploads/videos/42/book-talk.mp4");
    expect(videos[1]?.hasAttribute("src")).toBe(false);
    expect(videos[2]?.hasAttribute("src")).toBe(false);
  });

  it("drops pathological layout values while retaining bounded formatting", () => {
    const fragment = parse(sanitizeRichText(`
      <p id="unsafe" style="font-size: 999999999px; width: 999999999px; height: 999999999px; margin: 999999999px; max-width: 999999999px">Oversized</p>
      <p id="safe" style="font-size: 18px; width: 100%; max-width: 600px; margin: 12px 0">Bounded</p>
      <img src="/api/uploads/images/42/unsafe.png" width="999999999px" height="999999999px">
      <img src="/api/uploads/images/42/safe.png" width="100%" height="4096px">
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
      <div class="file-attachment" data-file-url="/uploads/files/42/reading.pdf">
        <button class="remove-btn editor-only" type="button" data-file-url="/uploads/files/42/reading.pdf" onclick="alert(1)">Remove</button>
      </div>
    `));
    const link = fragment.querySelector("a");

    expect(link?.getAttribute("href")).toBe("https://school.example/library");
    expect(link?.getAttribute("target")).toBe("_blank");
    expect(link?.getAttribute("rel")).toBe("noopener noreferrer");
    expect(fragment.querySelector(".editor-only, button")).toBeNull();
    expect(fragment.querySelector(".file-attachment")?.getAttribute("data-file-url")).toBe(
      "/api/uploads/files/42/reading.pdf",
    );
  });

  it("retains inert editor controls without inline code", () => {
    const fragment = parse(sanitizeRichText(`
      <button class="remove-btn editor-only" type="button" data-file-url="/uploads/files/42/reading.pdf" onclick="alert(1)">Remove</button>
    `, { mode: "editor" }));
    const button = fragment.querySelector("button");

    expect(button).not.toBeNull();
    expect(button?.getAttribute("type")).toBe("button");
    expect(button?.getAttribute("data-file-url")).toBe(
      "/api/uploads/files/42/reading.pdf",
    );
    expect(button?.hasAttribute("onclick")).toBe(false);
  });

  it("retains only safe local metadata for the trusted PDF renderer", () => {
    const safeFragment = parse(sanitizeRichText(`
      <div data-inline-pdf-viewer="true" data-pdf-url="/uploads/files/42/reading.pdf" data-pdf-title="Course reading"></div>
    `, { mode: "editor" }));
    const unsafeFragment = parse(sanitizeRichText(`
      <div data-inline-pdf-viewer="true" data-pdf-url="javascript:alert(1)" data-pdf-title="Course reading"></div>
    `, { mode: "editor" }));

    expect(safeFragment.querySelector("div")?.getAttribute("data-inline-pdf-viewer")).toBe("true");
    expect(safeFragment.querySelector("div")?.getAttribute("data-pdf-url")).toBe(
      "/api/uploads/files/42/reading.pdf",
    );
    expect(safeFragment.querySelector("div")?.getAttribute("data-pdf-title")).toBe("Course reading");
    expect(unsafeFragment.querySelector("div")?.hasAttribute("data-pdf-url")).toBe(false);
  });
});

describe("normalizeRichTextUrl", () => {
  it.each([
    ["/uploads/images/42/photo.png", "image", "/api/uploads/images/42/photo.png"],
    ["/api/uploads/files/42/reading.pdf", "attachment", "/api/uploads/files/42/reading.pdf"],
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
    ["//tracker.example/file.pdf", "attachment"],
    ["\\\\tracker.example\\file.pdf", "attachment"],
    ["https://tracker.example/video.mp4", "video"],
    ["https://tracker.example/pixel.png", "image"],
    ["/uploads/files/42/../1/private.pdf", "attachment"],
    ["/uploads/files/42/%2e%2e/1/private.pdf", "attachment"],
    ["/uploads/files/42/reading.pdf::$DATA", "attachment"],
    ["/uploads/files/42/read%3Asecret.pdf", "attachment"],
    ["/uploads/files/42/read%ZZing.pdf", "attachment"],
  ])("rejects the unsafe %s URL for %s", (url, kind) => {
    expect(normalizeRichTextUrl(url, kind)).toBeNull();
  });
});
