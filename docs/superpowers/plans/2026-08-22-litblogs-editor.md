# LitBlogs Rich-Text Editor Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Replace TinyMCE with a self-hosted Tiptap-based LitBlogs editor whose sanitized HTML and visuals remain identical across authoring and every published-post surface.

**Architecture:** Keep sanitized HTML as the API/database compatibility boundary, centralize rich-text document styling, and use audited open-source Tiptap extensions plus custom atomic nodes for authorized images, videos, and PDFs. Implement test-first from HTML contracts upward, then verify role-specific rendering and computed-style parity in real Chromium.

**Tech Stack:** React 18, Tiptap 3 OSS, ProseMirror, DOMPurify, Vitest/Testing Library, Playwright Chromium, FastAPI/Bleach, existing UploadAsset APIs.

---

### Task 1: Lock the dependency and no-vendor-runtime contract

**Files:**
- Modify: `litblogs/package.json`
- Modify: `litblogs/package-lock.json`
- Modify: `litblogs/src/thirdPartyPrivacy.test.js`
- Modify: `scripts/validate-repository-policy.py`
- Modify: `litblogs/tests/test_repository_policy.py`

- [ ] **Step 1: Write failing dependency-policy tests**

Add assertions that the manifest contains the reviewed open-source Tiptap packages and that source/build policy rejects `@tiptap-pro/`, Tiptap Cloud/service packages, Tiptap API keys, and new external editor origins. Keep the existing self-hosted TinyMCE privacy assertions during the migration; its removal becomes a RED gate in Task 5.

```js
expect(manifest.dependencies).toMatchObject({
  '@tiptap/react': expect.stringMatching(/^\^3\./),
  '@tiptap/pm': expect.stringMatching(/^\^3\./),
  '@tiptap/starter-kit': expect.stringMatching(/^\^3\./),
});
expect(source).not.toMatch(/@tiptap-pro|tiptap\.cloud|apiKey/);
```

- [ ] **Step 2: Run RED gates**

Run `npm run test:run -- src/thirdPartyPrivacy.test.js` from `litblogs`; expect failures because the OSS Tiptap dependencies are absent. Run the focused repository-policy test and expect its new Tiptap allow/deny assertion to fail for the same reason.

- [ ] **Step 3: Replace dependencies**

Install version `3.30.2` for `@tiptap/react`, `@tiptap/pm`, `@tiptap/starter-kit`, `@tiptap/extension-text-style`, `@tiptap/extension-color`, `@tiptap/extension-highlight`, `@tiptap/extension-font-family`, `@tiptap/extension-text-align`, `@tiptap/extension-underline`, `@tiptap/extension-link`, `@tiptap/extension-image`, `@tiptap/extension-table`, `@tiptap/extension-character-count`, and `@tiptap/extension-placeholder`. Keep TinyMCE temporarily so every intermediate commit still builds; regenerate the lockfile only through npm.

- [ ] **Step 4: Implement repository allow/deny policy**

Allow only the audited new `@tiptap/*` package names and deny Pro/cloud/service packages, external scripts, Tiptap API keys, and new third-party editor network origins. Update the secret/license scan fixtures without weakening detection elsewhere.

- [ ] **Step 5: Run GREEN gates and commit**

Run the focused frontend and repository-policy tests, `npm ls --all`, and `npm audit --omit=dev`; expect all to pass with both engines temporarily installed and no Pro/cloud package. Commit `build: add Tiptap OSS editor dependencies`.

### Task 2: Define canonical rich-text HTML and extension behavior

**Files:**
- Create: `litblogs/src/editor/richTextSchema.js`
- Create: `litblogs/src/editor/richTextSchema.test.js`
- Create: `litblogs/src/editor/FontSize.js`
- Create: `litblogs/src/editor/AttachmentNode.js`
- Create: `litblogs/src/editor/VideoNode.js`
- Modify: `litblogs/src/utils/richTextSecurity.js`
- Modify: `litblogs/src/utils/richTextSecurity.test.js`
- Modify: `litblogs/main.py`
- Modify: `litblogs/tests/test_content_security.py`

