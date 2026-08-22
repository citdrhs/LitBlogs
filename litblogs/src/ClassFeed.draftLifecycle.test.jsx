// @vitest-environment jsdom

import React from "react";
import {
  act,
  fireEvent,
  render,
  screen,
} from "@testing-library/react";
import {
  MemoryRouter,
  Route,
  Routes,
  useNavigate,
} from "react-router-dom";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import ClassFeed from "./ClassFeed.jsx";
import {
  PrivateDraftProvider,
  usePrivateDrafts,
} from "./context/PrivateDraftContext.jsx";


const mocks = vi.hoisted(() => {
  const toast = Object.assign(vi.fn(), {
    success: vi.fn(),
    error: vi.fn(),
  });
  return {
    axios: {
      get: vi.fn(),
      put: vi.fn(),
      post: vi.fn(),
      delete: vi.fn(),
    },
    toast,
  };
});

vi.mock("axios", () => ({ default: mocks.axios }));
vi.mock("react-hot-toast", () => ({ toast: mocks.toast }));
vi.mock("./components/Loader", () => ({
  default: () => <div>Loading test feed</div>,
}));
vi.mock("./components/Navbar", () => ({
  default: ({ onSignOut }) => <button onClick={onSignOut}>Sign Out</button>,
}));
vi.mock("./components/Footer", () => ({ default: () => null }));
vi.mock("./components/CommentThread", () => ({ default: () => null }));
vi.mock("./components/PdfViewerModal", () => ({
  openPdfViewerModal: vi.fn(),
}));
vi.mock("./utils/timeUtils", () => ({
  formatRelativeTime: () => "recently",
  setupTimeUpdater: () => undefined,
}));
vi.mock("./components/SelfHostedEditor", () => ({
  default: ({ value, onEditorChange }) => (
    <textarea
      aria-label="Post content"
      value={value}
      onChange={(event) => onEditorChange(event.target.value)}
    />
  ),
}));
vi.mock("framer-motion", async () => {
  const ReactModule = await import("react");
  const componentCache = new Map();
  const ignoredProps = new Set([
    "animate",
    "exit",
    "initial",
    "layout",
    "transition",
    "whileHover",
    "whileTap",
  ]);
  const motion = new Proxy({}, {
    get: (_target, tag) => {
      if (!componentCache.has(tag)) {
        componentCache.set(tag, ReactModule.forwardRef((props, ref) => {
          const domProps = Object.fromEntries(
            Object.entries(props).filter(([key]) => !ignoredProps.has(key)),
          );
          return ReactModule.createElement(tag, { ...domProps, ref });
        }));
      }
      return componentCache.get(tag);
    },
  });
  return {
    AnimatePresence: ({ children }) => children,
    motion,
  };
});


const PRIVATE_CANARY = "private route-switch response attachment.pdf";
const ASSIGNMENT = {
  id: 17,
  title: "Close reading response",
  description: "Respond to the chapter",
  due_date: "2099-08-22T12:00:00Z",
  allow_late: true,
  visibility: "class",
  my_submission: null,
  my_draft: null,
  my_draft_revision: 0,
};
const BASELINE_POST = {
  id: 99,
  owner_id: 7,
  title: "Baseline Post",
  content: "<p>Published baseline</p>",
  author: "Draft Student",
  created_at: "2026-08-22T10:00:00Z",
  comments: 0,
};

const flushPromises = async () => {
  await act(async () => {
    for (let index = 0; index < 8; index += 1) {
      await Promise.resolve();
    }
  });
};

const NavigationControls = () => {
  const navigate = useNavigate();
  return (
    <nav>
      <button onClick={() => navigate("/class-feed/1")}>Go class one</button>
      <button onClick={() => navigate("/class-feed/2")}>Go class two</button>
      <button onClick={() => navigate("/elsewhere")}>Go elsewhere</button>
    </nav>
  );
};

