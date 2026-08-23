# LitBlogs Rich-Text Editor Design

## Objective

Replace TinyMCE with a fully self-hosted, first-party LitBlogs post editor that requires no vendor account or API key. The replacement must preserve every currently supported post-formatting and upload workflow, eliminate the iframe and TinyMCE-specific markup, and make authoring visually match every published-post surface.

This is a single-author editor. Real-time coauthoring, comments, suggestions, tracked changes, pagination, and Word document import/export are intentionally outside this release.

## Chosen approach

Use the MIT-licensed Tiptap 3 open-source packages as the browser editing engine and build the complete LitBlogs product layer around them. LitBlogs owns the toolbar, dialogs, styling, upload interactions, accessibility, HTML contract, and tests. No Tiptap Cloud, Pro, paid, AI, collaboration, or telemetry package is permitted.

Building directly on raw `contenteditable` is rejected. Selection handling, IME composition, clipboard behavior, nested lists, tables, history grouping, mobile keyboards, and accessibility are browser-engine concerns that should remain delegated to a mature open-source editing engine.

## Product experience

The existing create/edit-post modal remains the entry point. Its title field, Save/Cancel behavior, private in-memory draft lifecycle, structured media/code sections, and post request contract remain intact.

The content area becomes a native LitBlogs document canvas with no iframe. It uses a compact two-row responsive toolbar:

- Block style: paragraph, title, heading, subheading, small heading, and blockquote.
- Font family and the current 8, 10, 12, 14, 16, 18, 24, 36, and 48 point sizes.
- Text color and background highlight palettes whose swatches are always visible.
- Bold, italic, underline, strikethrough, clear formatting, undo, and redo.
- Left, center, and right alignment; bulleted and numbered lists.
- Links, tables, school-hosted images, videos, and PDF attachments.
- Word count, keyboard shortcuts, browser spellcheck, upload progress, and bounded non-sensitive error messages.

Controls reflect the current selection. Applying foreground color or highlight changes the selected text immediately. Re-selecting formatted text restores the corresponding active toolbar value and visible swatch.

The visual direction is a restrained school editorial workspace: the current modal shell is retained, while the editor uses a paper-white canvas, ink-blue active controls, clearly grouped toolbar sections, strong focus rings, and a subtle document edge. It must feel native to LitBlogs rather than like an embedded third-party product.

## HTML and persistence contract

Sanitized HTML remains the persisted post format for this release. There is no database migration and no switch to Tiptap JSON. This preserves existing posts, backend upload binding, render consumers, and API compatibility.

The canonical flow is:

`stored sanitized HTML -> frontend sanitizer -> Tiptap parser -> editor transactions -> canonical HTML serializer -> frontend sanitizer -> post request canonicalizer -> backend sanitizer -> database`

The backend sanitizer remains authoritative. Editor output is untrusted input even though the browser sanitizes it before insertion, serialization, and display.

Supported HTML is deliberately limited to the existing server/frontend allowlist:

- Blocks: `p`, `h1`-`h4`, `blockquote`, ordered/unordered lists, list items, tables, rows, headers, cells, and code/preformatted content already allowed by the shared sanitizer.
- Marks: `strong`, `em`, `u`, `s`, links, and spans carrying only supported color, background-color, font-size, font-family, text-align, font-weight, font-style, and text-decoration values.
- Images: authorized local upload URLs, alt text, width/height, supported alignment classes, and responsive dimensions.
- Video: a canonical `figure.video-container` with a `video` and `source` carrying an authorized local URL and approved MIME type.
- PDF attachment: a canonical `div.file-attachment` with the existing `data-file-url`, `data-file-name`, `data-file-size`, and `data-file-type` attributes.

Editor-only buttons, controls, selection chrome, NodeView wrappers, and upload state are never serialized. Legacy `mceNonEditable`, `mceEditable`, `.tox`, inline `onclick`, and TinyMCE editor-only control markup are accepted only during import, normalized, and omitted from canonical output.

The user-facing font menu remains labeled in points, but persisted web CSS is canonical pixels: `8/10/12/14/16/18/24/36/48pt` maps to `10.667/13.333/16/18.667/21.333/24/32/48/64px`. Frontend and backend normalization recognize only those legacy point values and convert them before CSS validation; all newly emitted HTML is pixels. This closes the current defect where TinyMCE emits point values but both sanitizers silently remove them, without creating a permanently mixed-unit store.

## Shared visual contract

One shared `rich-text-content` stylesheet defines typography, headings, paragraphs, blockquotes, lists, tables, links, inline colors/highlights, images, video, attachments, and code for both the editor canvas and every renderer.

All read-only surfaces render through one `RichTextContent` component. Full views render the complete sanitized document. Compact cards use an outer CSS line/height clamp or an explicit “Open post” affordance; they do not rewrite rich HTML into plain text, delete inline styles, or mutate the document tree.

The editor may add selection outlines, resize handles, placeholder text, upload status, and remove buttons through editor-only classes. It may not override document typography or formatted values. Published surfaces may constrain outer width, but computed styles for the same rich-text node must otherwise match the editor.

The shared stylesheet is consumed by:

- The author editor in `ClassFeed`.
- Published posts in the class feed.
- Standalone `PostView`.
- Student class/post surfaces.
- Teacher/admin class details and post previews.
- Student profile/detail post histories.

Existing scattered TinyMCE-era content rules and runtime style injection are consolidated so a color, highlight, font, size, alignment, list, table, image, attachment, or video cannot silently disappear on one route.

No preview or feed may remove an allowed inline foreground color. The current ClassFeed preview and StudentHub color-stripping transforms are deleted and replaced by the shared sanitized renderer. Contrast tests cover every fixed palette swatch on both light and dark outer themes. Shared rendering must not depend on `!important`, because style normalization intentionally removes CSS priority markers.

