import { act, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { MemoryRouter } from "react-router-dom";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import TeacherCodeVerification from "./TeacherCodeVerification";
import { clearPendingVerification, getPendingVerification, rememberPendingVerification } from "../utils/pendingVerification";

const doubles = vi.hoisted(() => ({ post: vi.fn() }));
vi.mock("axios", () => ({ default: { post: doubles.post } }));
const onVerified = vi.fn();

const remember = (overrides = {}) => rememberPendingVerification({
  code: "email_verification_required",
  email: "student@example.com",
  verification_challenge: "private-synthetic-challenge",
  expires_at: new Date(Date.now() + 900_000).toISOString(),
  teacher_code_allowed: true,
  ...overrides,
});
const open = () => {
  render(<MemoryRouter><TeacherCodeVerification onVerified={onVerified} /></MemoryRouter>);
  fireEvent.click(screen.getByRole("button", { name: "Enter a teacher code" }));
};

beforeEach(() => {
  vi.clearAllMocks();
  clearPendingVerification();
  localStorage.clear();
  sessionStorage.clear();
});
afterEach(() => vi.useRealTimers());

describe("teacher code entry", () => {
  it("verifies with a password-authenticated challenge and clears secrets after success", async () => {
    remember();
    doubles.post.mockResolvedValue({ status: 200, data: { message: "Email verified successfully" } });
    open();
    const input = screen.getByLabelText("Six-digit teacher code");
    expect(input).toHaveFocus();
    expect(input).toHaveAttribute("inputmode", "numeric");
    fireEvent.change(input, { target: { value: "012345" } });
    fireEvent.click(screen.getByRole("button", { name: "Verify my account" }));
    await waitFor(() => expect(onVerified).toHaveBeenCalledTimes(1));
    expect(doubles.post).toHaveBeenCalledWith("/auth/verify-student-code", {
      verification_challenge: "private-synthetic-challenge", code: "012345",
    }, { signal: expect.any(AbortSignal) });
    expect(getPendingVerification()).toBeNull();
    expect(input).toHaveValue("");
    expect(window.location.href).not.toContain("private-synthetic-challenge");
    expect(JSON.stringify({ ...localStorage, ...sessionStorage })).not.toMatch(/private-synthetic-challenge|012345/);
  });

  it("uses a generic error without displaying backend details or retaining the code", async () => {
    remember();
    doubles.post.mockRejectedValue({ response: { status: 400, data: { detail: "private database exception" } } });
    open();
    fireEvent.change(screen.getByLabelText("Six-digit teacher code"), { target: { value: "123456" } });
    fireEvent.click(screen.getByRole("button", { name: "Verify my account" }));
    expect(await screen.findByRole("alert")).toHaveFocus();
    expect(screen.getByRole("alert")).toHaveTextContent("That code is incorrect or has expired");
    expect(document.body).not.toHaveTextContent("private database exception");
    expect(screen.getByLabelText("Six-digit teacher code")).toHaveValue("");
    expect(onVerified).not.toHaveBeenCalled();
  });

  it("requires a fresh password check after refresh and for nonstudent accounts", () => {
    open();
    expect(screen.getByRole("link", { name: "Sign in to enter a code" })).toHaveAttribute("href", "/sign-in");
    expect(screen.queryByRole("textbox")).not.toBeInTheDocument();
    expect(doubles.post).not.toHaveBeenCalled();
  });

  it("keeps codes unavailable to unverified teachers", () => {
    remember({ teacher_code_allowed: false, verification_challenge: null });
    open();
    expect(screen.getByText(/Teacher codes are for student accounts/)).toBeInTheDocument();
    expect(screen.queryByRole("textbox")).not.toBeInTheDocument();
  });

  it("blocks duplicate submissions and aborts a request when closed", async () => {
    remember();
    doubles.post.mockReturnValue(new Promise(() => {}));
    const view = render(<MemoryRouter><TeacherCodeVerification onVerified={onVerified} /></MemoryRouter>);
    fireEvent.click(screen.getByRole("button", { name: "Enter a teacher code" }));
    fireEvent.change(screen.getByLabelText("Six-digit teacher code"), { target: { value: "123456" } });
    const form = screen.getByRole("button", { name: "Verify my account" }).closest("form");
    fireEvent.submit(form);
    fireEvent.submit(form);
    expect(doubles.post).toHaveBeenCalledTimes(1);
    const signal = doubles.post.mock.calls[0][2].signal;
    view.unmount();
    expect(signal.aborted).toBe(true);
  });

  it("expires pending authentication even while the code form is open", () => {
    vi.useFakeTimers();
    remember();
    open();
    fireEvent.change(screen.getByLabelText("Six-digit teacher code"), { target: { value: "123456" } });
    act(() => vi.advanceTimersByTime(900_001));
    expect(screen.queryByLabelText("Six-digit teacher code")).not.toBeInTheDocument();
    expect(screen.getByRole("link", { name: "Sign in to enter a code" })).toBeInTheDocument();
    expect(screen.getByRole("link", { name: "Sign in to enter a code" })).toHaveFocus();
    expect(screen.getByRole("status")).toHaveTextContent("Your verification session has expired");
    expect(getPendingVerification()).toBeNull();
    expect(doubles.post).not.toHaveBeenCalled();
  });
});
