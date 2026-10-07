// @vitest-environment jsdom

import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import {
  findPostDraft,
  loadAssignmentDraft,
  removePostDraft,
  saveAssignmentDraft,
  submitAssignment,
  uploadAssignmentEditorAsset,
  upsertPostDraft,
} from "./privateDrafts.js";

const PRIVATE_CANARY = "private student draft with attachment-metadata.pdf";

const snapshotBrowserState = () => ({
  local: { ...localStorage },
  session: { ...sessionStorage },
});

describe("private assignment drafts", () => {
  beforeEach(() => {
    localStorage.clear();
    sessionStorage.clear();
  });

  it("recovers a saved assignment draft from the authenticated server after a fresh page state", async () => {
    let serverDraft = null;
    const client = {
      put: vi.fn(async (_url, payload) => {
        serverDraft = {
          has_draft: Boolean(payload.content),
          content: payload.content,
          content_format: payload.content_format,
          saved_at: "2026-08-22T05:25:00Z",
          revision: payload.expected_revision + 1,
        };
        return { data: serverDraft };
      }),
      get: vi.fn(async () => ({ data: serverDraft })),
    };

    await expect(saveAssignmentDraft(client, 17, PRIVATE_CANARY, 0)).resolves.toEqual({
      hasDraft: true,
      content: PRIVATE_CANARY,
      contentFormat: "rich",
      savedAt: "2026-08-22T05:25:00Z",
      revision: 1,
    });

    // A reload starts with no component memory. Recovery must come from the
    // authorized server endpoint, never browser persistence.
    const recovered = await loadAssignmentDraft(client, 17);

    expect(client.put).toHaveBeenCalledWith("/assignments/17/draft", {
      content: PRIVATE_CANARY,
      content_format: "rich",
      expected_revision: 0,
    });
    expect(client.get).toHaveBeenCalledWith("/assignments/17/draft");
    expect(recovered).toEqual({
      hasDraft: true,
      content: PRIVATE_CANARY,
      contentFormat: "rich",
      savedAt: "2026-08-22T05:25:00Z",
      revision: 1,
    });
    expect(snapshotBrowserState()).toEqual({ local: {}, session: {} });
  });

  it("keeps unsent content out of browser persistence when server autosave fails", async () => {
    localStorage.setItem("darkMode", "true");
    sessionStorage.setItem("user_info", '{"userId":7}');
    const initialBrowserState = snapshotBrowserState();
    const client = {
      put: vi.fn(async () => {
        throw new Error("synthetic autosave outage");
      }),
    };

    await expect(saveAssignmentDraft(client, 17, PRIVATE_CANARY, 0)).rejects.toThrow(
      "synthetic autosave outage",
    );

    expect(snapshotBrowserState()).toEqual(initialBrowserState);
    expect(JSON.stringify(snapshotBrowserState())).not.toContain(PRIVATE_CANARY);
  });

  it("forwards an abort signal so stale autosaves cannot race submission or close", async () => {
    const controller = new AbortController();
    const client = {
      put: vi.fn(async () => ({
        data: {
          has_draft: true,
          content: PRIVATE_CANARY,
          saved_at: null,
          revision: 5,
        },
      })),
    };

    await saveAssignmentDraft(client, 17, PRIVATE_CANARY, 4, {
      signal: controller.signal,
    });

    expect(client.put).toHaveBeenCalledWith(
      "/assignments/17/draft",
      { content: PRIVATE_CANARY, content_format: "rich", expected_revision: 4 },
      { signal: controller.signal },
    );
  });

  it("submits against the exact draft revision and returns the tombstone revision", async () => {
    const client = {
      post: vi.fn(async () => ({
        data: { id: 8, content: PRIVATE_CANARY, draft_revision: 6 },
      })),
    };

    await expect(submitAssignment(client, 17, PRIVATE_CANARY, 5)).resolves.toMatchObject({
      id: 8,
      draft_revision: 6,
    });
    expect(client.post).toHaveBeenCalledWith("/assignments/17/submit", {
      content: PRIVATE_CANARY,
      content_format: "rich",
      expected_draft_revision: 5,
    });
  });

  it("saves and submits an image-only rich response with the same draft revision contract", async () => {
    const imageUrl = `/api/uploads/objects/ab/${"ab".repeat(16)}.png`;
    const html = `<p><img src="${imageUrl}" alt="Drawing"></p>`;
    const client = {
      put: vi.fn(async () => ({ data: {
        has_draft: true,
        content: html,
        content_format: "rich",
        saved_at: "2026-08-22T05:25:00Z",
        revision: 2,
      } })),
      post: vi.fn(async () => ({ data: { id: 9, content: html, content_format: "rich", draft_revision: 3 } })),
    };

    await expect(saveAssignmentDraft(client, 17, html, 1)).resolves.toMatchObject({
      hasDraft: true,
      content: html,
      contentFormat: "rich",
      revision: 2,
    });
    expect(client.put).toHaveBeenCalledWith("/assignments/17/draft", {
      content: html,
      content_format: "rich",
      expected_revision: 1,
    });

    await submitAssignment(client, 17, html, 2);
    expect(client.post).toHaveBeenCalledWith("/assignments/17/submit", {
      content: html,
      content_format: "rich",
      expected_draft_revision: 2,
    });
  });

  it("uploads scoped editor media and rejects a noncanonical returned URL", async () => {
    const imageUrl = `/api/uploads/objects/ab/${"ab".repeat(16)}.png`;
    const file = new File(["png data"], "drawing.png", { type: "image/png" });
    const client = { post: vi.fn(async () => ({ data: { url: imageUrl } })) };

    await expect(uploadAssignmentEditorAsset(client, 17, { kind: "image", file })).resolves.toMatchObject({
      kind: "image",
      url: imageUrl,
    });
    expect(client.post).toHaveBeenCalledWith(
      "/assignments/17/upload/image",
      expect.any(FormData),
      expect.any(Object),
    );
    expect(client.post.mock.calls[0][1].get("file")).toBe(file);

    client.post.mockResolvedValueOnce({ data: { url: "https://elsewhere.invalid/private.png" } });
    await expect(uploadAssignmentEditorAsset(client, 17, { kind: "image", file })).rejects.toThrow("invalid upload response");
    await expect(uploadAssignmentEditorAsset(client, 17, { kind: "image", file: new File(["bad"], "work.pdf", { type: "application/pdf" }) }))
      .rejects.toThrow("supported file type");
    expect(client.post).toHaveBeenCalledTimes(2);
  });

  it.each([
    ["video", "lesson.mp4", "video/mp4", "video", "mp4"],
    ["pdf", "reading.pdf", "application/pdf", "file", "pdf"],
  ])("routes %s to the matching private assignment endpoint", async (kind, name, type, endpointKind, extension) => {
    const file = new File(["media"], name, { type });
    const url = `/api/uploads/objects/ab/${"ab".repeat(16)}.${extension}`;
    const client = { post: vi.fn(async () => ({ data: { url } })) };

    await expect(uploadAssignmentEditorAsset(client, 17, { kind, file })).resolves.toMatchObject({
      kind,
      url,
    });
    expect(client.post).toHaveBeenCalledWith(
      `/assignments/17/upload/${endpointKind}`,
      expect.any(FormData),
      expect.any(Object),
    );
  });

  it("rejects missing, negative, and unbounded revisions before any request", async () => {
    const client = { put: vi.fn(), post: vi.fn() };

    for (const revision of [undefined, -1, 2_147_483_647]) {
      await expect(saveAssignmentDraft(
        client,
        17,
        PRIVATE_CANARY,
        revision,
      )).rejects.toThrow("revision");
      await expect(submitAssignment(
        client,
        17,
        PRIVATE_CANARY,
        revision,
      )).rejects.toThrow("revision");
    }
    expect(client.put).not.toHaveBeenCalled();
    expect(client.post).not.toHaveBeenCalled();
  });
});

