import { beforeEach, expect, it, vi } from "vitest";

const doubles = vi.hoisted(() => ({
  createRoot: vi.fn(),
  initialize: vi.fn(),
  loadPublicRuntimeConfig: vi.fn(),
  pca: vi.fn(),
  render: vi.fn(),
}));

vi.mock("react-dom/client", () => ({
  default: {
    createRoot: doubles.createRoot,
  },
}));

vi.mock("@azure/msal-browser", () => ({
  LogLevel: { Error: 3 },
  PublicClientApplication: doubles.pca,
}));

vi.mock("@azure/msal-react", () => ({
  MsalProvider: ({ children }) => children,
}));

vi.mock("@react-oauth/google", () => ({
  GoogleOAuthProvider: ({ children }) => children,
}));

vi.mock("./config/runtimeConfig", () => ({
  loadPublicRuntimeConfig: doubles.loadPublicRuntimeConfig,
}));

vi.mock("./App", () => ({
  default: () => null,
}));

vi.mock("axios", () => ({
  default: {
    defaults: {},
    interceptors: {
      response: { use: vi.fn() },
    },
  },
}));

vi.mock("./utils/auth", () => ({
  clearStoredAuth: vi.fn(),
  configureAuthHttpClient: vi.fn(),
  purgeLegacyPersistentAuth: vi.fn(),
}));

beforeEach(() => {
  vi.resetModules();
  vi.clearAllMocks();
  doubles.createRoot.mockReturnValue({ render: doubles.render });
  doubles.pca.mockImplementation(function MockPublicClientApplication() {
    return { initialize: doubles.initialize };
  });
  document.body.innerHTML = '<div id="root"></div>';
});

it("never constructs Microsoft authentication when runtime disables stale valid IDs", async () => {
  doubles.loadPublicRuntimeConfig.mockResolvedValue({
    csrfCookieName: "litblogs-csrf",
    googleOauthEnabled: false,
    googleClientId: "987654321.apps.googleusercontent.com",
    microsoftOauthEnabled: false,
    microsoftClientId: "2f1c67a1-91e2-46a3-941f-b88e31763e51",
    microsoftTenantId: "871bd3e0-2dc0-4a40-9b07-9d03068c2364",
    localPasswordRegistrationEnabled: true,
  });

  await import("./main.jsx");
  await vi.waitFor(() => expect(doubles.render).toHaveBeenCalledOnce());

  expect(doubles.pca).not.toHaveBeenCalled();
  expect(doubles.initialize).not.toHaveBeenCalled();
});

it("clears a bootstrapped verification secret when app initialization fails", async () => {
  window.history.replaceState(
    { navigationId: 21 },
    "",
    "/verify-email#token=configuration-failure-secret",
  );
  const tokenApi = await import("./utils/verificationToken.js");
  tokenApi.captureEmailVerificationTokenAtBootstrap(window);
  doubles.loadPublicRuntimeConfig.mockRejectedValue(new Error("configuration unavailable"));

  await import("./main.jsx");
  await vi.waitFor(() => {
    expect(document.getElementById("root")).toHaveTextContent(
      "LitBlogs is temporarily unavailable",
    );
  });

  const submit = vi.fn();
  await expect(tokenApi.submitBootstrappedEmailVerification(submit)).rejects.toThrow(
    "Email verification is unavailable",
  );
  expect(submit).not.toHaveBeenCalled();
  expect(window.location.hash).toBe("");
});
