import { spawnSync } from 'node:child_process';
import fs from 'node:fs';
import path from 'node:path';
import { fileURLToPath } from 'node:url';

import { expect, test as base } from '@playwright/test';

const supportDirectory = path.dirname(fileURLToPath(import.meta.url));
const VERIFICATION_TOKEN_PATTERN = /^[A-Za-z0-9_-]{32,128}$/;

const dashboardPath = {
  ADMIN: '/admin-dashboard',
  STUDENT: '/student-hub',
  TEACHER: '/teacher-dashboard',
};

const readCredentials = () => {
  const credentialsFile = process.env.E2E_CREDENTIALS_FILE;
  if (!credentialsFile || !fs.existsSync(credentialsFile)) {
    throw new Error('E2E credentials are unavailable');
  }
  return JSON.parse(fs.readFileSync(credentialsFile, 'utf8'));
};

export const test = base.extend({
  availability: [async ({}, use) => {
    const reason = process.env.E2E_LOCAL_SKIP_REASON;
    test.skip(Boolean(reason), reason || '');
    await use();
  }, { auto: true }],
  journey: async ({ browser, baseURL }, use, testInfo) => {
    const credentials = readCredentials();
    const sessions = [];
    const secrets = new Set();
    for (const user of Object.values(credentials.users)) {
      secrets.add(user.email);
      secrets.add(user.username);
      secrets.add(user.password);
    }

    const attachApi = (session) => {
      session.api = async (route, options = {}) => {
        const method = String(options.method || 'GET').toUpperCase();
        const headers = { ...(options.headers || {}) };
        if (!['GET', 'HEAD', 'OPTIONS'].includes(method)) {
          const csrfCookie = (await session.context.cookies()).find(
            ({ name }) => name === process.env.E2E_CSRF_COOKIE_NAME,
          );
          if (csrfCookie) headers['X-CSRF-Token'] = csrfCookie.value;
        }
        const apiPath = route.startsWith('/api') ? route : `/api${route}`;
        return session.context.request.fetch(new URL(apiPath, baseURL).toString(), {
          ...options,
          method,
          headers,
          failOnStatusCode: false,
        });
      };
      return session;
    };

    const openAnonymous = async () => {
      const context = await browser.newContext({ baseURL });
      const page = await context.newPage();
      const session = attachApi({ context, page, role: 'ANONYMOUS' });
      sessions.push(session);
      return session;
    };

    const openRole = async (name) => {
      const user = credentials.users[name];
      if (!user) throw new Error(`Unknown E2E role: ${name}`);
      const context = await browser.newContext({ baseURL });
      const page = await context.newPage();
      const session = attachApi({ context, page, role: user.role, user });
      sessions.push(session);

      await page.goto('/sign-in');
      await page.getByPlaceholder('Enter your email').fill(user.email);
      await page.getByPlaceholder('Enter your password').fill(user.password);
      await page.getByRole('button', { name: 'Sign In', exact: true }).click();
      await expect(page).toHaveURL(new RegExp(`${dashboardPath[user.role]}$`));
      return session;
    };

    const captureVerificationEmail = async (email) => {
      const normalizedEmail = String(email || '').trim().toLowerCase();
      secrets.add(normalizedEmail);
      const result = spawnSync(
        process.env.E2E_PYTHON,
        ['-m', 'e2e.support.capture_verification'],
        {
          cwd: path.resolve(supportDirectory, '..', '..'),
          encoding: 'utf8',
          env: process.env,
          input: JSON.stringify({
            email: normalizedEmail,
            frontend_origin: new URL(baseURL).origin,
          }),
          maxBuffer: 16 * 1024,
          shell: false,
          windowsHide: true,
        },
      );
      const stdout = String(result.stdout || '');
      const stderr = String(result.stderr || '');
      const token = stdout.endsWith('\r\n')
        ? stdout.slice(0, -2)
        : stdout.endsWith('\n')
          ? stdout.slice(0, -1)
          : '';
      if (
        result.status !== 0
        || stderr !== ''
        || !VERIFICATION_TOKEN_PATTERN.test(token)
        || stdout !== `${token}${process.platform === 'win32' ? '\r\n' : '\n'}`
      ) {
        testInfo.annotations.push({
          type: 'checkpoint',
          description: [
            `verification-helper-status-${result.status ?? 'none'}`,
            stderr === '' ? 'stderr-empty' : 'stderr-fixed',
            stdout === '' ? 'stdout-empty' : 'stdout-present',
          ].join('-'),
        });
        throw new Error('Verification email capture failed');
      }
      secrets.add(token);
      secrets.add(`#token=${token}`);
      return token;
    };

    await use({
      captureVerificationEmail,
      credentials,
      openAnonymous,
      openRole,
      redact: (...values) => values.forEach((value) => secrets.add(String(value || ''))),
    });

    if (testInfo.status !== testInfo.expectedStatus) {
      const failureRedactionsFile = process.env.E2E_FAILURE_REDACTIONS_FILE;
      if (failureRedactionsFile) {
        fs.writeFileSync(
          failureRedactionsFile,
          JSON.stringify([...secrets]),
          { mode: 0o600 },
        );
      }
      const summary = {
        title: testInfo.title,
        status: testInfo.status,
        roles: [...new Set(sessions.map(({ role }) => role))],
        error_count: testInfo.errors.length,
        checkpoints: testInfo.annotations
          .filter(({ type }) => type === 'checkpoint')
          .map(({ description }) => description),
        error_locations: testInfo.errors.map(({ location }) => (
          location
            ? {
                file: String(location.file || '').split(/[\\/]/).slice(-3).join('/'),
                line: location.line,
                column: location.column,
              }
            : null
        )),
      };
      await testInfo.attach('sanitized-failure.json', {
        body: Buffer.from(JSON.stringify(summary, null, 2)),
        contentType: 'application/json',
      });
    }

    await Promise.all(sessions.map(({ context }) => context.close()));
  },
});

export { expect };
