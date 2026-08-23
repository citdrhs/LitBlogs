import React from "react";
import { fireEvent, render, screen } from "@testing-library/react";
import { MemoryRouter, Route, Routes } from "react-router-dom";
import { beforeEach, describe, expect, it, vi } from "vitest";

import PostView from "./PostView";
import StudentHub from "./StudentHub";
import ClassDetails from "./components/ClassDetails";
import StudentDetails from "./components/StudentDetails";

const mocks = vi.hoisted(() => ({
  axios: {
    get: vi.fn(),
    post: vi.fn(),
    put: vi.fn(),
  },
}));

vi.mock("axios", () => ({ default: mocks.axios }));
vi.mock("framer-motion", async () => {
  const { createElement, Fragment } = await import("react");
  const motionElement = (tag) => ({
    children,
    initial: _initial,
    animate: _animate,
    exit: _exit,
    transition: _transition,
    whileHover: _whileHover,
    whileTap: _whileTap,
    ...props
  }) => createElement(tag, props, children);

  return {
    AnimatePresence: ({ children }) => createElement(Fragment, null, children),
    motion: {
      button: motionElement("button"),
      div: motionElement("div"),
    },
  };
});
vi.mock("./components/Loader", () => ({ default: () => <p>Loading</p> }));
vi.mock("./components/Navbar", () => ({ default: () => <nav>Navigation</nav> }));
vi.mock("./components/Footer", () => ({ default: () => <footer>Footer</footer> }));
vi.mock("./components/CommentThread", () => ({ default: () => <div>Comment thread</div> }));
vi.mock("react-hot-toast", () => ({
  default: { error: vi.fn(), success: vi.fn() },
  toast: { error: vi.fn(), success: vi.fn() },
}));
vi.mock("./utils/timeUtils", () => ({
  formatRelativeTime: () => "Recently",
  setupTimeUpdater: () => 0,
}));

const IMAGE_URL = "/api/uploads/objects/00/00000000000000000000000000000011.png";
const VIDEO_URL = "/api/uploads/objects/00/00000000000000000000000000000021.mp4";
const PDF_URL = "/api/uploads/objects/00/00000000000000000000000000000031.pdf";

const RICH_HTML = `
  <h2 style="color: #1d4ed8" onclick="window.__consumerXss=true">Rich heading</h2>
  <p><span style="color: #7e22ce; background-color: #fef3c7; font-family: Georgia, serif; font-size: 18px">Styled passage</span></p>
  <ul><li><strong>Bullet evidence</strong></li></ul>
  <ol><li><em>Ordered evidence</em></li></ol>
  <table><tbody><tr><th><p>Claim</p></th><td><p>Evidence</p></td></tr></tbody></table>
  <pre><code class="language-javascript">const safe = true;</code></pre>
  <img class="post-image" src="${IMAGE_URL}" alt="Reading diagram">
  <figure class="video-container"><video controls preload="metadata"><source src="${VIDEO_URL}" type="video/mp4"></video></figure>
  <div class="file-attachment" data-file-url="${PDF_URL}" data-file-name="Reading.pdf" data-file-size="42 KB" data-file-type="application/pdf"></div>
  <p>${"Long formatted preview content ".repeat(12)}<mark style="background-color: #ddd6fe">End marker</mark></p>
  <script><p>dangerous subtree text</p></script>
`;

const makePost = (id, title) => ({
  id,
  title,
  content: RICH_HTML,
  author: { first_name: "Ada", last_name: "Reader" },
  created_at: "2026-08-22T12:00:00Z",
  comments: 0,
  likes: 0,
  user_liked: false,
  is_saved: false,
});

const POST_VIEW_POST = makePost(9, "Full post");
const STUDENT_HUB_POST = makePost(10, "Hub post");
const CLASS_DETAILS_POST = makePost(11, "Class post");
const STUDENT_DETAILS_POST = makePost(12, "Student post");

const expectRichMatrix = (content, { compact }) => {
  expect(content).toHaveClass("rich-text-content");
  if (compact) {
    expect(content).toHaveClass("rich-text-content--compact");
  } else {
    expect(content).not.toHaveClass("rich-text-content--compact");
  }

  expect(content.querySelector("h2")).toHaveTextContent("Rich heading");
  expect(content.querySelector("h2")).toHaveStyle({ color: "#1d4ed8" });
  expect(content.querySelector("span")).toHaveStyle({
    color: "#7e22ce",
    backgroundColor: "#fef3c7",
    fontFamily: "Georgia, serif",
    fontSize: "18px",
  });
  expect(content.querySelector("ul li strong")).toHaveTextContent("Bullet evidence");
  expect(content.querySelector("ol li em")).toHaveTextContent("Ordered evidence");
  expect(content.querySelector("table th")).toHaveTextContent("Claim");
  expect(content.querySelector("table td")).toHaveTextContent("Evidence");
  expect(content.querySelector("pre code")).toHaveTextContent("const safe = true;");
  expect(content.querySelector("img")?.getAttribute("src")).toBe(IMAGE_URL);
  expect(content.querySelector("video source")?.getAttribute("src")).toBe(VIDEO_URL);
  expect(content.querySelector(".file-attachment")?.getAttribute("data-file-url")).toBe(PDF_URL);
  expect(content.querySelector("mark")).toHaveTextContent("End marker");
  expect(content.querySelector("script")).toBeNull();
  expect(content.querySelector("[onclick]")).toBeNull();
  expect(content).not.toHaveTextContent("dangerous subtree text");
};

