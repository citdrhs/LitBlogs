# Teacher-assisted student verification

This fallback helps a registered student finish verification when school email delivery fails. It does not change their password or grant a session. Normal email links and the explicit Resend email action remain available on the verification page.

## Classroom use

1. The teacher opens Teacher Dashboard → Students → Verify students and enters up to 25 exact school email addresses. Students do not need to be enrolled in a class yet. There is no searchable school-wide directory.
2. Only enabled, unverified, local-password student accounts from an allowed school domain appear. Confirm the student's identity in person, select them, and create codes.
3. Tell each student their own six-digit code. Creating or redeeming a teacher code sends no email. Codes are displayed only in this dialog; closing it removes the display, and a replacement invalidates the old code.
4. The student signs in using their existing email and password. Correct-password unverified logins redirect to a separate verification page. Choose Enter a teacher code, enter the code, then sign in normally after success.

Codes expire after 15 minutes and allow five incorrect attempts. The attempt budget persists across logins and application replicas. If a code expires or locks, confirm the student's identity again and create a replacement. If the page is refreshed or its short-lived verification session expires, the student must sign in again before entering a code. Teacher accounts use email or administrator assistance instead of student codes.

## Security and recovery

- Code digests use a keyed HMAC bound to the account ID and exact email; plaintext codes are never stored in the database. Password-authenticated pending challenges use a separate signing key and audience from normal sessions and are held only in browser memory.
- A code cannot verify a different student. Password/email changes invalidate pending authentication. Disabling a student or issuing teacher invalidates their codes; re-enabling them does not restore old codes. A disabled, unverified, deleted, or nonteacher issuer cannot authorize redemption.
- Issuance rechecks the teacher and their live session while holding database locks. Redemption consumes the code, activates the student, invalidates email-link capabilities, and records its audit event in one transaction. Email verification also prevents subsequent code redemption.
- If the student remains unable to sign in after verification, use existing administrator recovery after checking the exact email and account status. Do not delete student accounts or work to resolve email delivery.
- Do not include codes, challenges, passwords, or personal student details in logs, screenshots of real classes, or support tickets. Audit records identify issuance/redemption without retaining code values.

## Deployment

Apply Alembic revision `f7a9d2c4e610` through the normal reviewed update/backup procedure. It adds `student_verification_codes`, audit action values, runtime permissions, and a restricted account-disable function update. It does not rewrite existing users, classes, posts, uploads, or assignments. Database grants, email-worker head admission, and restore schema checks ship with the revision. No new environment secret is required; the existing application signing secret derives purpose-specific keys.

The migration refuses a downgrade once verification code or audit records exist. Use a reviewed recovery plan rather than erasing these records to force an older schema. Retain the encrypted pre-update backup and verify application readiness and existing email delivery after rollout.

Smoke-test with authorized demo accounts: confirm the main sign-in screen has no resend/code controls; wrong passwords remain generic; a correct-password unverified student reaches the verification page; teacher lookup excludes verified/disabled/nonstudent accounts; the code screen sends no email; a wrong code fails; a valid code works once for the selected account; and the student can then sign in normally. Confirm the normal email-link path still works, including when the database session timezone differs from UTC.