- [ ] **Step 1: Write failing HTML fixture tests**

Create table-driven fixtures for headings, blockquotes, lists, links, tables, code, foreground/background colors, font family/size, alignment, image dimensions/classes, canonical video figures, canonical PDF attachments, and TinyMCE legacy wrappers. Each fixture must assert safe visible content and backend-scanned URLs survive while `mceNonEditable`, inline handlers, editor controls, unsupported CSS, remote media, and unsafe protocols do not.

Add a cross-boundary regression proving all nine configured point labels normalize to their canonical pixel values and survive frontend sanitization, backend sanitization, storage, and rendering. Add route regressions proving allowed foreground/background colors are retained rather than removed by ClassFeed or StudentHub preview transforms.

```js
it.each(RICH_TEXT_FIXTURES)('$name round-trips canonical HTML', ({ input, expected }) => {
  const editor = createRichTextTestEditor(input);
  expect(canonicalizeEditorHtml(editor.getHTML())).toBe(expected);
  editor.destroy();
});
```

- [ ] **Step 2: Run RED schema tests**

Run `npm run test:run -- src/editor/richTextSchema.test.js src/utils/richTextSecurity.test.js`; expect module-not-found and missing-normalization failures.

- [ ] **Step 3: Implement the audited extension set**

Export `createRichTextExtensions()` with StarterKit, underline, link, text style/color/font family/font size, multicolor highlight, text alignment, table, image, character count, placeholder, and custom atomic attachment/video nodes. Configure only the headings, attributes, styles, protocols, classes, canonical pixel sizes, font families, and MIME values admitted end-to-end.

Add an exact legacy-normalization map in both sanitizer paths: `8/10/12/14/16/18/24/36/48pt` becomes `10.667/13.333/16/18.667/21.333/24/32/48/64px` before bounded CSS validation. Reject every other point value and have the font-size extension emit only the canonical pixel values while displaying point labels.

- [ ] **Step 4: Implement canonical legacy import/output**

Sanitize before parsing, parse legacy attachment/video/image markup into typed nodes, and render vendor-neutral canonical HTML containing the existing backend-scanned attributes. Ensure editor-only controls are React NodeView UI and never part of `renderHTML()`.

- [ ] **Step 5: Run GREEN schema/security tests and commit**

Run the focused tests, including a canary containing scripts, event handlers, remote URLs, and unsupported styles. Expect exact canonical output and no canary activation. Commit `feat: define canonical LitBlogs rich-text schema`.

### Task 3: Build the accessible LitBlogs editor and toolbar

**Files:**
- Create: `litblogs/src/components/LitBlogsEditor.jsx`
- Create: `litblogs/src/components/LitBlogsEditor.test.jsx`
- Create: `litblogs/src/components/LitBlogsEditorToolbar.jsx`
- Create: `litblogs/src/components/LitBlogsEditorToolbar.test.jsx`
- Create: `litblogs/src/components/LitBlogsColorPalette.jsx`
- Create: `litblogs/src/components/LitBlogsColorPalette.test.jsx`
- Create: `litblogs/src/styles/rich-text-content.css`
- Create: `litblogs/src/styles/litblogs-editor.css`

- [ ] **Step 1: Write failing toolbar and controlled-editor tests**

Cover every block/mark/alignment/list/link/table/history command, visible color/highlight swatches, selection-aware pressed/value state, keyboard operation, focus restoration, disabled state, word count, browser spellcheck, placeholder, and external-value synchronization without duplicate `onChange` calls or cursor resets.

