import { spawn } from "node:child_process";
import fs from "node:fs";
import path from "node:path";
import { fileURLToPath, pathToFileURL } from "node:url";

const scriptDirectory = path.dirname(fileURLToPath(import.meta.url));
const packageDirectory = path.resolve(scriptDirectory, "..");
const repositoryDirectory = path.resolve(packageDirectory, "..", "..");
const appDirectory = path.join(repositoryDirectory, "litblogs");
const capturesDirectory = path.join(packageDirectory, "public", "captures");
const defaultPython = "C:\\Users\\antho\\Documents\\Projects\\LitBlog\\.venv\\Scripts\\python.exe";
const capturePort = Number.parseInt(process.env.CAPTURE_FRONTEND_PORT || "4274", 10);
const e2eFrontendPort = Number.parseInt(process.env.E2E_FRONTEND_PORT || "4273", 10);
const backendPort = Number.parseInt(process.env.E2E_BACKEND_PORT || "8101", 10);
const baseURL = `http://127.0.0.1:${capturePort}`;
const { chromium, expect } = await import(pathToFileURL(
  path.join(appDirectory, "node_modules", "@playwright", "test", "index.mjs"),
).href);

const SYNTHETIC = Object.freeze({
  firstName: "Jordan",
  lastName: "Reader",
  email: "student.guide@example.com",
  password: "LitBlog-Guide!2026-safe",
  className: "English 10 Reading Circle",
  classDescription: "A synthetic class for the LitBlog student tutorial.",
  postTitle: "My Reading Reflection",
  postBody: "Reading carefully helps me notice important details and connect evidence to my ideas.",
  formattedText: "important details",
});

const expectedCaptures = [
  "signup-filled.jpg",
  "registration-success.jpg",
  "signin-filled.jpg",
  "student-hub-empty.jpg",
  "join-class-code.jpg",
  "student-hub.jpg",
  "class-feed.jpg",
  "post-composer.jpg",
  "post-written.jpg",
  "post-bold.jpg",
  "post-highlight-palette.jpg",
  "post-formatted.jpg",
  "publish-action.jpg",
  "published-post.jpg",
];

const waitForUrl = async (url, child, label) => {
  const deadline = Date.now() + 60_000;
  while (Date.now() < deadline) {
    if (child?.exitCode !== null) throw new Error(`${label} exited before becoming ready`);
    try {
      const response = await fetch(url);
      if (response.ok) return;
    } catch {
      // Startup is still in progress.
    }
    await new Promise((resolve) => setTimeout(resolve, 250));
  }
  throw new Error(`${label} did not become ready at ${url}`);
};

const stopChild = async (child) => {
  if (!child || child.exitCode !== null) return;
  child.kill();
  await Promise.race([
    new Promise((resolve) => child.once("exit", resolve)),
    new Promise((resolve) => setTimeout(resolve, 5_000)),
  ]);
};

const stabilize = async (page) => {
  await page.waitForFunction(() => document.fonts?.status === "loaded");
  await page.evaluate(() => new Promise((resolve) => {
    requestAnimationFrame(() => requestAnimationFrame(resolve));
  }));
  await page.waitForTimeout(900);
};

const screenshot = async (page, filename) => {
  await stabilize(page);
  await page.screenshot({
    path: path.join(capturesDirectory, filename),
    type: "jpeg",
    quality: 90,
    fullPage: false,
    animations: "allow",
    caret: "hide",
  });
};

const configureContext = async (browser) => {
  const context = await browser.newContext({
    baseURL,
    viewport: { width: 1440, height: 900 },
    deviceScaleFactor: 1,
    colorScheme: "light",
    locale: "en-US",
  });
  await context.addInitScript(() => {
    localStorage.setItem("darkMode", "false");
    sessionStorage.clear();
  });
  await context.route("**/*", async (route) => {
    const url = new URL(route.request().url());
    if (url.pathname === "/api/runtime-config") {
      await route.fulfill({
        status: 200,
        contentType: "application/json",
        headers: { "Cache-Control": "no-store" },
        body: JSON.stringify({
          csrf_cookie_name: "litblogs_e2e_csrf",
          google_client_id: "",
          microsoft_client_id: "",
          microsoft_tenant_id: "",
          local_password_registration_enabled: true,
        }),
      });
      return;
    }
    if (["http:", "https:"].includes(url.protocol)
      && !["127.0.0.1", "localhost"].includes(url.hostname)) {
      await route.abort("blockedbyclient");
      return;
    }
    await route.continue();
  });
  return context;
};