## Editor architecture

`LitBlogsEditor.jsx` owns the Tiptap lifecycle and exposes a small controlled interface:

```jsx
<LitBlogsEditor
  value={content}
  onChange={setContent}
  editorFontSize={userSettings.editorFontSize}
  disabled={isSubmitting}
/>
```

External value changes are imported only when they differ from the last emitted canonical HTML. That prevents cursor jumps and update loops while still supporting edit-post loads, draft restoration, discard, and route/user resets.

Tiptap extensions are assembled in one audited module. Only open-source `@tiptap/*` packages are allowed. Custom extensions provide:

- Font size serialization using supported point values.
- Local image attributes and resizing/alignment.
- Atomic video blocks.
- Atomic PDF attachment blocks.
- Canonical HTML normalization for legacy content.

Toolbar, color palettes, link dialog, table menu, upload buttons, and NodeViews are ordinary accessible React components. All buttons have explicit `type="button"`, labels, pressed/expanded state, keyboard operation, and visible focus.

## Upload behavior

Existing authenticated upload endpoints and the UploadAsset lifecycle remain unchanged:

- Image: `POST /upload`.
- Video: `POST /upload/video`.
- PDF: `POST /upload/file`.

The editor accepts only the current client-side file types and limits, shows progress, normalizes the returned URL, and inserts a node only after the upload succeeds. Remote image URLs remain rejected unless they normalize to an authorized school upload URL.

Serialized image/video/PDF nodes retain the exact semantic URLs and attributes scanned by the backend. Publishing therefore atomically binds pending UploadAsset rows exactly as it does today. Removing a node changes editor content only; the existing server reconciliation lifecycle owns unbound pending cleanup.

## Paste, drag/drop, and legacy content

Pasted HTML passes through the existing frontend sanitizer before Tiptap parses it. Script, event, remote media, unsafe protocols, arbitrary classes/IDs, unsupported CSS, and active embeds are discarded. Plain text and safe formatting remain.

Pasted or dropped data images use the authenticated image-upload path rather than serializing base64 data. External media is not fetched by the application. Oversized or unsupported content fails with a generic user-facing message and never reaches persistent browser storage or logs.

Existing posts are covered by fixture-based round trips. Importing and reserializing an unchanged legacy post must preserve its visible safe content and every backend-scanned upload reference while removing only editor-vendor artifacts.

## Privacy and error handling

Post content remains in the existing App-scoped private draft context only. It must never enter localStorage, sessionStorage, IndexedDB, CacheStorage, history state, object URLs retained past use, console output, telemetry, or failure artifacts.

Upload and parsing failures show bounded generic messages. Raw HTML, post content, file names where unnecessary, authenticated upload URLs, cookies, CSRF values, and response bodies are excluded from logs and test artifacts.

## Verification strategy

Unit and component tests establish:

- Every toolbar command and selection-aware state.
- Visible foreground and background color palettes.
- Exact HTML serialization for all supported formatting.
- Legacy HTML import and vendor-artifact removal.
- Client sanitizer behavior for paste and serialized output.
- Image/video/PDF upload success, progress, rejection, insertion, removal, and canonical attributes.
- Controlled-value synchronization without cursor reset loops.
- 500 ms in-memory draft autosave, restore, discard, navigation, and user/class isolation.
- Keyboard navigation, accessible names/states, and responsive toolbar overflow.

Real Chromium journeys use synthetic content containing every supported formatting category. A teacher authors and publishes through the editor, then the suite verifies DOM structure and computed-style parity in:

1. The author editor before publishing.
2. The author class feed after publishing.
3. An enrolled student's class feed.
4. The standalone post view.
5. The teacher/admin class-details post preview.
6. StudentHub and StudentDetails/profile post-history views where the post is visible.

The journeys also cover edit/reopen round trips, colored and highlighted selections, headings, lists, tables, links, code, image/video/PDF elements, upload authorization, removal, mobile viewport behavior, keyboard-only formatting, and safe paste.

Local visual verification captures synthetic-data screenshots of the editor and each renderer at desktop and mobile widths. Screenshots are inspected during implementation but are not uploaded as failure artifacts. Computed-style and DOM assertions remain the durable automated proof.

## Dependency and release policy

TinyMCE, `@tinymce/tinymce-react`, TinyMCE imports, TinyMCE CSP sources, GPL-mode configuration, `.tox` selectors, and TinyMCE-specific privacy tests are removed after parity is green.

The repository policy permits only the explicitly reviewed MIT Tiptap packages. It rejects `@tiptap-pro/*`, Tiptap Cloud/Collaboration service packages, external editor scripts, editor API keys, and new rich-text network origins. The release SBOM/license inventory must identify the installed packages and their MIT license.

## Acceptance criteria

- TinyMCE and its React wrapper are absent from source, lockfile, built assets, CSP, and release-policy scans.
- The editor requires no API key or third-party runtime request.
- Existing safe post HTML remains visually intact when opened and republished.
- Foreground and background color palettes visibly render their swatches, preserve selection state, serialize supported colors, and render identically after publishing.
- Every supported format renders with matching DOM semantics and computed styles in the editor, teacher feed, student feed, standalone post, class-details preview, and profile/detail consumers.
- Image, video, and PDF uploads bind through the existing secure UploadAsset contract and remain authorized on every permitted view.
- Unsafe pasted or stored HTML remains inert at editor, request, persistence, and render boundaries.
- Draft privacy and lifecycle regressions remain green.
- Frontend unit tests, real Chromium journeys, lint, production build, dependency audit, backend sanitizer/upload tests, repository policy, and secret/privacy scans pass.
- Independent spec, code-quality, security, and visual reviews report no unresolved Critical or Important findings.
