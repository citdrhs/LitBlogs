import fs from 'node:fs';

import { expect, test as base } from '@playwright/test';

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

    await use({
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