```jsx
render(<LitBlogsEditor value="<p>Blue text</p>" onChange={onChange} />);
selectEditorText('Blue text');
await user.click(screen.getByRole('button', { name: 'Text color' }));
await user.click(screen.getByRole('button', { name: 'Blue #1d4ed8' }));
expect(screen.getByTestId('editor-canvas').querySelector('span')).toHaveStyle({ color: '#1d4ed8' });
expect(screen.getByRole('button', { name: 'Text color' })).toHaveStyle({ '--selected-color': '#1d4ed8' });
```

- [ ] **Step 2: Run RED component tests**

Run `npm run test:run -- src/components/LitBlogsEditor.test.jsx src/components/LitBlogsEditorToolbar.test.jsx src/components/LitBlogsColorPalette.test.jsx`; expect missing-component failures.

- [ ] **Step 3: Implement editor lifecycle and toolbar**

Use `useEditor` and `EditorContent`. Emit sanitized canonical HTML on document updates, track the last emitted/imported HTML, and call `commands.setContent(value, { emitUpdate: false })` only for genuine external changes. Build accessible native buttons/selects/popovers with explicit labels, pressed/expanded state, roving keyboard behavior where applicable, and visible focus.

- [ ] **Step 4: Implement shared document and editor-only CSS**

Move document typography/media rules into `.rich-text-content`. Scope toolbar, selection outlines, resize controls, placeholders, upload indicators, and remove buttons to `.litblogs-editor`. Define every foreground/background swatch as a visible CSS custom-property-backed color chip and preserve user editor-font-size settings without changing serialized HTML.

- [ ] **Step 5: Run GREEN component/accessibility tests and commit**

Run the focused tests in desktop and narrow container sizes. Assert no console errors and no iframe exists. Commit `feat: add the native LitBlogs post editor`.

### Task 4: Integrate authenticated editor uploads

**Files:**
- Create: `litblogs/src/editor/editorUploads.js`
- Create: `litblogs/src/editor/editorUploads.test.js`
- Create: `litblogs/src/components/EditorImageNodeView.jsx`
- Create: `litblogs/src/components/EditorVideoNodeView.jsx`
- Create: `litblogs/src/components/EditorAttachmentNodeView.jsx`
- Create: `litblogs/src/components/EditorMediaNodes.test.jsx`
- Modify: `litblogs/src/components/LitBlogsEditor.jsx`

- [ ] **Step 1: Write failing upload/node tests**

Cover image/video/PDF type and size validation, upload endpoints, progress, canonical URL normalization, generic failure messages, insertion only after success, atomic selection/deletion, image alt/dimensions/alignment, exact video source/type, exact attachment data attributes, base64 paste upload, remote-image rejection, and object URL cleanup.

- [ ] **Step 2: Run RED upload tests**

Run `npm run test:run -- src/editor/editorUploads.test.js src/components/EditorMediaNodes.test.jsx`; expect missing uploader/NodeView failures.

- [ ] **Step 3: Implement upload functions**

Expose one `uploadEditorAsset({ kind, file, onProgress, signal })` that maps `image`, `video`, and `pdf` to the existing endpoints, uses the existing authenticated Axios/CSRF behavior, bounds client input, accepts only current server-compatible types, and returns a normalized authorized local URL plus safe metadata.

- [ ] **Step 4: Implement atomic media NodeViews**

Render editor controls outside canonical content, use transactions for update/remove, preserve selection and undo history, and serialize the exact HTML attributes consumed by `extract_upload_references_from_html`. Never delete an uploaded object directly from the editor.

- [ ] **Step 5: Run GREEN upload/security tests and commit**

Run focused frontend tests plus backend upload-reference/binding tests. Expect canonical references to bind and foreign/remote references to remain rejected. Commit `feat: integrate secure rich-text media uploads`.

### Task 5: Replace the ClassFeed TinyMCE adapter and preserve drafts

