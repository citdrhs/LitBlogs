import { render, screen } from "@testing-library/react";
import { MemoryRouter } from "react-router-dom";
import { beforeEach, describe, expect, it, vi } from "vitest";

const doubles = vi.hoisted(() => ({
  clearStoredAuth: vi.fn(),
  fetchBrowserSession: vi.fn(),
  renderAdmin: vi.fn(),
  renderClassFeed: vi.fn(),
  renderLanding: vi.fn(),
  renderStudent: vi.fn(),
  renderSubmissions: vi.fn(),
  renderTeacher: vi.fn(),
}));

vi.mock("./utils/auth", () => ({
  clearStoredAuth: doubles.clearStoredAuth,
  fetchBrowserSession: doubles.fetchBrowserSession,
}));

vi.mock("./context/PrivateDraftContext", () => ({
  PrivateDraftProvider: ({ children }) => children,
}));

vi.mock("./LitBlogs", () => ({
  default: () => {
    doubles.renderLanding();
    return <p>Landing page data</p>;
  },
}));

vi.mock("./ClassFeed", () => ({
  default: () => {
    doubles.renderClassFeed();
    return <p>Class feed data</p>;
  },
}));

vi.mock("./TeacherDashboard", () => ({
  default: () => {
    doubles.renderTeacher();
    return <p>Teacher dashboard data</p>;
  },
}));

vi.mock("./StudentHub", () => ({
  default: () => {
    doubles.renderStudent();
    return <p>Student hub data</p>;
  },
}));

vi.mock("./AdminDashboard", () => ({
  default: () => {
    doubles.renderAdmin();
    return <p>Admin dashboard data</p>;
  },
}));

vi.mock("./AssignmentSubmissions", () => ({
  default: () => {
    doubles.renderSubmissions();
    return <p>Assignment submissions data</p>;
  },
}));

import App from "./App";

const session = (role) => ({
  userId: 42,
  username: `synthetic-${role.toLowerCase()}`,
  role,
  is_admin: role === "ADMIN",
});

const renderPath = (path) => render(
  <MemoryRouter initialEntries={[path]}>
    <App />
  </MemoryRouter>,
);

beforeEach(() => {
  vi.clearAllMocks();
  localStorage.clear();
  sessionStorage.clear();
});

describe("role-aware route shells", () => {
  it.each([
    ["STUDENT", "/teacher-dashboard", doubles.renderTeacher],
    ["STUDENT", "/admin-dashboard", doubles.renderAdmin],
    ["TEACHER", "/student-hub", doubles.renderStudent],
    ["TEACHER", "/admin-dashboard", doubles.renderAdmin],
    ["ADMIN", "/student-hub", doubles.renderStudent],
    ["ADMIN", "/teacher-dashboard", doubles.renderTeacher],
  ])("denies a %s session at %s without rendering its page", async (role, path, renderPage) => {
    doubles.fetchBrowserSession.mockResolvedValue(session(role));

    renderPath(path);

    expect(await screen.findByRole("alert")).toHaveTextContent(/do not have access/i);
    expect(renderPage).not.toHaveBeenCalled();
  });

  it.each([
    ["STUDENT", "/student-hub", doubles.renderStudent],
    ["STUDENT", "/class-feed/2", doubles.renderClassFeed],
    ["TEACHER", "/teacher-dashboard", doubles.renderTeacher],
    ["TEACHER", "/class/2/assignment/3/submissions", doubles.renderSubmissions],
    ["ADMIN", "/admin-dashboard", doubles.renderAdmin],
    ["ADMIN", "/class/2/assignment/3/submissions", doubles.renderSubmissions],
  ])("allows a %s session at %s", async (role, path, renderPage) => {
    doubles.fetchBrowserSession.mockResolvedValue(session(role));

    renderPath(path);

    await vi.waitFor(() => expect(renderPage).toHaveBeenCalledOnce());
    expect(screen.queryByRole("alert")).not.toBeInTheDocument();
  });

  it("redirects the legacy class-feed route before mounting a feed without a class id", async () => {
    doubles.fetchBrowserSession.mockResolvedValue(session("STUDENT"));

    renderPath("/class-feed");

    expect(await screen.findByText("Landing page data")).toBeInTheDocument();
    expect(doubles.renderClassFeed).not.toHaveBeenCalled();
  });
});