const csrfToken = async (context) => {
  const cookie = (await context.cookies()).find(({ name }) => name === "litblogs_e2e_csrf");
  if (!cookie) throw new Error("Disposable capture session has no CSRF cookie");
  return cookie.value;
};

const apiJson = async (context, route, options = {}) => {
  const method = String(options.method || "GET").toUpperCase();
  const headers = { Accept: "application/json", ...(options.headers || {}) };
  if (!new Set(["GET", "HEAD", "OPTIONS"]).has(method)) {
    headers["X-CSRF-Token"] = await csrfToken(context);
  }
  const response = await context.request.fetch(new URL(`/api${route}`, baseURL).toString(), {
    ...options,
    method,
    headers,
    failOnStatusCode: false,
  });
  if (!response.ok()) {
    throw new Error(`${method} ${route} failed with ${response.status()}`);
  }
  return response.json();
};

const signIn = async (page, user) => {
  await page.goto("/sign-in");
  await expect(page.getByRole("heading", { name: "Sign In", exact: true })).toBeVisible();
  await page.getByLabel("Email Address").fill(user.email);
  await page.getByLabel("Password").fill(user.password);
  await page.getByRole("button", { name: "Sign In", exact: true }).click();
};

const selectTextRange = async (editor, exactText) => {
  const selected = await editor.evaluate((root, text) => {
    const walker = document.createTreeWalker(root, NodeFilter.SHOW_TEXT);
    let node = walker.nextNode();
    while (node && !node.data.includes(text)) node = walker.nextNode();
    if (!node) return "";
    const start = node.data.indexOf(text);
    const range = document.createRange();
    range.setStart(node, start);
    range.setEnd(node, start + text.length);
    const selection = window.getSelection();
    selection.removeAllRanges();
    selection.addRange(range);
    root.focus();
    document.dispatchEvent(new Event("selectionchange", { bubbles: true }));
    return selection.toString();
  }, exactText);
  if (selected !== exactText) throw new Error(`Could not select editor text: ${exactText}`);
  await editor.page().waitForTimeout(80);
};

const monitorPage = (page, label) => {
  const errors = [];
  page.on("pageerror", (error) => errors.push(`${label} page error: ${error.message}`));
  return () => {
    if (errors.length) throw new Error(errors.join("\n"));
  };
};

if (process.env.E2E_DISPOSABLE_DATABASE_CONFIRMED !== "litblogs-e2e-only") {
  throw new Error(
    "Capture refused: set E2E_DISPOSABLE_DATABASE_CONFIRMED=litblogs-e2e-only",
  );
}

const python = process.env.E2E_PYTHON || defaultPython;
if (!fs.existsSync(python)) {
  throw new Error(`Prepared E2E Python was not found: ${python}`);
}

fs.mkdirSync(capturesDirectory, { recursive: true });
for (const filename of expectedCaptures) fs.rmSync(path.join(capturesDirectory, filename), { force: true });

process.env.E2E_PYTHON = python;
process.env.E2E_FRONTEND_PORT = String(e2eFrontendPort);
process.env.E2E_BACKEND_PORT = String(backendPort);
process.env.E2E_REQUIRE_AVAILABLE = "true";

const globalSetupPath = path.join(appDirectory, "e2e", "global-setup.mjs");
const { default: startDisposableE2e } = await import(pathToFileURL(globalSetupPath).href);

let cleanupDisposable = null;
let devServer = null;
let browser = null;