const DraftProbe = () => {
  const { getAssignmentMemory, postDrafts } = usePrivateDrafts();
  const classOneAssignment = getAssignmentMemory({
    userId: 7,
    classId: "1",
    assignmentId: 17,
  });
  const classTwoAssignment = getAssignmentMemory({
    userId: 7,
    classId: "2",
    assignmentId: 17,
  });
  return (
    <>
      <output data-testid="post-draft-probe">
        {postDrafts.map((draft) => `${draft.classId}:${draft.postTitle}`).join("|") || "none"}
      </output>
      <output data-testid="assignment-draft-probe">
        {`1:${classOneAssignment?.content || "none"}|2:${classTwoAssignment?.content || "none"}`}
      </output>
    </>
  );
};

const renderFeed = () => render(
  <MemoryRouter initialEntries={["/class-feed/1"]}>
    <PrivateDraftProvider>
      <NavigationControls />
      <DraftProbe />
      <Routes>
        <Route path="/class-feed/:classId" element={<ClassFeed />} />
        <Route path="/elsewhere" element={<div>Elsewhere route</div>} />
      </Routes>
    </PrivateDraftProvider>
  </MemoryRouter>,
);

const assignmentServerPayload = (content = "", revision = 0) => ({
  has_draft: Boolean(content),
  content,
  saved_at: content ? "2026-08-22T11:00:00Z" : null,
  revision,
});

const installDefaultHttpResponses = () => {
  mocks.axios.get.mockImplementation(async (url) => {
    if (url === "/user/settings") {
      return {
        data: {
          remember_drafts: true,
          editor_font_size: "medium",
          auto_play_videos: false,
          email_notifications: false,
          assignment_reminders: false,
        },
      };
    }
    if (url === "/classes/1/details") return { data: { id: 1, name: "Class One" } };
    if (url === "/classes/2/details") return { data: { id: 2, name: "Class Two" } };
    if (url === "/classes/1/posts") return { data: [BASELINE_POST] };
    if (url === "/classes/2/posts") return { data: [] };
    if (url === "/classes/1/assignments") return { data: [ASSIGNMENT] };
    if (url === "/classes/2/assignments") return { data: [] };
    if (url === "/assignments/17/draft") {
      return { data: assignmentServerPayload() };
    }
    if (url === "/classes/1/posts/99") return { data: BASELINE_POST };
    if (url === "/classes/1/posts/99/likes") {
      return { data: { like_count: 0, user_liked: false } };
    }
    if (url === "/classes/1/posts/99/comments?limit=1") {
      return { data: { total: 0 } };
    }
    throw new Error(`Unexpected GET ${url}`);
  });
  mocks.axios.put.mockResolvedValue({
    data: assignmentServerPayload(PRIVATE_CANARY, 1),
  });
  mocks.axios.post.mockResolvedValue({ data: {} });
  mocks.axios.delete.mockResolvedValue({ data: {} });
};


