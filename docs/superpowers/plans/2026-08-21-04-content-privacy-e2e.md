# Content Privacy and End-to-End Verification Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Prevent stored XSS, private-file exposure/path traversal, vulnerable PDF rendering, and persistent sensitive browser data, then verify representative use cases through the real UI.

**Architecture:** Sanitize at both trust boundaries, serve files only through authorized canonical paths, and keep browser persistence non-sensitive. Playwright and in-app browser checks run against the full React/FastAPI/PostgreSQL stack with synthetic accounts.

**Tech Stack:** Bleach, DOMPurify, FastAPI streaming uploads, React, Vitest, Playwright, PostgreSQL.

---

### Task 1: Centralize rich-content sanitization

**Files:**
- Create: `litblogs/content_security.py`
- Create: `litblogs/tests/test_content_security.py`
- Create: `litblogs/src/utils/sanitizeHtml.js`
- Create: `litblogs/src/utils/sanitizeHtml.test.js`
- Modify: `litblogs/main.py`
- Modify: `litblogs/src/ClassFeed.jsx`
- Modify: `litblogs/src/PostView.jsx`
- Modify: `litblogs/src/StudentHub.jsx`
- Modify: `litblogs/src/components/ClassDetails.jsx`
- Modify: `litblogs/src/components/StudentDetails.jsx`

- [ ] Write backend/frontend failing tests for scripts, event handlers, JavaScript/data URLs, escaped-markup reactivation, style elements, external embeds, and safe formatting/media links.
- [ ] Implement one server allowlist and a DOMPurify final-render utility; delete entity-decoding-after-sanitization and `react-html-parser` paths.
- [ ] Run focused tests and confirm malicious payloads render inert while approved rich text remains.
- [ ] Commit `security: sanitize rich content at both boundaries`.

### Task 2: Make uploads private and canonical

**Files:**
- Create: `litblogs/upload_security.py`
- Modify: `litblogs/main.py`
- Modify: `litblogs/src/utils/urlUtils.js`
- Create: `litblogs/tests/test_upload_security.py`

- [ ] Write failing tests for unauthenticated reads, `../` and encoded traversal, sibling-prefix delete bypass, cross-class reads, signature/MIME/extension mismatch, SVG/HTML, oversize files, UUID names, safe response headers, and owner deletion.
- [ ] Remove the public static mount and recursive filename fallback. Resolve every path below `UPLOAD_DIR`, parse owner/class scope, enforce access, stream with limits, verify signatures, and return private/nosniff/attachment headers.
- [ ] Run focused tests on Windows paths and PostgreSQL-backed access fixtures; expect pass.
- [ ] Commit `security: authorize and validate uploaded content`.

### Task 3: Remove vulnerable PDF/Giphy/parser dependencies

**Files:**
- Modify: `litblogs/package.json`
- Modify: `litblogs/package-lock.json`
- Modify: `litblogs/src/components/PdfViewerModal.jsx`
- Modify: callers in `litblogs/src/ClassFeed.jsx` and `litblogs/src/PostView.jsx`

- [ ] Add a failing component test asserting PDF actions use the authorized download endpoint and do not mount an inline parser.
- [ ] Remove `pdfjs-dist`, `@react-pdf-viewer/*`, unused Giphy packages, and `react-html-parser`; replace PDF preview with a clear authenticated download action.
- [ ] Run `npm audit --omit=dev --audit-level=high`; expect zero high/critical findings.
- [ ] Run frontend tests/lint/build and commit `security: remove vulnerable content runtimes`.

### Task 4: Remove sensitive persistent browser state

**Files:**
- Modify: `litblogs/src/ClassFeed.jsx`
- Modify: `litblogs/src/utils/auth.js`
- Modify: `litblogs/src/utils/userSettings.js`
- Create: `litblogs/src/utils/storagePrivacy.test.js`

- [ ] Write failing tests proving JWTs, email/profile objects, assignment drafts, and post content are absent from `localStorage`, and logout clears all session draft keys.
- [ ] Keep cosmetic preferences in local storage, keep non-sensitive session UI data in session storage, and use backend draft endpoints/in-memory state for private text.
- [ ] Run frontend tests and commit `privacy: stop persisting sensitive browser data`.

### Task 5: Add full-stack browser journeys

**Files:**
- Create: `litblogs/playwright.config.js`
- Create: `litblogs/e2e/role-journeys.spec.js`
- Modify: `litblogs/package.json`
- Modify: `.github/workflows/ci.yml`

- [ ] Add a failing Playwright teacher/student journey against a disposable PostgreSQL database and test-only app process.
- [ ] Cover teacher create/view class; student join/change font/post/like/comment; teacher view student/profile/post, create assignment/review submission, archive/restore, and delete populated class.
- [ ] Add negative UI assertions for unauthorized routes and expired sessions.
- [ ] Run headless Chromium locally; expect pass without production credentials or data.
- [ ] Add an `e2e` CI job with uploaded artifacts only on failure and commit `test: verify student and teacher browser journeys`.

### Task 6: Final security and release verification

- [ ] Run fresh installs, all unit/integration/E2E tests, lint, build, Ruff, Bandit, pip-audit, npm audit, secret scan, and `git diff --check`.
- [ ] Start the test stack and use the in-app browser to manually confirm the representative teacher/student path and responsive console/network state.
- [ ] Request independent review of the complete stack, fix Critical/Important issues test-first, and repeat every verification command.
- [ ] Prepare the stacked draft PR descriptions with bases, dependencies, risks, migration/rollback notes, and exact test evidence.