describe("private post drafts", () => {
  const context = {
    classId: "42",
    userId: 7,
    editingPostId: null,
  };
  const payload = {
    postTitle: "Private reflection",
    content: `<p>${PRIVATE_CANARY}</p>`,
    postContent: {
      text: PRIVATE_CANARY,
      media: [{ url: "/api/uploads/private-image", alt: "private image" }],
      files: [{ url: "/api/uploads/private-file", name: "private.pdf" }],
      expandableLists: [],
      codeSnippets: [],
    },
  };

  beforeEach(() => {
    localStorage.clear();
    sessionStorage.clear();
  });

  afterEach(() => {
    vi.restoreAllMocks();
    vi.unstubAllGlobals();
  });

  it("keeps post drafts only in the caller-owned in-memory collection", () => {
    const saved = upsertPostDraft([], {
      ...context,
      payload,
      savedAt: "2026-08-22T05:26:00Z",
    });

    expect(findPostDraft(saved.drafts, context)).toMatchObject({
      postTitle: "Private reflection",
      content: `<p>${PRIVATE_CANARY}</p>`,
      savedAt: "2026-08-22T05:26:00Z",
    });
    expect(JSON.stringify(snapshotBrowserState())).not.toContain(PRIVATE_CANARY);
    expect(localStorage.length).toBe(0);
    expect(sessionStorage.length).toBe(0);
  });

  it("does not recover a post draft after a fresh page state", () => {
    const saved = upsertPostDraft([], { ...context, payload });

    expect(findPostDraft(saved.drafts, context)).not.toBeNull();
    expect(findPostDraft([], context)).toBeNull();
  });

  it("removes only the selected in-memory draft", () => {
    const newPost = upsertPostDraft([], { ...context, payload }).drafts;
    const withEdit = upsertPostDraft(newPost, {
      ...context,
      editingPostId: 99,
      payload: { ...payload, postTitle: "Private edit" },
    }).drafts;

    const remaining = removePostDraft(withEdit, {
      ...context,
      editingPostId: null,
    });

    expect(findPostDraft(remaining, context)).toBeNull();
    expect(findPostDraft(remaining, { ...context, editingPostId: 99 })).toMatchObject({
      postTitle: "Private edit",
    });
  });

  it("drops empty snapshots instead of retaining stale private data", () => {
    const saved = upsertPostDraft([], { ...context, payload }).drafts;
    const cleared = upsertPostDraft(saved, {
      ...context,
      payload: {
        postTitle: "",
        content: "",
        postContent: {
          text: "",
          media: [],
          files: [],
          expandableLists: [],
          codeSnippets: [],
        },
      },
    });

    expect(cleared.savedAt).toBeNull();
    expect(cleared.drafts).toEqual([]);
  });

  it("never writes a private payload to any durable browser sink under an arbitrary key", async () => {
    const storageWrite = vi.spyOn(Storage.prototype, "setItem");
    const idbOpen = vi.fn();
    const cacheOpen = vi.fn();
    const historyPush = vi.spyOn(history, "pushState");
    const historyReplace = vi.spyOn(history, "replaceState");
    const objectUrl = vi.fn();
    const previousObjectUrl = Object.getOwnPropertyDescriptor(URL, "createObjectURL");
    Object.defineProperty(URL, "createObjectURL", {
      configurable: true,
      value: objectUrl,
    });
    vi.stubGlobal("indexedDB", { open: idbOpen });
    vi.stubGlobal("caches", { open: cacheOpen });

    try {
      upsertPostDraft([], { ...context, payload });
      await expect(saveAssignmentDraft(
        { put: vi.fn(async () => { throw new Error("offline"); }) },
        17,
        PRIVATE_CANARY,
        0,
      )).rejects.toThrow("offline");

      expect(storageWrite).not.toHaveBeenCalled();
      expect(idbOpen).not.toHaveBeenCalled();
      expect(cacheOpen).not.toHaveBeenCalled();
      expect(objectUrl).not.toHaveBeenCalled();
      expect(historyPush).not.toHaveBeenCalled();
      expect(historyReplace).not.toHaveBeenCalled();
    } finally {
      if (previousObjectUrl) {
        Object.defineProperty(URL, "createObjectURL", previousObjectUrl);
      } else {
        delete URL.createObjectURL;
      }
    }
  });
});