**Files:**
- Modify: `litblogs/src/ClassFeed.jsx`
- Modify: `litblogs/src/ClassFeed.draftLifecycle.test.jsx`
- Create: `litblogs/src/ClassFeed.editorIntegration.test.jsx`
- Delete: `litblogs/src/components/SelfHostedEditor.jsx`
- Modify: `litblogs/src/LitBlogs.css`
- Modify: `litblogs/package.json`
- Modify: `litblogs/package-lock.json`
- Modify: `litblogs/src/thirdPartyPrivacy.test.js`
- Modify: `scripts/validate-repository-policy.py`
- Modify: `litblogs/tests/test_repository_policy.py`

- [ ] **Step 1: Write failing composer integration tests**

Assert the new editor loads new/edit HTML, changes mark the composer dirty, 500 ms memory-only autosave preserves canonical HTML, blank cancel does not erase a saved draft, untouched edit cancel creates no draft, discard/reset/class/user transitions remain isolated, and submit sends the canonical post request with structured media/code arrays unchanged. Add dependency/source/build-policy assertions that now require TinyMCE to be completely absent.

- [ ] **Step 2: Run RED ClassFeed tests**

Run the new integration test with the existing draft lifecycle suite; expect failures while ClassFeed still lazy-loads `SelfHostedEditor` and constructs `tinyMceConfig`.

- [ ] **Step 3: Replace the adapter**

Lazy-load `LitBlogsEditor`, pass `value`, `onChange`, font-size setting, and submit-disabled state, and remove `TINYMCE_CONFIG`, TinyMCE setup callbacks, window preview globals, and TinyMCE-only helpers. Remove `tinymce` and `@tinymce/tinymce-react` from the manifest/lockfile now that no source imports them. Preserve post title, media/code sections, save/cancel/discard behavior, API payload construction, and modal layout.

- [ ] **Step 4: Remove TinyMCE-era CSS and consolidate render classes**

Delete `.tox`, `.tinymce-content`, `mce*`, and iframe-specific rules only after equivalent shared stylesheet assertions are green. Replace render containers with the common `rich-text-content` class without changing authorization or sanitizer calls.

- [ ] **Step 5: Run GREEN composer/privacy tests and commit**

Run ClassFeed, private-draft, rich-text, post-contract, and durable-storage canary tests. Expect no private HTML in browser durable sinks and no TinyMCE source reference. Commit `refactor: replace the ClassFeed TinyMCE composer`.

### Task 6: Unify every published rich-text consumer

**Files:**
- Modify: `litblogs/src/ClassFeed.jsx`
- Modify: `litblogs/src/PostView.jsx`
- Modify: `litblogs/src/StudentHub.jsx`
- Modify: `litblogs/src/components/ClassDetails.jsx`
- Modify: `litblogs/src/components/StudentDetails.jsx`
- Create: `litblogs/src/components/RichTextContent.jsx`
- Create: `litblogs/src/components/RichTextContent.test.jsx`
- Modify: `litblogs/src/utils/richTextIntegration.test.js`
- Create: `litblogs/src/utils/richTextVisualContract.test.jsx`

- [ ] **Step 1: Write failing consumer matrix tests**

Render a single sanitized fixture through every consumer and assert equivalent semantic nodes/classes/styles for headings, foreground/background colors, fonts/sizes, alignment, lists, tables, links, code, images, video, and attachments. Add explicit regressions for the historical missing-post-format and invisible-color-swatch failures.

The ClassFeed preview and StudentHub tests must fail while their current transforms strip inline `color`; GREEN requires deleting that stripping rather than weakening the fixture.

- [ ] **Step 2: Run RED render-parity tests**

Run the integration and visual-contract suites; expect route-specific DOM/style divergence from existing runtime style injection and TinyMCE-era selectors.

- [ ] **Step 3: Apply the shared renderer contract**

Keep `sanitizeRichText(..., { mode: 'render' })` as the final boundary inside `RichTextContent`, apply the common `rich-text-content` class, and remove route-specific decoding/mutation/style behavior that changes canonical content. Preserve each route's outer card/layout and authorization semantics. Compact previews may CSS-clamp their outer container but may not flatten rich HTML to plain text or strip allowed styles.

