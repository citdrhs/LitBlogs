# Student and Teacher Use Cases Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Turn the requested student and teacher behaviors into an executable regression contract and repair every reproduced workflow failure.

**Architecture:** Tests call the real FastAPI routes with synthetic users and a fresh database; shared fixtures create two teachers, multiple students, and separate classes to prove both success and isolation. Route fixes reuse centralized access checks and transactional deletion helpers.

**Tech Stack:** pytest, FastAPI TestClient, SQLAlchemy, PostgreSQL, React Testing Library.

---

### Task 1: Build role journey fixtures

**Files:**
- Modify: `litblogs/tests/conftest.py`
- Create: `litblogs/tests/factories.py`
- Create: `litblogs/tests/test_student_journey.py`
- Create: `litblogs/tests/test_teacher_journey.py`

- [ ] Create factories that register/login two teachers and two students, create two classes, and return authenticated clients/CSRF headers without fixed database IDs.
- [ ] Add a failing student journey covering join, list, font setting, post, like, comment/reply, draft, submission, profile, and logout.
- [ ] Add a failing teacher journey covering create/view/list, assignment, roster/profile/posts/notes, analytics, archive/restore, and populated deletion.
- [ ] Run both files and capture each failing behavior before production changes.
- [ ] Commit only fixtures/tests as `test: codify student and teacher journeys`.

### Task 2: Repair class lifecycle and notes

**Files:**
- Modify: `litblogs/models.py`
- Modify: `litblogs/main.py`
- Create: `litblogs/alembic.ini`
- Create: `litblogs/migrations/env.py`
- Create: `litblogs/migrations/versions/20260821_01_class_notes.py`
- Create: `litblogs/tests/test_class_lifecycle.py`

- [ ] Write focused failing tests that notes persist for the owning teacher, another teacher is denied, and populated class deletion removes dependent rows without integrity errors.
- [ ] Add `ClassEnrollment.notes`, correct teacher-record comparisons, and delete class dependents in one transaction using existing dependency cleanup helpers.
- [ ] Add Alembic migrations for the notes column plus enrollment/submission uniqueness constraints, and document stamping the existing production schema before upgrade.
- [ ] Run focused tests on SQLite and PostgreSQL; expect pass.
- [ ] Commit `fix: make teacher notes and class deletion reliable`.

### Task 3: Enforce post/social journeys

**Files:**
- Modify: `litblogs/main.py`
- Modify: `litblogs/schemas.py`
- Create: `litblogs/tests/test_posts_social.py`

- [ ] Write failing positive tests for student/teacher post CRUD, like toggle, comments/replies, and pagination, plus negative tests for nonmembers, other classes, invalid parents, empty content, and oversized inputs.
- [ ] Apply class/post/comment access checks to every social route and typed bounded request schemas; ensure teachers moderate only owned classes.
- [ ] Run focused and journey tests; expect pass.
- [ ] Commit `fix: enforce class-scoped post interactions`.

### Task 4: Enforce assignment and submission privacy

**Files:**
- Modify: `litblogs/main.py`
- Modify: `litblogs/schemas.py`
- Create: `litblogs/tests/test_assignments.py`

- [ ] Write failing tests for teacher assignment CRUD, student draft round-trip/submission/late policy, teacher review/reply, own-submission reads, peer denial, and other-teacher denial.
- [ ] Restrict submission listings and replies by role/object ownership; validate assignment belongs to the route class and submission belongs to that assignment.
- [ ] Remove student email and AI-analysis fields from peer-visible responses; use separate teacher and student response schemas.
- [ ] Run focused and journey tests; expect pass.
- [ ] Commit `security: protect assignment submissions by role`.

### Task 5: Enforce profile, roster, settings, and account journeys

**Files:**
- Modify: `litblogs/main.py`
- Modify: `litblogs/schemas.py`
- Create: `litblogs/tests/test_profiles_settings.py`
- Create: `litblogs/src/Settings.test.jsx`

- [ ] Write failing tests for shared-class profile visibility, unrelated-user denial, roster field minimization for students, full owned roster for teachers, all valid font sizes, invalid font fallback/rejection, profile update bounds, and account deletion.
- [ ] Split minimal/full roster serializers and apply the privacy setting consistently. Validate settings with enums and bounded profile models.
- [ ] Make account and class deletion remove authorized file artifacts according to the documented retention policy, without following symlinks or paths outside the upload root.
- [ ] Test the React settings control saves and applies font size without exposing auth credentials.
- [ ] Run focused suites and complete journeys; expect pass.
- [ ] Commit `fix: preserve profile privacy and user settings`.

### Task 6: PostgreSQL role verification

- [ ] Create a uniquely named disposable local PostgreSQL database, assert the name has the `litblog_test_` prefix, and run the full backend suite against it.
- [ ] Drop only that verified disposable database after the run.
- [ ] Request independent review, fix Critical/Important findings test-first, and rerun both SQLite-fast and PostgreSQL suites.