const renderRoute = (element, initialEntry, path) => render(
  <MemoryRouter initialEntries={[initialEntry]}>
    <Routes>
      <Route path={path} element={element} />
    </Routes>
  </MemoryRouter>,
);

beforeEach(() => {
  vi.clearAllMocks();
  localStorage.clear();
  sessionStorage.clear();
  localStorage.setItem("darkMode", "false");
  sessionStorage.setItem("user_info", JSON.stringify({ role: "STUDENT", username: "ada" }));

  Object.defineProperty(window, "matchMedia", {
    configurable: true,
    value: vi.fn(() => ({ matches: false })),
  });
  window.scrollTo = vi.fn();
  window.HTMLElement.prototype.scrollIntoView = vi.fn();

  mocks.axios.get.mockImplementation(async (url) => {
    if (url === "/classes/4/posts/9") return { data: POST_VIEW_POST };
    if (url === "/classes/4/posts/9/likes") {
      return { data: { user_liked: false, like_count: 0 } };
    }
    if (url.startsWith("/classes/4/posts/9/comments?")) {
      return { data: { comments: [], total: 0, has_more: false } };
    }
    if (url === "/student/classes?status=active") return { data: [] };
    if (url === "/student/classes?status=archived") return { data: [] };
    if (url === "/student/posts") return { data: [STUDENT_HUB_POST] };
    if (url === "/classes/4/details") {
      return {
        data: {
          id: 4,
          name: "Literature",
          access_code: "READ42",
          enrollment_count: 0,
        },
      };
    }
    if (url === "/classes/4/students") return { data: [] };
    if (url === "/classes/4/posts") return { data: [CLASS_DETAILS_POST] };
    if (url === "/classes/4/assignments") return { data: [] };
    if (url === "/classes/4/analytics") return { data: {} };
    if (url === "/classes/4/students/7") {
      return {
        data: {
          id: 7,
          first_name: "Ada",
          last_name: "Reader",
          username: "ada",
          email: "ada@example.test",
          enrollment_date: "2026-08-01T12:00:00Z",
          engagement_score: 100,
          recent_activity: [{
            type: "enrollment",
            description: "Joined Literature",
            timestamp: "2026-08-01T12:00:00Z",
          }],
        },
      };
    }
    if (url === "/classes/4/students/7/posts") return { data: [STUDENT_DETAILS_POST] };
    throw new Error(`Unexpected GET ${url}`);
  });
});

describe("shared rich-text consumer integration", () => {
  it("renders the full PostView body through the shared full renderer", async () => {
    renderRoute(<PostView />, "/class/4/post/9", "/class/:classId/post/:postId");

    const content = await screen.findByLabelText("Post content");
    expectRichMatrix(content, { compact: false });
  });

  it("keeps StudentHub post previews as rich DOM inside the compact clamp", async () => {
    render(
      <MemoryRouter>
        <StudentHub />
      </MemoryRouter>,
    );
    await screen.findByText("My Classes");
    fireEvent.click(screen.getByRole("button", { name: "Post History" }));

    const content = await screen.findByLabelText("Preview of Hub post");
    expectRichMatrix(content, { compact: true });
  });

  it("keeps ClassDetails post previews as rich DOM inside the compact clamp", async () => {
    render(
      <MemoryRouter>
        <ClassDetails
          classData={{ id: 4, name: "Literature", access_code: "READ42" }}
          darkMode={false}
          initialTab="Blogs"
          onBack={() => undefined}
        />
      </MemoryRouter>,
    );

    const content = await screen.findByLabelText("Preview of Class post");
    expectRichMatrix(content, { compact: true });
  });

  it("keeps StudentDetails post previews as rich DOM inside the compact clamp", async () => {
    renderRoute(
      <StudentDetails darkMode={false} />,
      "/class/4/student/7",
      "/class/:classId/student/:studentId",
    );
    await screen.findByText("Ada Reader");
    fireEvent.click(screen.getByRole("button", { name: "Posts" }));

    const content = await screen.findByLabelText("Preview of Student post");
    expectRichMatrix(content, { compact: true });
  });
});