- [ ] **Step 4: Run GREEN consumer tests and commit**

Run all frontend rich-text, role, class, post, and profile component suites. Commit `fix: unify rich-text rendering across LitBlogs views`.

### Task 7: Prove visual and role-specific parity in real Chromium

**Files:**
- Create: `litblogs/e2e/specs/editor-rendering.spec.js`
- Create: `litblogs/e2e/support/richTextFixture.js`
- Modify: `litblogs/e2e/support/fixtures.js`
- Modify: `litblogs/playwright.config.js` only if a synthetic local visual-verification project is required
- Modify: `.github/workflows/ci.yml`
- Modify: `.github/workflows/release.yml`
- Modify: `scripts/validate-repository-policy.py`
- Modify: `litblogs/tests/test_repository_policy.py`

- [ ] **Step 1: Write failing browser journeys**

Through the real UI, have a teacher create a post containing every supported format and authorized media type. Before publishing, record semantic DOM and a bounded computed-style map. After publishing, compare that contract in the author feed, enrolled-student feed, standalone post, teacher/admin class-details preview, and permitted profile/history view. Add edit/reopen, selection-state, safe paste, keyboard-only, mobile-width, and unauthorized-view assertions.

```js
const editorContract = await captureRichTextContract(page.getByTestId('editor-canvas'));
await publishPost(page);
await expectRichTextContract(page.getByTestId('class-feed-post-body'), editorContract);
```

- [ ] **Step 2: Run RED Chromium suite**

Run the focused E2E spec against the disposable PostgreSQL 17 harness; expect failures because the editor/test IDs and shared computed-style contract do not exist yet.

- [ ] **Step 3: Complete stable selectors and route fixtures**

Add semantic `data-testid` values only where accessible roles/text are insufficient. Keep all content synthetic, redact failure output, disable raw screenshots/traces/video in CI, and ensure the existing failure reporter removes cookies, CSRF values, HTML, upload URLs, and draft canaries.

- [ ] **Step 4: Run GREEN desktop/mobile journeys and inspect visuals**

Run Chromium at desktop and mobile viewports. Produce local-only synthetic screenshots for the editor and every renderer, inspect them with the image viewer, and record any mismatch as a failing DOM/computed-style regression before correcting it.

- [ ] **Step 5: Wire protected CI/release coverage and commit**

Add the focused editor journey to existing browser jobs without weakening the PostgreSQL role, migration, secret-redaction, retry, or artifact policies. Run policy/YAML tests. Commit `test: verify editor and published-post visual parity`.

### Task 8: Full verification and independent closure

**Files:**
- Modify only files required by test-first fixes to concrete review findings

- [ ] **Step 1: Run the complete frontend gates**

Run clean dependency installation, all Vitest suites, ESLint, Vite production build, `npm ls --all`, full and production npm audits, and a source/build scan proving TinyMCE/Pro/cloud/API-key/external-editor strings are absent.

- [ ] **Step 2: Run backend and policy gates**

Run the complete backend suite, Ruff, Bandit, compileall, repository policy, generic-secret scan, migration checks, and `git diff --check`. Run real PostgreSQL upload binding/sanitizer tests where available.

- [ ] **Step 3: Run full-stack browser verification**

Run all Chromium journeys against the isolated PostgreSQL 17 stack. Reinspect the local-only desktop/mobile editor and cross-role renderer screenshots, browser console, failed requests, and computed-style parity output.

- [ ] **Step 4: Request independent reviews**

Obtain separate spec-compliance, code-quality/security, and frontend visual/accessibility reviews of the frozen exact tree. Convert every Critical/Important finding into a focused failing regression, implement the minimal correction, and repeat review until approved.

- [ ] **Step 5: Commit the exact approved tree**

After fresh full gates and clean staging review, commit locally with `feat: replace TinyMCE with LitBlogs editor`. Do not push or merge without the user's explicit instruction.
