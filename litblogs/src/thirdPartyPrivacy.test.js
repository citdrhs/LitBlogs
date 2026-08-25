import { existsSync, readFileSync, readdirSync } from "node:fs";
import { extname, join } from "node:path";
import { describe, expect, it } from "vitest";

const projectRoot = globalThis.process.cwd();
const sourceRoot = join(projectRoot, "src");

const REVIEWED_TIPTAP_RUNTIME_DEPENDENCIES = {
  "@tiptap/core": "^3.30.2",
  "@tiptap/extension-character-count": "^3.30.2",
  "@tiptap/extension-color": "^3.30.2",
  "@tiptap/extension-font-family": "^3.30.2",
  "@tiptap/extension-highlight": "^3.30.2",
  "@tiptap/extension-image": "^3.30.2",
  "@tiptap/extension-link": "^3.30.2",
  "@tiptap/extension-placeholder": "^3.30.2",
  "@tiptap/extension-table": "^3.30.2",
  "@tiptap/extension-text-align": "^3.30.2",
  "@tiptap/extension-text-style": "^3.30.2",
  "@tiptap/extension-underline": "^3.30.2",
  "@tiptap/pm": "^3.30.2",
  "@tiptap/react": "^3.30.2",
  "@tiptap/starter-kit": "^3.30.2",
};

const readProjectFile = (relativePath) => (
  readFileSync(join(projectRoot, relativePath), "utf8")
);

const collectRuntimeSource = (directory) => readdirSync(directory, { withFileTypes: true })
  .flatMap((entry) => {
    const path = join(directory, entry.name);

    if (entry.isDirectory()) {
      return entry.name === "test" ? [] : collectRuntimeSource(path);
    }

    const isRuntimeSource = [
      ".cjs",
      ".css",
      ".js",
      ".jsx",
      ".mjs",
      ".ts",
      ".tsx",
    ].includes(extname(entry.name));
    const isTest = entry.name.includes(".test.");
    return isRuntimeSource && !isTest ? [readFileSync(path, "utf8")] : [];
  })
  .join("\n");

const getCsp = (html) => {
  const match = html.match(/http-equiv="Content-Security-Policy"\s+content="([^"]+)"/i);
  return match?.[1] || "";
};