describe("ClassFeed private draft lifecycle", () => {
  beforeEach(() => {
    localStorage.clear();
    sessionStorage.clear();
    sessionStorage.setItem("user_info", JSON.stringify({
      userId: 7,
      username: "draft-student",
      firstName: "Draft",
      role: "STUDENT",
    }));
    vi.clearAllMocks();
    installDefaultHttpResponses();
  });

  afterEach(() => {
    vi.useRealTimers();
    vi.unstubAllGlobals();
  });

  it("hides the submission review control from students", async () => {
    renderFeed();
    await flushPromises();

    expect(screen.getByRole("button", { name: "Submit" })).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "Open Submissions" })).not.toBeInTheDocument();
  });

  it("labels assignment audience without promising peer-visible submissions", async () => {
    renderFeed();
    await flushPromises();

    expect(screen.getByText("Visible to Students")).toBeInTheDocument();
    expect(screen.queryByText("Public Submissions")).not.toBeInTheDocument();
  });

  it("does not autosave a programmatic assignment load, then guards and debounces a user edit", async () => {
    renderFeed();
    await flushPromises();
    fireEvent.click(screen.getByRole("button", { name: "Submit" }));
    await flushPromises();

    vi.useFakeTimers();
    await act(async () => vi.advanceTimersByTimeAsync(600));
    expect(mocks.axios.put).not.toHaveBeenCalled();

    const storageWrite = vi.spyOn(Storage.prototype, "setItem");
    fireEvent.change(screen.getByPlaceholderText("Write your submission..."), {
      target: { value: PRIVATE_CANARY },
    });
    await flushPromises();

    const unload = new Event("beforeunload", { cancelable: true });
    window.dispatchEvent(unload);
    expect(unload.defaultPrevented).toBe(true);

    await act(async () => vi.advanceTimersByTimeAsync(499));
    expect(mocks.axios.put).not.toHaveBeenCalled();
    await act(async () => vi.advanceTimersByTimeAsync(1));
    await flushPromises();
    expect(mocks.axios.put).toHaveBeenCalledWith(
      "/assignments/17/draft",
      { content: PRIVATE_CANARY, expected_revision: 0 },
      expect.objectContaining({ signal: expect.any(AbortSignal) }),
    );
    expect(storageWrite.mock.calls.flat().join(" ")).not.toContain(PRIVATE_CANARY);
  });

  it("keeps a failed close controlled and offers explicit discard without recreating the draft", async () => {
    let rejectClose;
    mocks.axios.put.mockImplementation(() => new Promise((_resolve, reject) => {
      rejectClose = reject;
    }));
    vi.stubGlobal("confirm", vi.fn(() => true));
    renderFeed();
    await flushPromises();
    fireEvent.click(screen.getByRole("button", { name: "Submit" }));
    await flushPromises();

    fireEvent.change(screen.getByPlaceholderText("Write your submission..."), {
      target: { value: PRIVATE_CANARY },
    });
    fireEvent.click(screen.getByRole("button", { name: "Cancel" }));
    await flushPromises();
    expect(screen.getByRole("button", { name: "Saving..." })).toBeDisabled();
    expect(screen.getByDisplayValue(PRIVATE_CANARY)).toBeInTheDocument();

    await act(async () => rejectClose(new Error("synthetic close outage")));
    await flushPromises();
    expect(screen.getByDisplayValue(PRIVATE_CANARY)).toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: "Discard unsaved changes" }));
    expect(screen.queryByDisplayValue(PRIVATE_CANARY)).not.toBeInTheDocument();

    vi.useFakeTimers();
    await act(async () => vi.advanceTimersByTimeAsync(1000));
    expect(mocks.axios.put).toHaveBeenCalledTimes(1);
  });

  it("keeps content after a delayed accepted save makes submission revision stale", async () => {
    let resolveDelayedSave;
    mocks.axios.put.mockImplementation(() => new Promise((resolve) => {
      resolveDelayedSave = resolve;
    }));
    mocks.axios.post.mockRejectedValueOnce({
      response: {
        status: 409,
        data: { detail: "Assignment draft changed in another session" },
      },
    });
    renderFeed();
    await flushPromises();
    fireEvent.click(screen.getByRole("button", { name: "Submit" }));
    await flushPromises();

    vi.useFakeTimers();
    fireEvent.change(screen.getByPlaceholderText("Write your submission..."), {
      target: { value: PRIVATE_CANARY },
    });
    await act(async () => vi.advanceTimersByTimeAsync(500));
    await flushPromises();
    expect(mocks.axios.put).toHaveBeenCalledTimes(1);
    expect(mocks.axios.put.mock.calls[0][2].signal.aborted).toBe(false);

    fireEvent.click(screen.getAllByRole("button", { name: "Submit" }).at(-1));
    await flushPromises();
    expect(mocks.axios.post).toHaveBeenCalledWith("/assignments/17/submit", {
      content: PRIVATE_CANARY,
      expected_draft_revision: 0,
    }, expect.objectContaining({ signal: expect.any(AbortSignal) }));
    expect(screen.getByDisplayValue(PRIVATE_CANARY)).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Discard unsaved changes" })).toBeEnabled();

    await act(async () => resolveDelayedSave({
      data: assignmentServerPayload(PRIVATE_CANARY, 1),
    }));
    await flushPromises();
    expect(screen.getByDisplayValue(PRIVATE_CANARY)).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Discard unsaved changes" })).toBeEnabled();
  });

  it("does not autosave an edit baseline or recreate it after discard", async () => {
    vi.stubGlobal("confirm", vi.fn(() => true));
    renderFeed();
    await flushPromises();

    fireEvent.click(screen.getByRole("button", { name: "Post actions for Baseline Post" }));
    fireEvent.click(screen.getByRole("menuitem", { name: "Edit Post" }));
    await flushPromises();

    vi.useFakeTimers();
    await act(async () => vi.advanceTimersByTimeAsync(600));
    expect(screen.getByTestId("post-draft-probe")).toHaveTextContent("none");

    fireEvent.change(screen.getByLabelText("Post Title (Required)"), {
      target: { value: "Private edited title" },
    });
    await act(async () => vi.advanceTimersByTimeAsync(500));
    expect(screen.getByTestId("post-draft-probe")).toHaveTextContent(
      "1:Private edited title",
    );

    fireEvent.click(screen.getByRole("button", { name: "Discard Draft" }));
    await flushPromises();
    await act(async () => vi.advanceTimersByTimeAsync(600));
    expect(screen.getByTestId("post-draft-probe")).toHaveTextContent("none");
    expect(screen.getByLabelText("Post Title (Required)")).toHaveValue("Baseline Post");
  });

  it("snapshots before a class route switch, resets the composer, and restores only in the original class", async () => {
    renderFeed();
    await flushPromises();
    fireEvent.click(screen.getByRole("button", { name: "Create New Post" }));
    await flushPromises();
    fireEvent.change(screen.getByLabelText("Post Title (Required)"), {
      target: { value: "Class one private draft" },
    });
    fireEvent.change(screen.getByLabelText("Post content"), {
      target: { value: PRIVATE_CANARY },
    });

    // Switch before the debounce fires. The old class snapshot must be kept in
    // provider memory, while its composer is never publishable in class two.
    fireEvent.click(screen.getByRole("button", { name: "Go class two" }));
    await flushPromises();
    expect(screen.getByText("Class Two")).toBeInTheDocument();
    expect(screen.queryByLabelText("Post Title (Required)")).not.toBeInTheDocument();
    expect(screen.getByTestId("post-draft-probe")).toHaveTextContent(
      "1:Class one private draft",
    );

    fireEvent.click(screen.getByRole("button", { name: "Go class one" }));
    await flushPromises();
    expect(screen.getByText("Class one private draft")).toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: "Resume" }));
    expect(screen.getByLabelText("Post Title (Required)")).toHaveValue(
      "Class one private draft",
    );
    expect(screen.getByLabelText("Post content")).toHaveValue(PRIVATE_CANARY);
  });

  it("preserves unsent assignment memory across SPA navigation without exposing it in another class", async () => {
    renderFeed();
    await flushPromises();
    fireEvent.click(screen.getByRole("button", { name: "Submit" }));
    await flushPromises();
    fireEvent.change(screen.getByPlaceholderText("Write your submission..."), {
      target: { value: PRIVATE_CANARY },
    });

    fireEvent.click(screen.getByRole("button", { name: "Go class two" }));
    await flushPromises();
    expect(screen.getByText("Class Two")).toBeInTheDocument();
    expect(screen.queryByDisplayValue(PRIVATE_CANARY)).not.toBeInTheDocument();

    fireEvent.click(screen.getByRole("button", { name: "Go class one" }));
    await flushPromises();
    fireEvent.click(screen.getByRole("button", { name: "Submit" }));
    expect(screen.getByDisplayValue(PRIVATE_CANARY)).toBeInTheDocument();
    expect(mocks.axios.get.mock.calls.filter(
      ([url]) => url === "/assignments/17/draft",
    )).toHaveLength(1);
  });

  it("snapshots a dirty composer when ClassFeed unmounts for another SPA route", async () => {
    renderFeed();
    await flushPromises();
    fireEvent.click(screen.getByRole("button", { name: "Create New Post" }));
    await flushPromises();
    fireEvent.change(screen.getByLabelText("Post Title (Required)"), {
      target: { value: "Unmount-safe private draft" },
    });
    fireEvent.change(screen.getByLabelText("Post content"), {
      target: { value: PRIVATE_CANARY },
    });

    fireEvent.click(screen.getByRole("button", { name: "Go elsewhere" }));
    expect(screen.getByText("Elsewhere route")).toBeInTheDocument();
    expect(screen.getByTestId("post-draft-probe")).toHaveTextContent(
      "1:Unmount-safe private draft",
    );

    fireEvent.click(screen.getByRole("button", { name: "Go class one" }));
    await flushPromises();
    fireEvent.click(screen.getByRole("button", { name: "Resume" }));
    expect(screen.getByLabelText("Post Title (Required)")).toHaveValue(
      "Unmount-safe private draft",
    );
  });

  it("keeps an existing new-post draft when a blank new composer is canceled", async () => {
    renderFeed();
    await flushPromises();
    fireEvent.click(screen.getByRole("button", { name: "Create New Post" }));
    fireEvent.change(screen.getByLabelText("Post Title (Required)"), {
      target: { value: "Saved new-post draft" },
    });
    fireEvent.click(screen.getByRole("button", { name: "Save Draft" }));
    expect(screen.getByTestId("post-draft-probe")).toHaveTextContent(
      "1:Saved new-post draft",
    );

    fireEvent.click(screen.getByRole("button", { name: "Cancel" }));
    fireEvent.click(screen.getByRole("button", { name: "Create New Post" }));
    expect(screen.getByLabelText("Post Title (Required)")).toHaveValue("");
    fireEvent.click(screen.getByRole("button", { name: "Cancel" }));

    expect(screen.getByTestId("post-draft-probe")).toHaveTextContent(
      "1:Saved new-post draft",
    );
  });

  it("does not fabricate a draft when an untouched published post edit is canceled", async () => {
    renderFeed();
    await flushPromises();
    fireEvent.click(screen.getByRole("button", { name: "Post actions for Baseline Post" }));
    fireEvent.click(screen.getByRole("menuitem", { name: "Edit Post" }));
    await flushPromises();
    expect(screen.getByLabelText("Post Title (Required)")).toHaveValue("Baseline Post");

    fireEvent.click(screen.getByRole("button", { name: "Cancel" }));

    expect(screen.getByTestId("post-draft-probe")).toHaveTextContent("none");
  });

  it("keeps a successful submission successful when the follow-up list refresh fails", async () => {
    renderFeed();
    await flushPromises();
    fireEvent.click(screen.getByRole("button", { name: "Submit" }));
    await flushPromises();
    fireEvent.change(screen.getByPlaceholderText("Write your submission..."), {
      target: { value: PRIVATE_CANARY },
    });
    mocks.axios.post.mockResolvedValueOnce({
      data: { id: 501, content: PRIVATE_CANARY, draft_revision: 1 },
    });
    const defaultGet = mocks.axios.get.getMockImplementation();
    mocks.axios.get.mockImplementation(async (url, config) => {
      if (url === "/classes/1/assignments") {
        throw new Error("synthetic refresh outage");
      }
      return defaultGet(url, config);
    });

    fireEvent.click(screen.getAllByRole("button", { name: "Submit" }).at(-1));
    await flushPromises();

    expect(screen.queryByPlaceholderText("Write your submission...")).not.toBeInTheDocument();
    expect(screen.getByTestId("assignment-draft-probe")).toHaveTextContent("1:none");
    expect(mocks.toast.success).toHaveBeenCalledWith("Assignment submitted successfully!");
    expect(mocks.toast.error).not.toHaveBeenCalledWith("Failed to submit assignment");
  });

  it("ignores a delayed class-one close completion after switching classes", async () => {
    let resolveClose;
    mocks.axios.put.mockImplementation(() => new Promise((resolve) => {
      resolveClose = resolve;
    }));
    renderFeed();
    await flushPromises();
    fireEvent.click(screen.getByRole("button", { name: "Submit" }));
    await flushPromises();
    fireEvent.change(screen.getByPlaceholderText("Write your submission..."), {
      target: { value: PRIVATE_CANARY },
    });
    fireEvent.click(screen.getByRole("button", { name: "Cancel" }));
    await flushPromises();

    fireEvent.click(screen.getByRole("button", { name: "Go class two" }));
    await flushPromises();
    await act(async () => resolveClose({
      data: assignmentServerPayload(PRIVATE_CANARY, 1),
    }));
    await flushPromises();

    expect(screen.getByText("Class Two")).toBeInTheDocument();
    expect(screen.getByTestId("assignment-draft-probe")).toHaveTextContent(
      `1:${PRIVATE_CANARY}|2:none`,
    );
    expect(screen.queryByDisplayValue(PRIVATE_CANARY)).not.toBeInTheDocument();
  });

  it("ignores a delayed class-one submit completion and never starts its stale refresh", async () => {
    let resolveSubmit;
    mocks.axios.post.mockImplementation(() => new Promise((resolve) => {
      resolveSubmit = resolve;
    }));
    renderFeed();
    await flushPromises();
    fireEvent.click(screen.getByRole("button", { name: "Submit" }));
    await flushPromises();
    fireEvent.change(screen.getByPlaceholderText("Write your submission..."), {
      target: { value: PRIVATE_CANARY },
    });
    fireEvent.click(screen.getAllByRole("button", { name: "Submit" }).at(-1));
    await flushPromises();

    fireEvent.click(screen.getByRole("button", { name: "Go class two" }));
    await flushPromises();
    await act(async () => resolveSubmit({
      data: { id: 501, content: PRIVATE_CANARY, draft_revision: 1 },
    }));
    await flushPromises();

    expect(screen.getByText("Class Two")).toBeInTheDocument();
    expect(screen.getByTestId("assignment-draft-probe")).toHaveTextContent(
      `1:${PRIVATE_CANARY}|2:none`,
    );
    expect(mocks.axios.get.mock.calls.filter(
      ([url]) => url === "/classes/1/assignments",
    )).toHaveLength(1);
    expect(mocks.toast.success).not.toHaveBeenCalledWith(
      "Assignment submitted successfully!",
    );
  });

  it("does not warn for a clean load error and retries when the assignment is reopened", async () => {
    let draftLoads = 0;
    const defaultGet = mocks.axios.get.getMockImplementation();
    mocks.axios.get.mockImplementation(async (url, config) => {
      if (url === "/assignments/17/draft") {
        draftLoads += 1;
        if (draftLoads === 1) throw new Error("synthetic draft load outage");
        return { data: assignmentServerPayload("Recovered server draft", 4) };
      }
      return defaultGet(url, config);
    });
    renderFeed();
    await flushPromises();
    fireEvent.click(screen.getByRole("button", { name: "Submit" }));
    await flushPromises();

    const unload = new Event("beforeunload", { cancelable: true });
    window.dispatchEvent(unload);
    expect(unload.defaultPrevented).toBe(false);
    fireEvent.click(screen.getByRole("button", { name: "Cancel" }));
    fireEvent.click(screen.getByRole("button", { name: "Submit" }));
    await flushPromises();

    expect(draftLoads).toBe(2);
    expect(screen.getByDisplayValue("Recovered server draft")).toBeInTheDocument();
  });

  it("offers an explicit retry after a clean assignment draft load error", async () => {
    let draftLoads = 0;
    const defaultGet = mocks.axios.get.getMockImplementation();
    mocks.axios.get.mockImplementation(async (url, config) => {
      if (url === "/assignments/17/draft") {
        draftLoads += 1;
        if (draftLoads === 1) throw new Error("synthetic draft load outage");
        return { data: assignmentServerPayload("Retry recovered draft", 3) };
      }
      return defaultGet(url, config);
    });
    renderFeed();
    await flushPromises();
    fireEvent.click(screen.getByRole("button", { name: "Submit" }));
    await flushPromises();

    fireEvent.click(screen.getByRole("button", { name: "Retry loading" }));
    await flushPromises();

    expect(draftLoads).toBe(2);
    expect(screen.getByDisplayValue("Retry recovered draft")).toBeInTheDocument();
  });
});
