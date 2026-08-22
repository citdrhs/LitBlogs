import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { MemoryRouter } from "react-router-dom";
import { afterAll, beforeAll, beforeEach, describe, expect, it, vi } from "vitest";

const doubles = vi.hoisted(() => ({
  loginPopup: vi.fn(),
  post: vi.fn(),
  fetchBrowserSession: vi.fn(),
}));

vi.mock("axios", () => ({
  default: { post: doubles.post },
}));

vi.mock("@azure/msal-react", () => ({
  useMsal: () => ({ instance: { loginPopup: doubles.loginPopup } }),
}));

vi.mock("@react-oauth/google", () => ({
  GoogleLogin: ({ onSuccess }) => (
    <button
      type="button"
      onClick={() => onSuccess({ credential: "synthetic-google-id-token" })}
    >
      Synthetic Google
    </button>
  ),
}));

vi.mock("./utils/auth", () => ({
  fetchBrowserSession: doubles.fetchBrowserSession,
}));

let FAQ;
let SignUp;

beforeAll(async () => {
  vi.stubEnv("VITE_GOOGLE_CLIENT_ID", "987654321.apps.googleusercontent.com");
  vi.stubEnv("VITE_MICROSOFT_CLIENT_ID", "2f1c67a1-91e2-46a3-941f-b88e31763e51");
  vi.stubEnv("VITE_MICROSOFT_TENANT_ID", "871bd3e0-2dc0-4a40-9b07-9d03068c2364");
  ({ default: SignUp } = await import("./Sign-up.jsx"));
  ({ default: FAQ } = await import("./components/FAQ.jsx"));
});

afterAll(() => {
  vi.unstubAllEnvs();
});

beforeEach(() => {
  vi.clearAllMocks();
  window.matchMedia = vi.fn().mockReturnValue({ matches: false });
  doubles.post.mockResolvedValue({
    status: 202,
    data: {
      message: "If registration can be completed, sign in with the submitted credentials.",
    },
  });
  doubles.fetchBrowserSession.mockResolvedValue({ role: "STUDENT" });
  doubles.loginPopup.mockResolvedValue({ idToken: "synthetic-microsoft-id-token" });
});

function renderSignup() {
  render(
    <MemoryRouter>
      <SignUp />
    </MemoryRouter>,
  );
}

function fillPasswordRegistration({ role, invitationToken } = { role: "STUDENT" }) {
  fireEvent.change(screen.getByLabelText("First Name"), { target: { value: "Private" } });
  fireEvent.change(screen.getByLabelText("Last Name"), { target: { value: "Student" } });
  fireEvent.change(screen.getByLabelText("Email Address"), {
    target: { value: "private.student@example.com" },
  });
  fireEvent.change(screen.getByLabelText("Password"), {
    target: { value: "Long-Private-Password1!" },
  });
  fireEvent.change(screen.getByLabelText("Confirm Password"), {
    target: { value: "Long-Private-Password1!" },
  });
  fireEvent.change(screen.getByLabelText("Role"), { target: { value: role } });
  if (invitationToken) {
    fireEvent.change(screen.getByLabelText("Teacher invitation token"), {
      target: { value: invitationToken },
    });
  }
}

describe("password registration privacy contract", () => {
  it("keeps the browser anonymous after generic acceptance and directs the user to sign in", async () => {
    renderSignup();
    fillPasswordRegistration();

    fireEvent.click(screen.getByRole("button", { name: "Sign Up" }));

    await waitFor(() => {
      expect(doubles.post).toHaveBeenCalledWith(
        "/auth/register",
        expect.objectContaining({
          email: "private.student@example.com",
          role: "STUDENT",
        }),
      );
    });
    expect(doubles.fetchBrowserSession).not.toHaveBeenCalled();
    expect(
      await screen.findByText(/if your registration was accepted/i),
    ).toBeInTheDocument();
    expect(
      screen
        .getAllByRole("link", { name: "Sign In" })
        .some((link) => link.getAttribute("href") === "/sign-in"),
    ).toBe(true);
  });

  it("uses the one-time teacher invitation field and never the removed shared-code field", async () => {
    renderSignup();
    fillPasswordRegistration({
      role: "TEACHER",
      invitationToken: "synthetic-one-time-teacher-invitation",
    });

    fireEvent.click(screen.getByRole("button", { name: "Sign Up" }));

    await waitFor(() => {
      expect(doubles.post).toHaveBeenCalledWith(
        "/auth/register",
        expect.objectContaining({
          role: "TEACHER",
          teacher_invitation_token: "synthetic-one-time-teacher-invitation",
        }),
      );
    });
    const payload = doubles.post.mock.calls[0][1];
    expect(payload).not.toHaveProperty("access_code");
    expect(payload).not.toHaveProperty("accessCode");
    expect(doubles.fetchBrowserSession).not.toHaveBeenCalled();
    expect(screen.getByLabelText("Teacher invitation token")).toHaveValue("");
    expect(screen.getByLabelText("Password")).toHaveValue("");
    expect(screen.getByLabelText("Confirm Password")).toHaveValue("");
  });

  it("sends the one-time teacher invitation with verified-provider signup", async () => {
    renderSignup();
    fireEvent.change(screen.getByLabelText("Role"), { target: { value: "TEACHER" } });
    fireEvent.change(screen.getByLabelText("Teacher invitation token"), {
      target: { value: "synthetic-provider-teacher-invitation" },
    });

    fireEvent.click(screen.getByRole("button", { name: "Synthetic Google" }));

    await waitFor(() => {
      expect(doubles.post).toHaveBeenCalledWith("/auth/google-signup", {
        idToken: "synthetic-google-id-token",
        role: "TEACHER",
        teacherInvitationToken: "synthetic-provider-teacher-invitation",
      });
    });
    expect(screen.getByLabelText("Teacher invitation token")).toHaveValue("");
  });
});

describe("class enrollment help", () => {
  it("directs students to join a class only after signing in", () => {
    render(
      <MemoryRouter>
        <FAQ darkMode={false} />
      </MemoryRouter>,
    );

    fireEvent.click(screen.getByText("How can I join my teacher's class?"));

    expect(screen.getByText(/after signing in/i)).toBeInTheDocument();
    expect(screen.queryByText(/sign-up menu/i)).not.toBeInTheDocument();
  });
});
