import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { StrictMode } from "react";
import { MemoryRouter } from "react-router-dom";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

const doubles = vi.hoisted(() => ({
  post: vi.fn(),
}));

vi.mock("axios", () => ({
  default: { post: doubles.post },
}));

vi.mock("./components/Footer", () => ({
  default: () => <footer>LitBlogs</footer>,
}));

const GENERIC_INVALID = "Invalid or expired verification link";
const GENERIC_RESEND =
  "If the account can be verified, verification instructions will be sent.";

const renderAt = async ({
  strict = true,
  url = "/verify-email#token=private-verification-token",
} = {}) => {
  vi.resetModules();
  window.history.replaceState({ navigationId: 17 }, "", url);
  const tokenApi = await import("./utils/verificationToken.js");
  tokenApi.captureEmailVerificationTokenAtBootstrap(window);
  const { default: VerifyEmail } = await import("./VerifyEmail.jsx");
  const page = (
    <MemoryRouter initialEntries={[`${window.location.pathname}${window.location.search}`]}>
      <VerifyEmail />
    </MemoryRouter>
  );
  return {
    ...render(strict ? <StrictMode>{page}</StrictMode> : page),
    tokenApi,
    VerifyEmail,
  };
};

beforeEach(() => {
  vi.clearAllMocks();
  localStorage.clear();
  sessionStorage.clear();
  document.documentElement.classList.remove("dark");
  window.matchMedia = vi.fn().mockReturnValue({ matches: false });
});

afterEach(() => {
  vi.restoreAllMocks();
  window.history.replaceState(null, "", "/");
});

describe("public email verification", () => {
  it("uses the canonical app theme so the dark card and text remain legible", async () => {
    localStorage.setItem("litblogs_settings", JSON.stringify({ darkMode: true }));
    await renderAt({ url: "/verify-email?resend=1" });

    expect(await screen.findByRole("heading", { name: "Request another verification email" }))
      .toBeInTheDocument();
    expect(document.documentElement).toHaveClass("dark");
    expect(screen.getByRole("main").parentElement).toHaveClass("bg-slate-950");
  });

  it("submits the fragment once through a StrictMode replay and guides success to sign in", async () => {
    doubles.post.mockResolvedValue({
      status: 200,
      data: { message: "Email verified successfully" },
    });
    const consoleSpies = [
      vi.spyOn(console, "log").mockImplementation(() => {}),
      vi.spyOn(console, "info").mockImplementation(() => {}),
      vi.spyOn(console, "warn").mockImplementation(() => {}),
      vi.spyOn(console, "error").mockImplementation(() => {}),
    ];

    await renderAt();

    const heading = await screen.findByRole("heading", { name: "Email verified" });
    expect(heading).toHaveFocus();
    expect(doubles.post).toHaveBeenCalledTimes(1);
    expect(doubles.post).toHaveBeenCalledWith("/auth/verify-email", {
      token: "private-verification-token",
    });
    expect(
      screen
        .getAllByRole("link", { name: "Sign In" })
        .some((link) => link.getAttribute("href") === "/sign-in"),
    ).toBe(true);
    expect(document.body).not.toHaveTextContent("private-verification-token");
    expect(window.location.href).not.toContain("private-verification-token");
    expect(JSON.stringify({ ...localStorage, ...sessionStorage })).not.toContain(
      "private-verification-token",
    );
    consoleSpies.forEach((spy) => {
      expect(JSON.stringify(spy.mock.calls)).not.toContain("private-verification-token");
    });
  });

  it("gives a captured fragment precedence over the resend-only query", async () => {
    doubles.post.mockResolvedValue({ status: 200, data: {} });

    await renderAt({
      url: "/verify-email?resend=1#token=private-verification-token",
    });

    expect(await screen.findByRole("heading", { name: "Email verified" })).toBeInTheDocument();
    expect(doubles.post).toHaveBeenCalledTimes(1);
    expect(doubles.post).toHaveBeenCalledWith("/auth/verify-email", {
      token: "private-verification-token",
    });
    expect(window.location.href).not.toContain("private-verification-token");
  });

  it("reattaches to one in-flight request when a resend URL remounts", async () => {
    let resolveRequest;
    doubles.post.mockReturnValue(new Promise((resolve) => {
      resolveRequest = resolve;
    }));
    const firstRender = await renderAt({
      strict: false,
      url: "/verify-email?resend=1#token=pending-verification-token",
    });
    await waitFor(() => expect(doubles.post).toHaveBeenCalledTimes(1));
    expect(screen.getByRole("heading", { name: "Verifying your school email" }))
      .toBeInTheDocument();
    firstRender.unmount();

    render(
      <MemoryRouter initialEntries={["/verify-email?resend=1"]}>
        <firstRender.VerifyEmail />
      </MemoryRouter>,
    );

    expect(screen.getByRole("heading", { name: "Verifying your school email" }))
      .toBeInTheDocument();
    resolveRequest({ status: 200, data: {} });
    expect(await screen.findByRole("heading", { name: "Email verified" })).toBeInTheDocument();
    expect(doubles.post).toHaveBeenCalledTimes(1);
  });

  it.each([
    ["missing", "/verify-email", null],
    ["legacy query", "/verify-email?token=query-secret", null],
    ["backend rejection", "/verify-email#token=rejected-secret", { response: { status: 400, data: { detail: "private reason" } } }],
    ["network failure", "/verify-email#token=network-secret", new Error("private host detail")],
  ])("shows one generic error for %s without exposing failure details", async (_name, url, error) => {
    if (error) {
      doubles.post.mockRejectedValue(error);
    }

    await renderAt({ url });

    expect(await screen.findByText(GENERIC_INVALID)).toBeInTheDocument();
    expect(document.body).not.toHaveTextContent(/private reason|private host detail|query-secret|rejected-secret|network-secret/i);
    expect(window.location.href).not.toMatch(/token=/i);
    if (!error) {
      expect(doubles.post).not.toHaveBeenCalled();
    }
  });

  it("does not replay a completed verification after the page remounts", async () => {
    doubles.post.mockResolvedValue({ status: 200, data: {} });
    const firstRender = await renderAt({ strict: false });
    await screen.findByRole("heading", { name: "Email verified" });
    firstRender.unmount();

    render(
      <MemoryRouter initialEntries={["/verify-email"]}>
        <firstRender.VerifyEmail />
      </MemoryRouter>,
    );

    expect(await screen.findByText(GENERIC_INVALID)).toBeInTheDocument();
    expect(doubles.post).toHaveBeenCalledTimes(1);
  });
});

