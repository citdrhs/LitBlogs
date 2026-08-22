import { describe, expect, it } from "vitest";

import { buildPostRequestPayload } from "./postRequestContract";

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
});
