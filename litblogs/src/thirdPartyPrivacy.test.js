import { readFileSync, readdirSync } from "node:fs";
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
    expect(dependencies).toMatchObject({
      "@tinymce/tinymce-react": "^6.3.0",
      tinymce: "^8.5.1",
    });
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

  it("bundles TinyMCE and every configured community plugin from npm", () => {
    const editorSource = readProjectFile("src/components/SelfHostedEditor.jsx");
    const classFeedSource = readProjectFile("src/ClassFeed.jsx");

    expect(editorSource).toContain("import 'tinymce/tinymce'");
    expect(editorSource).toContain("licenseKey=\"gpl\"");
    expect(editorSource).toContain("tinymceScriptSrc={NO_EXTERNAL_EDITOR_SCRIPTS}");

    for (const plugin of [
      "advlist",
      "anchor",
      "autolink",
      "charmap",
      "code",
      "fullscreen",
      "help",
      "image",
      "insertdatetime",
      "link",
      "lists",
      "preview",
      "quickbars",
      "searchreplace",
      "table",
      "visualblocks",
      "wordcount",
    ]) {
      expect(editorSource).toContain(`import 'tinymce/plugins/${plugin}'`);
    }

    expect(classFeedSource).toContain("lazy(() => import('./components/SelfHostedEditor'))");
    expect(classFeedSource).not.toContain("@tinymce/tinymce-react");
    expect(classFeedSource).toContain("help_tabs: ['shortcuts', 'keyboardnav']");
    expect(classFeedSource).toContain("branding: false");
    expect(classFeedSource).toContain("promotion: false");
  });

  it("does not load editor plugins with remote asset defaults", () => {
    const editorSource = readProjectFile("src/components/SelfHostedEditor.jsx");
    const classFeedSource = readProjectFile("src/ClassFeed.jsx");

    expect(editorSource).not.toContain("tinymce/plugins/emoticons");
    expect(classFeedSource).not.toMatch(/["']emoticons["']/);
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