describe("generic verification resend", () => {
  it("disables the resend controls while the request is pending", async () => {
    let resolveRequest;
    doubles.post.mockReturnValue(new Promise((resolve) => {
      resolveRequest = resolve;
    }));
    await renderAt({ url: "/verify-email?resend=1" });
    const input = await screen.findByLabelText("School email address");
    fireEvent.change(input, { target: { value: "student@school.example" } });
    fireEvent.click(screen.getByRole("button", { name: "Send verification email" }));

    expect(input).toBeDisabled();
    expect(screen.getByRole("button", { name: "Sending…" })).toBeDisabled();

    resolveRequest({ status: 202, data: { message: GENERIC_RESEND } });
    expect(await screen.findByText(GENERIC_RESEND)).toHaveFocus();
  });

  it("accepts an email without revealing whether an account exists", async () => {
    doubles.post.mockResolvedValue({ status: 202, data: { message: GENERIC_RESEND } });
    await renderAt({ url: "/verify-email?resend=1" });

    expect(
      await screen.findByRole("heading", { name: "Request another verification email" }),
    ).toBeInTheDocument();
    fireEvent.change(screen.getByLabelText("School email address"), {
      target: { value: "student@school.example" },
    });
    fireEvent.click(screen.getByRole("button", { name: "Send verification email" }));

    await waitFor(() => {
      expect(doubles.post).toHaveBeenCalledWith("/auth/resend-verification", {
        email: "student@school.example",
      });
    });
    expect(await screen.findByText(GENERIC_RESEND)).toHaveAttribute("role", "status");
    expect(screen.getByLabelText("School email address")).toHaveValue("");
    expect(screen.getByText(/wait at least five minutes/i)).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Request received" })).toBeDisabled();
    expect(doubles.post).toHaveBeenCalledTimes(1);
  });

  it("uses a non-enumerating error when resend cannot be submitted", async () => {
    doubles.post.mockRejectedValue(new Error("private SMTP or network detail"));
    await renderAt({ url: "/verify-email?resend=1" });
    fireEvent.change(await screen.findByLabelText("School email address"), {
      target: { value: "student@school.example" },
    });
    fireEvent.click(screen.getByRole("button", { name: "Send verification email" }));

    expect(
      await screen.findByRole("alert"),
    ).toHaveTextContent("We couldn't submit that request. Please try again.");
    expect(document.body).not.toHaveTextContent(/SMTP|network detail/i);
  });
});
