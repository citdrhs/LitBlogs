import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { MemoryRouter, Route, Routes } from "react-router-dom";
import { beforeEach, describe, expect, it, vi } from "vitest";
import StudentHub from "./StudentHub.jsx";

const doubles = vi.hoisted(() => ({
  get: vi.fn(), post: vi.fn(), success: vi.fn(), error: vi.fn(),
}));
vi.mock("axios", () => ({ default: { get: doubles.get, post: doubles.post } }));
vi.mock("react-hot-toast", () => ({ toast: { success: doubles.success, error: doubles.error } }));
vi.mock("./components/Navbar", () => ({ default: () => <nav aria-label="School navigation" /> }));
vi.mock("./components/Footer", () => ({ default: () => null }));
vi.mock("./components/Loader", () => ({ default: () => <p role="status">Loading classes</p> }));
vi.mock("./components/RichTextContent", () => ({ default: () => null }));
vi.mock("framer-motion", () => {
  const clean = (props) => Object.fromEntries(Object.entries(props).filter(([name]) => !["initial", "animate", "exit", "whileHover", "whileTap"].includes(name)));
  return {
    AnimatePresence: ({ children }) => children,
    motion: {
      button: (props) => <button {...clean(props)} />,
      div: (props) => <div {...clean(props)} />,
    },
  };
});

const CLASSROOM = { id: 7, name: "COW English", description: "Class publishing", teacher_name: "Ms. Rivera" };
const ARCHIVED = { id: 8, name: "Previous English", description: "Last year", teacher_name: "Ms. Rivera" };
const failure = () => ({ response: { status: 503, data: { detail: "private upstream details" } } });
const open = () => render(
  <MemoryRouter initialEntries={["/student-hub"]}>
    <Routes>
      <Route path="/student-hub" element={<StudentHub />} />
      <Route path="/class-feed/7" element={<h1>Class seven feed</h1>} />
    </Routes>
  </MemoryRouter>,
);

beforeEach(() => {
  vi.clearAllMocks();
  doubles.get.mockReset();
  doubles.post.mockReset();
  localStorage.clear();
  sessionStorage.clear();
  sessionStorage.setItem("user_info", JSON.stringify({ userId: 41, role: "STUDENT", username: "student" }));
});

describe("StudentHub class loading", () => {
  it("keeps active class navigation when only the archived list is unavailable", async () => {
    doubles.get.mockImplementation((url) => url.includes("status=active")
      ? Promise.resolve({ data: [CLASSROOM] }) : Promise.reject(failure()));
    open();
    expect(await screen.findByRole("heading", { name: "COW English" })).toBeInTheDocument();
    expect(screen.getByRole("alert")).toHaveTextContent(/could not be loaded/i);
    expect(screen.getByRole("button", { name: "Retry loading classes" })).toBeEnabled();
    expect(screen.queryByText(/not enrolled in any classes/i)).not.toBeInTheDocument();
    expect(document.body).not.toHaveTextContent("private upstream details");
    fireEvent.click(screen.getByRole("heading", { name: "COW English" }));
    expect(await screen.findByRole("heading", { name: "Class seven feed" })).toBeInTheDocument();
    expect(doubles.post).not.toHaveBeenCalled();
  });

  it("retries failed list reads without sending a join request", async () => {
    let archivedAvailable = false;
    doubles.get.mockImplementation((url) => {
      if (url.includes("status=active")) return Promise.resolve({ data: [CLASSROOM] });
      return archivedAvailable ? Promise.resolve({ data: [ARCHIVED] }) : Promise.reject(failure());
    });
    open();
    await screen.findByRole("alert");
    archivedAvailable = true;
    fireEvent.click(screen.getByRole("button", { name: "Retry loading classes" }));
    await waitFor(() => expect(screen.queryByRole("alert")).not.toBeInTheDocument());
    expect(screen.getByRole("heading", { name: "COW English" })).toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: "Previous Classes" }));
    expect(screen.getByRole("heading", { name: "Previous English" })).toBeInTheDocument();
    expect(doubles.post).not.toHaveBeenCalled();
    expect(doubles.get.mock.calls.filter(([url]) => url.includes("status=archived"))).toHaveLength(2);
  });

  it("does not claim the student has no memberships after a failed active-list read", async () => {
    doubles.get.mockImplementation((url) => url.includes("status=active")
      ? Promise.reject(failure()) : Promise.resolve({ data: [] }));
    open();
    await screen.findByRole("alert");
    expect(screen.queryByText(/not enrolled in any classes/i)).not.toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Retry loading classes" })).toBeEnabled();
  });

  it("keeps a successful join successful when the following class-list refresh fails", async () => {
    let joined = false;
    let refreshAvailable = false;
    doubles.get.mockImplementation((url) => {
      if (!url.includes("status=active")) return Promise.resolve({ data: [] });
      if (joined && !refreshAvailable) return Promise.reject(failure());
      return Promise.resolve({ data: joined ? [CLASSROOM] : [] });
    });
    doubles.post.mockImplementation(() => {
      joined = true;
      return Promise.resolve({ status: 200, data: { message: "Joined" } });
    });
    open();
    await screen.findByRole("heading", { name: "My Classes" });
    fireEvent.click(screen.getByRole("button", { name: "Join Class", exact: true }));
    fireEvent.change(screen.getByPlaceholderText("Enter class code"), { target: { value: "COW007" } });
    fireEvent.click(screen.getAllByRole("button", { name: "Join Class", exact: true }).at(-1));
    await waitFor(() => expect(doubles.success).toHaveBeenCalledWith("Successfully joined class!"));
    expect(screen.queryByRole("heading", { name: "Join a Class" })).not.toBeInTheDocument();
    expect(screen.queryByPlaceholderText("Enter class code")).not.toBeInTheDocument();
    expect(screen.getByRole("alert")).toHaveTextContent(/joined/i);
    expect(screen.getByRole("alert")).toHaveTextContent(/could not be loaded/i);
    expect(doubles.error).not.toHaveBeenCalled();
    expect(document.body).not.toHaveTextContent("check the class code");
    refreshAvailable = true;
    fireEvent.click(screen.getByRole("button", { name: "Retry loading classes" }));
    expect(await screen.findByRole("heading", { name: "COW English" })).toBeInTheDocument();
    expect(doubles.post).toHaveBeenCalledTimes(1);
    expect(doubles.post).toHaveBeenCalledWith("/student/join-class", { access_code: "COW007" });
  });
});
