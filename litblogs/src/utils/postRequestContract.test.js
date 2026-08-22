import { describe, expect, it } from "vitest";

import {
  buildPostRequestPayload,
  canonicalizePostUploadReferences,
} from "./postRequestContract";

describe("post request contract", () => {
  it("keeps route-scoped class identity out of the request body", () => {
    expect(buildPostRequestPayload({
      title: "A title",
      content: "<p>Body</p>",
      classId: 42,
    })).toEqual({
      title: "A title",
      content: "<p>Body</p>",
    });
  });

  it("stores only canonical upload attributes behind a frontend base path", () => {
    const key = "objects/aa/aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa.png";
    const displayUrl = `/litblogs/api/uploads/${key}`;
    const content = [
      `<pre><code>${displayUrl}</code></pre>`,
      `<img src="${displayUrl}" alt="Bound image">`,
      `<div class="file-attachment" data-file-url="${displayUrl}"></div>`,
      `<img src="https://example.test/litblogs/api/uploads/${key}" alt="External">`,
    ].join("");

    const canonical = canonicalizePostUploadReferences(content, "/litblogs/api");

    expect(canonical).toContain(`<code>${displayUrl}</code>`);
    expect(canonical).toContain(`src="/api/uploads/${key}"`);
    expect(canonical).toContain(`data-file-url="/api/uploads/${key}"`);
    expect(canonical).toContain(`src="https://example.test/litblogs/api/uploads/${key}"`);
  });

  it("persists restored structured items using canonical registry URLs", () => {
    const imageKey = "objects/ab/abbbbbbbbbbbbbbbbbbbbbbbbbbbbbbb.png";
    const fileKey = "objects/ac/accccccccccccccccccccccccccccccc.pdf";

    expect(buildPostRequestPayload({
      title: "Restored draft",
      content: "<p>Body</p>",
      postContent: {
        media: [{
          type: "image",
          url: `/litblogs/api/uploads/${imageKey}`,
          alt: "Diagram",
        }],
        files: [{
          name: "reading.pdf",
          url: `/litblogs/api/uploads/${fileKey}`,
        }],
        codeSnippets: [{ language: "python", code: "print('hi')" }],
      },
      apiBasePath: "/litblogs/api",
    })).toEqual({
      title: "Restored draft",
      content: "<p>Body</p>",
      media: [{ type: "image", url: `/api/uploads/${imageKey}`, alt: "Diagram" }],
      files: [{ name: "reading.pdf", url: `/api/uploads/${fileKey}` }],
      code_snippets: [{ language: "python", code: "print('hi')" }],
    });
  });
});
