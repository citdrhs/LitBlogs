import { expect, test } from '../support/fixtures.js';

const apiResponse = (page, method, pathname) => page.waitForResponse((response) => (
  response.request().method() === method
  && new URL(response.url()).pathname === pathname
));

test('an administrator invites a teacher who verifies email and creates a class', async ({ journey, baseURL }, testInfo) => {
  test.setTimeout(120_000);
  const checkpoint = (description) => testInfo.annotations.push({ type: 'checkpoint', description });
  const admin = await journey.openRole('admin');
  const invitee = await journey.openAnonymous();
  const email = `invited-teacher-${journey.credentials.run_id}@example.com`;
  const password = `Invited-${journey.credentials.run_id}-Teacher-Aa9!`;
  journey.redact(email, password);

  const denied = await invitee.api('/admin/teacher-invitations', {
    method: 'POST', data: { email },
  });
  checkpoint(`anonymous-invitation-status-${denied.status()}`);
  expect(denied.status()).toBe(401);
  expect((await admin.context.request.post(new URL('/api/admin/teacher-invitations', baseURL).href, {
    data: { email },
  })).status()).toBe(403);
  checkpoint('anonymous-and-missing-csrf-denied');

  await admin.page.getByRole('button', { name: 'Invite Teacher', exact: true }).click();
  const dialog = admin.page.getByRole('dialog', { name: 'Invite Teacher', exact: true });
  await dialog.getByLabel('Teacher email', { exact: true }).fill(email);
  const invitationCreated = apiResponse(admin.page, 'POST', '/api/admin/teacher-invitations');
  await dialog.getByRole('button', { name: 'Create invitation', exact: true }).click();
  const response = await invitationCreated;
  expect(response.status()).toBe(201);
  checkpoint('admin-invitation-created');
  const invitation = await response.json();
  journey.redact(invitation.invitation_token);
  expect(invitation.email).toBe(email);
  expect(response.headers()['cache-control']).toContain('no-store');
  expect(Date.parse(invitation.expires_at)).toBeGreaterThan(Date.now());
  await expect(dialog.getByLabel('Invitation code', { exact: true }))
    .toHaveValue(invitation.invitation_token);
  await expect(dialog.getByRole('button', { name: 'Copy invitation', exact: true })).toBeVisible();
  await expect(dialog.getByRole('link', { name: 'Sign up', exact: true }))
    .toHaveAttribute('href', new URL('/sign-up', baseURL).href);
  expect(await admin.page.evaluate((token) => (
    [...Object.values(localStorage), ...Object.values(sessionStorage)]
      .some((value) => String(value).includes(token))
    || window.location.href.includes(token)
  ), invitation.invitation_token)).toBe(false);
  await dialog.getByRole('button', { name: 'Close', exact: true }).click();
  await expect(dialog).toHaveCount(0);
  checkpoint('invitation-visible-and-not-persisted');

  await invitee.page.goto('/sign-up');
  await invitee.page.getByPlaceholder('Enter your first name').fill('Invited');
  await invitee.page.getByPlaceholder('Enter your last name').fill('Teacher');
  await invitee.page.getByPlaceholder('Enter your email').fill(email);
  await invitee.page.getByPlaceholder('Enter your password').fill(password);
  await invitee.page.getByPlaceholder('Confirm your password').fill(password);
  await invitee.page.getByLabel('Role', { exact: true }).selectOption('TEACHER');
  await invitee.page.getByLabel('Teacher invitation token', { exact: true })
    .fill(invitation.invitation_token);
  const registered = apiResponse(invitee.page, 'POST', '/api/auth/register');
  await invitee.page.getByRole('button', { name: 'Sign Up', exact: true }).click();
  expect((await registered).status()).toBe(202);
  checkpoint('teacher-signup-accepted');
  await expect(invitee.page.getByRole('dialog', { name: 'Check your school email' })).toBeVisible();
  expect((await invitee.api('/auth/login', {
    method: 'POST', data: { email, password },
  })).status()).toBe(401);

  // The existing guarded helper captures delivery only in the disposable E2E
  // database. It never contacts a real SMTP provider or school recipient.
  const verificationToken = await journey.captureVerificationEmail(email);
  const verified = apiResponse(invitee.page, 'POST', '/api/auth/verify-email');
  await invitee.page.goto(`/verify-email#token=${verificationToken}`);
  expect((await verified).status()).toBe(200);
  checkpoint('teacher-email-verified');
  await expect(invitee.page.getByRole('heading', { name: 'Email verified', exact: true })).toBeVisible();
  await invitee.page.goto('/sign-in');
  await invitee.page.getByPlaceholder('Enter your email').fill(email);
  await invitee.page.getByPlaceholder('Enter your password').fill(password);
  await invitee.page.getByRole('button', { name: 'Sign In', exact: true }).click();
  await expect(invitee.page).toHaveURL(/\/teacher-dashboard$/);
  checkpoint('invited-teacher-signed-in');

  // Becoming a teacher does not grant permission to invite another teacher.
  expect((await invitee.api('/admin/teacher-invitations', {
    method: 'POST', data: { email: `another-${journey.credentials.run_id}@example.com` },
  })).status()).toBe(403);

  const className = `Invited Teacher Class ${journey.credentials.run_id}`;
  await invitee.page.getByRole('button', { name: 'Classes', exact: true }).click();
  await invitee.page.getByRole('button', { name: 'Create New Class', exact: true }).click();
  await invitee.page.getByPlaceholder('Enter class name').fill(className);
  await invitee.page.getByPlaceholder('Enter class description').fill('Invitation signup browser verification');
  const classCreated = apiResponse(invitee.page, 'POST', '/api/classes');
  await invitee.page.getByRole('button', { name: 'Create Class', exact: true }).click();
  expect((await classCreated).status()).toBe(200);
  await expect(invitee.page.getByRole('heading', { name: className, exact: true })).toBeVisible();
  checkpoint('invited-teacher-created-class');
});