describe("third-party privacy policy", () => {
  it("pins only the reviewed Tiptap OSS packages as runtime dependencies", () => {
    const { dependencies } = JSON.parse(readProjectFile("package.json"));
    const declaredTiptapDependencies = Object.fromEntries(
      Object.entries(dependencies)
        .filter(([packageName]) => packageName.startsWith("@tiptap")),
    );

    expect(declaredTiptapDependencies).toEqual(REVIEWED_TIPTAP_RUNTIME_DEPENDENCIES);
    expect(Object.keys(dependencies)).not.toContain("@tinymce/tinymce-react");
    expect(Object.keys(dependencies)).not.toContain("tinymce");
    expect(readProjectFile("package-lock.json")).not.toMatch(/tinymce/i);
  });

  it("keeps runtime source free of Tiny Cloud, Google Fonts, and Unsplash origins", () => {
    const runtimeSource = `${readProjectFile("index.html")}\n${collectRuntimeSource(sourceRoot)}`;

    for (const forbiddenOrigin of [
      "cdn.tiny.cloud",
      "sp.tinymce.com",
      "api.tiptap.dev",
      "tiptap.cloud",
      "fonts.googleapis.com",
      "fonts.gstatic.com",
      "images.unsplash.com",
      "source.unsplash.com",
    ]) {
      expect(runtimeSource).not.toContain(forbiddenOrigin);
    }

    expect(runtimeSource).not.toMatch(/\bapiKey\s*=/);
    expect(runtimeSource).not.toMatch(/@(?:hocuspocus|tiptap-(?:cloud|pro))\//i);
    expect(runtimeSource).not.toMatch(
      /\b(?:(?:(?:VITE|REACT_APP)_)?TIPTAP(?:_CLOUD)?_(?:API_KEY|SECRET|TOKEN)|tiptap(?:Cloud)?(?:ApiKey|Secret|Token))\b/i,
    );
    expect(readProjectFile("index.html")).not.toMatch(
      /<script\b[^>]*\bsrc=["'](?:https?:)?\/\//i,
    );
  });

  it("uses the local Tiptap editor without the retired TinyMCE wrapper", () => {
    const editorSource = readProjectFile("src/components/LitBlogsEditor.jsx");
    const classFeedSource = readProjectFile("src/ClassFeed.jsx");
    const runtimeSource = collectRuntimeSource(sourceRoot);

    expect(existsSync(join(sourceRoot, "components", "SelfHostedEditor.jsx"))).toBe(false);
    expect(editorSource).toMatch(/from ["']@tiptap\/react["']/);
    expect(editorSource).not.toMatch(/\bapiKey\b|tiptap\.cloud|api\.tiptap\.dev/i);
    expect(classFeedSource).toContain("<LitBlogsEditor");
    expect(classFeedSource).not.toMatch(/SelfHostedEditor|@tinymce\/tinymce-react/i);
    expect(runtimeSource).not.toMatch(/@tinymce|tinymce|\.tox-|\.mce-/i);
  });

  it("bundles the authoring editor with ClassFeed instead of loading it after a composer opens", () => {
    const appSource = readProjectFile("src/App.jsx");
    const classFeedSource = readProjectFile("src/ClassFeed.jsx");
    expect(appSource).toMatch(
      /const\s+ClassFeed\s*=\s*lazy\(\(\)\s*=>\s*import\(["']\.\/ClassFeed["']\)\);/,
    );
    expect(appSource).not.toMatch(
      /import\s+ClassFeed\s+from\s+["']\.\/ClassFeed["'];/,
    );
    expect(classFeedSource).toMatch(
      /import\s+LitBlogsEditor\s+from\s+["']\.\/components\/LitBlogsEditor["'];/,
    );
    expect(classFeedSource).not.toMatch(
      /lazy\s*\(\s*\(\)\s*=>\s*import\(["']\.\/components\/LitBlogsEditor["']\)\s*\)/,
    );
    expect(classFeedSource).not.toContain("Loading the editor&hellip;");
  });

  it("uses same-origin profile cover choices", () => {
    const profileSource = readProjectFile("src/Profile.jsx");

    for (const image of [
      "Classroom1.jpeg",
      "Classroom2.jpeg",
      "Classroom3.jpeg",
      "Classroom4.jpeg",
    ]) {
      expect(profileSource).toContain(`assetPath("${image}")`);
    }
  });

  it("narrows CSP without breaking Google or Microsoft OAuth", () => {
    const csp = getCsp(readProjectFile("index.html"));

    expect(csp).toBe(
      "default-src 'self'; base-uri 'self'; object-src 'none'; form-action 'self'; "
      + "script-src 'self' https://accounts.google.com https://apis.google.com; "
      + "style-src 'self' 'unsafe-inline' https://accounts.google.com; "
      + "style-src-elem 'self' 'unsafe-inline' https://accounts.google.com; "
      + "font-src 'self' data:; img-src 'self' data: blob: https://*.googleusercontent.com; "
      + "media-src 'self' data: blob:; connect-src 'self' https://accounts.google.com "
      + "https://login.microsoftonline.com https://graph.microsoft.com; frame-src 'self' "
      + "https://accounts.google.com https://login.microsoftonline.com; "
      + "worker-src 'self' blob:; manifest-src 'self';",
    );
    expect(csp).toContain("script-src 'self' https://accounts.google.com https://apis.google.com");
    expect(csp).toContain("connect-src 'self' https://accounts.google.com https://login.microsoftonline.com https://graph.microsoft.com");
    expect(csp).not.toContain("%VITE_CSP_CONNECT_SRC%");
    expect(csp).toContain("frame-src 'self' https://accounts.google.com https://login.microsoftonline.com");
    expect(csp).toContain("img-src 'self' data: blob: https://*.googleusercontent.com");
    expect(csp).toContain("font-src 'self' data:");
    expect(csp).not.toContain("media-src 'self' data: blob: https:");
  });
});
