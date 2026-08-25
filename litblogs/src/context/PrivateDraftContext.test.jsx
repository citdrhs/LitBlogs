// @vitest-environment jsdom

import { act, cleanup, render } from "@testing-library/react";
import { afterEach, describe, expect, it } from "vitest";

import { clearStoredAuth, logoutBrowserSession } from "../utils/auth.js";
import {
  PrivateDraftProvider,
  usePrivateDrafts,
} from "./PrivateDraftContext.jsx";


const postContext = {
  userId: 7,
  classId: "42",
  editingPostId: null,
};
const assignmentContext = {
  userId: 7,
  classId: "42",
  assignmentId: 17,
};


const mountProvider = () => {
  let drafts;
  const Capture = () => {
    drafts = usePrivateDrafts();
    return null;
  };
  const view = render(
    <PrivateDraftProvider>
      <Capture />
    </PrivateDraftProvider>,
  );
  return { view, get drafts() { return drafts; } };
};


describe("App-level private draft memory", () => {
  afterEach(() => {
    cleanup();
    localStorage.clear();
    sessionStorage.clear();
  });

  it("survives child SPA navigation while the App provider remains mounted", () => {
    const mounted = mountProvider();

    act(() => {
      mounted.drafts.savePostDraft({
        ...postContext,
        payload: {
          postTitle: "Private reflection",
          content: "private post body",
        },
      });
      mounted.drafts.saveAssignmentMemory(assignmentContext, {
        content: "unsent assignment response",
        revision: 3,
        dirty: true,
        status: "error",
      });
    });

    expect(mounted.drafts.getPostDraft(postContext)).toMatchObject({
      postTitle: "Private reflection",
    });
    expect(mounted.drafts.getAssignmentMemory(assignmentContext)).toEqual({
      content: "unsent assignment response",
      revision: 3,
      savedAt: null,
      dirty: true,
      status: "error",
    });

    // A route child may unmount/remount, but the provider stays at App scope.
    mounted.view.rerender(
      <PrivateDraftProvider>
        <div>different route</div>
      </PrivateDraftProvider>,
    );
    mounted.view.rerender(
      <PrivateDraftProvider>
        <DraftProbe context={assignmentContext} />
      </PrivateDraftProvider>,
    );
    expect(mounted.view.getByTestId("assignment-memory")).toHaveTextContent(
      "unsent assignment response",
    );
  });

  it("isolates drafts by stable user, class, and new/edit scope", () => {
    const mounted = mountProvider();
    act(() => {
      mounted.drafts.savePostDraft({
        ...postContext,
        payload: { postTitle: "class 42 new", content: "new" },
      });
      mounted.drafts.savePostDraft({
        ...postContext,
        editingPostId: 99,
        payload: { postTitle: "class 42 edit", content: "edit" },
      });
      mounted.drafts.savePostDraft({
        ...postContext,
        classId: "43",
        payload: { postTitle: "class 43 new", content: "other class" },
      });
    });

    expect(mounted.drafts.getPostDraft(postContext).postTitle).toBe("class 42 new");
    expect(mounted.drafts.getPostDraft({
      ...postContext,
      editingPostId: 99,
    }).postTitle).toBe("class 42 edit");
    expect(mounted.drafts.getPostDraft({
      ...postContext,
      classId: "43",
    }).postTitle).toBe("class 43 new");
    expect(mounted.drafts.getPostDraft({
      ...postContext,
      userId: 8,
    })).toBeNull();
  });

  it("clears naturally with a fresh provider/full refresh", () => {
    const first = mountProvider();
    act(() => {
      first.drafts.savePostDraft({
        ...postContext,
        payload: { postTitle: "refresh canary", content: "private" },
      });
    });
    first.view.unmount();

    const fresh = mountProvider();
    expect(fresh.drafts.getPostDraft(postContext)).toBeNull();
    expect(fresh.drafts.getAssignmentMemory(assignmentContext)).toBeNull();
  });

  it("clears private memory on session expiry and before a failed logout returns", async () => {
    const mounted = mountProvider();
    const seed = () => act(() => {
      mounted.drafts.savePostDraft({
        ...postContext,
        payload: { postTitle: "logout canary", content: "private" },
      });
      mounted.drafts.saveAssignmentMemory(assignmentContext, {
        content: "private assignment",
        revision: 1,
        dirty: true,
        status: "pending",
      });
    });

    seed();
    act(() => clearStoredAuth());
    expect(mounted.drafts.getPostDraft(postContext)).toBeNull();
    expect(mounted.drafts.getAssignmentMemory(assignmentContext)).toBeNull();

    seed();
    await expect(logoutBrowserSession({
      post: async () => { throw new Error("synthetic logout outage"); },
    })).rejects.toThrow("synthetic logout outage");
    expect(mounted.drafts.getPostDraft(postContext)).toBeNull();
    expect(mounted.drafts.getAssignmentMemory(assignmentContext)).toBeNull();
  });

  it("reports dirty, inflight, error, and unsaved post memory as unload risks", () => {
    const mounted = mountProvider();
    expect(mounted.drafts.hasRiskyDrafts({ userId: 7 })).toBe(false);

    act(() => {
      mounted.drafts.saveAssignmentMemory(assignmentContext, {
        content: "clean fallback after load error",
        revision: 0,
        dirty: false,
        status: "error",
      });
    });
    expect(mounted.drafts.hasRiskyDrafts({ userId: 7 })).toBe(false);

    act(() => {
      mounted.drafts.saveAssignmentMemory(assignmentContext, {
        content: "private assignment",
        revision: 0,
        dirty: false,
        status: "saving",
      });
    });
    expect(mounted.drafts.hasRiskyDrafts({ userId: 7 })).toBe(true);

    act(() => mounted.drafts.removeAssignmentMemory(assignmentContext));
    act(() => {
      mounted.drafts.savePostDraft({
        ...postContext,
        payload: { postTitle: "private post", content: "private" },
      });
    });
    expect(mounted.drafts.hasRiskyDrafts({ userId: 7 })).toBe(true);
    expect(mounted.drafts.hasRiskyDrafts({ userId: 8 })).toBe(false);
  });
});


const DraftProbe = ({ context }) => {
  const drafts = usePrivateDrafts();
  return (
    <div data-testid="assignment-memory">
      {drafts.getAssignmentMemory(context)?.content || "none"}
    </div>
  );
};