try {
  cleanupDisposable = await startDisposableE2e();
  if (process.env.E2E_LOCAL_SKIP_REASON) {
    throw new Error(`Disposable E2E setup skipped: ${process.env.E2E_LOCAL_SKIP_REASON}`);
  }

  const viteCli = path.join(appDirectory, "node_modules", "vite", "bin", "vite.js");
  devServer = spawn(
    process.execPath,
    [viteCli, "--host", "127.0.0.1", "--port", String(capturePort), "--strictPort"],
    {
      cwd: appDirectory,
      env: {
        ...process.env,
        VITE_APP_BASE_PATH: "/",
        VITE_DEV_API_PROXY_TARGET: `http://127.0.0.1:${backendPort}`,
        VITE_LOCAL_PASSWORD_REGISTRATION_ENABLED: "true",
      },
      shell: false,
      stdio: "inherit",
      windowsHide: true,
    },
  );
  await waitForUrl(`${baseURL}/sign-up`, devServer, "capture Vite server");

  browser = await chromium.launch({ headless: true });
  const credentials = JSON.parse(fs.readFileSync(process.env.E2E_CREDENTIALS_FILE, "utf8"));

  const teacherContext = await configureContext(browser);
  const teacherPage = await teacherContext.newPage();
  const assertTeacherClean = monitorPage(teacherPage, "teacher");
  await signIn(teacherPage, credentials.users.teacher);
  await expect(teacherPage).toHaveURL(/\/teacher-dashboard$/);
  const classroom = await apiJson(teacherContext, "/classes", {
    method: "POST",
    data: {
      name: SYNTHETIC.className,
      description: SYNTHETIC.classDescription,
    },
  });
  if (!/^[A-Z0-9]{6}$/.test(classroom.access_code)) {
    throw new Error("Synthetic class did not return a six-character access code");
  }
  assertTeacherClean();
  await teacherContext.close();

  const studentContext = await configureContext(browser);
  const page = await studentContext.newPage();
  const assertStudentClean = monitorPage(page, "student");

  await page.goto("/sign-up");
  await expect(page).toHaveURL(/\/sign-up$/);
  await expect(page.getByRole("heading", { name: "Sign Up", exact: true })).toBeVisible();
  await page.getByLabel("First Name").fill(SYNTHETIC.firstName);
  await page.getByLabel("Last Name").fill(SYNTHETIC.lastName);
  await page.getByLabel("Email Address").fill(SYNTHETIC.email);
  await page.getByLabel("Password", { exact: true }).fill(SYNTHETIC.password);
  await page.getByLabel("Confirm Password").fill(SYNTHETIC.password);
  await page.getByRole("combobox", { name: "Role" }).selectOption("STUDENT");
  await page.evaluate(() => { document.documentElement.style.zoom = "0.82"; });
  await screenshot(page, "signup-filled.jpg");
  await page.evaluate(() => { document.documentElement.style.zoom = ""; });

  const registration = page.waitForResponse((response) => (
    response.request().method() === "POST"
    && new URL(response.url()).pathname === "/api/auth/register"
  ));
  await page.getByRole("button", { name: "Sign Up", exact: true }).click();
  if ((await registration).status() !== 202) throw new Error("Student registration was not accepted");
  const registrationHeading = page.getByRole("heading", { name: "Registration submitted" });
  await expect(registrationHeading).toBeVisible();
  await expect(page.getByText(/sign in with the credentials you submitted/i)).toBeVisible();
  await screenshot(page, "registration-success.jpg");

  await registrationHeading.locator("xpath=..").getByRole("link", {
    name: "Sign In",
    exact: true,
  }).click();
  await expect(page).toHaveURL(/\/sign-in$/);
  await expect(page.getByRole("heading", { name: "Sign In", exact: true })).toBeVisible();
  await page.getByLabel("Email Address").fill(SYNTHETIC.email);
  await page.getByLabel("Password", { exact: true }).fill(SYNTHETIC.password);
  await screenshot(page, "signin-filled.jpg");
  await page.getByRole("button", { name: "Sign In", exact: true }).click();
  await expect(page).toHaveURL(/\/student-hub$/);
  await expect(page.getByRole("heading", { name: "My Classes", exact: true })).toBeVisible();
  await screenshot(page, "student-hub-empty.jpg");

  await page.getByRole("button", { name: "Join Class", exact: true }).click();
  await expect(page.getByRole("heading", { name: "Join a Class", exact: true })).toBeVisible();
  await page.getByPlaceholder("Enter class code").fill(classroom.access_code);
  await screenshot(page, "join-class-code.jpg");
  const joined = page.waitForResponse((response) => (
    response.request().method() === "POST"
    && new URL(response.url()).pathname === "/api/student/join-class"
  ));
  await page.getByRole("button", { name: "Join Class", exact: true }).last().click();
  if ((await joined).status() !== 200) throw new Error("Student could not join the synthetic class");
  const classHeading = page.getByRole("heading", { name: SYNTHETIC.className, exact: true });
  await expect(classHeading).toBeVisible();
  await screenshot(page, "student-hub.jpg");

  await classHeading.click();
  await expect(page).toHaveURL(new RegExp(`/class-feed/${classroom.id}$`));
  await expect(page.getByRole("heading", { name: SYNTHETIC.className, exact: true })).toBeVisible();
  await expect(page.getByRole("button", { name: "Create New Post", exact: true })).toBeVisible();
  await screenshot(page, "class-feed.jpg");

  await page.getByRole("button", { name: "Create New Post", exact: true }).click();
  const composer = page.getByRole("dialog", { name: "Create post" });
  await expect(composer).toBeVisible();
  await expect(composer).toHaveAttribute("aria-modal", "true");
  const titleInput = composer.getByPlaceholder("Enter a descriptive title for your post");
  const editor = composer.getByRole("textbox", { name: "Post content" });
  const toolbar = composer.getByRole("toolbar", { name: "Rich text formatting" });
  await expect(titleInput).toBeVisible();
  await expect(editor).toBeVisible({ timeout: 60_000 });
  await expect(toolbar).toBeVisible();
  await screenshot(page, "post-composer.jpg");

  await titleInput.fill(SYNTHETIC.postTitle);
  await editor.click();
  await page.keyboard.type(SYNTHETIC.postBody);
  await page.evaluate(() => window.getSelection()?.removeAllRanges());
  await titleInput.focus();
  await expect(editor.locator("strong")).toHaveCount(0);
  await expect(editor.locator("mark")).toHaveCount(0);
  await screenshot(page, "post-written.jpg");

  await selectTextRange(editor, SYNTHETIC.formattedText);
  await toolbar.getByRole("button", { name: "Bold", exact: true }).click();
  await expect(editor.locator("strong")).toContainText(SYNTHETIC.formattedText);
  await expect(editor.locator("mark")).toHaveCount(0);
  await page.evaluate(() => window.getSelection()?.removeAllRanges());
  await titleInput.focus();
  await expect(editor.locator("strong")).toContainText(SYNTHETIC.formattedText);
  await screenshot(page, "post-bold.jpg");

  await selectTextRange(editor, SYNTHETIC.formattedText);
  await toolbar.getByRole("button", { name: /Highlight color:/ }).click();
  const highlightPalette = composer.getByRole("dialog", { name: "Highlight color palette" });
  await expect(highlightPalette).toBeVisible();
  const amberHighlight = highlightPalette.getByRole("button", { name: "Amber #fef3c7" });
  await expect(amberHighlight).toBeVisible();
  await screenshot(page, "post-highlight-palette.jpg");
  await amberHighlight.click();
  await expect(editor.locator("strong")).toContainText(SYNTHETIC.formattedText);
  await expect(editor.locator("mark")).toContainText(SYNTHETIC.formattedText);
  const markColor = await editor.locator("mark").evaluate(
    (mark) => getComputedStyle(mark).backgroundColor,
  );
  if (markColor !== "rgb(254, 243, 199)") {
    throw new Error(`Expected amber editor highlight, received ${markColor}`);
  }
  await page.evaluate(() => window.getSelection()?.removeAllRanges());
  await titleInput.focus();
  await expect(editor.locator("strong")).toContainText(SYNTHETIC.formattedText);
  await expect(editor.locator("mark")).toContainText(SYNTHETIC.formattedText);
  await screenshot(page, "post-formatted.jpg");

  const publish = composer.getByRole("button", { name: "Publish", exact: true });
  await publish.scrollIntoViewIfNeeded();
  await publish.focus();
  await screenshot(page, "publish-action.jpg");
  const published = page.waitForResponse((response) => (
    response.request().method() === "POST"
    && new URL(response.url()).pathname === `/api/classes/${classroom.id}/posts`
  ));
  await publish.click();
  const publishResponse = await published;
  if (!publishResponse.ok()) throw new Error(`Publish failed with ${publishResponse.status()}`);
  const post = await publishResponse.json();
  await expect(composer).toHaveCount(0);
  const preview = page.getByTestId(`class-feed-post-preview-${post.id}`);
  await expect(preview).toBeVisible();
  await expect(preview.locator("strong")).toContainText(SYNTHETIC.formattedText);
  await expect(preview.locator("mark")).toContainText(SYNTHETIC.formattedText);
  await preview.scrollIntoViewIfNeeded();
  await screenshot(page, "published-post.jpg");
  assertStudentClean();
  await studentContext.close();

  for (const filename of expectedCaptures) {
    const target = path.join(capturesDirectory, filename);
    const stats = fs.statSync(target);
    if (stats.size < 10_000) throw new Error(`Capture is unexpectedly small: ${filename}`);
  }
  console.log(`Captured ${expectedCaptures.length} synthetic UI states in ${capturesDirectory}`);
} finally {
  await browser?.close().catch(() => {});
  await stopChild(devServer);
  await cleanupDisposable?.();
}
