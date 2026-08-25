import { Buffer } from 'node:buffer';

import { expect, test } from '../support/fixtures.js';

test.describe.configure({ mode: 'serial', retries: 0 });

const state = {};

const responseJson = async (response, status = 200) => {
  expect(response.status()).toBe(status);
  return response.json();
};

const waitForApiResponse = (page, method, pathname) => page.waitForResponse((response) => {
  const url = new URL(response.url());
  return response.request().method() === method && url.pathname === pathname;
});

const futureDateInput = () => {
  const date = new Date(Date.now() + (48 * 60 * 60 * 1000));
  return new Date(date.getTime() - (date.getTimezoneOffset() * 60_000))
    .toISOString()
    .slice(0, 16);
};

const assignmentCard = (page, title) => page
  .getByRole('heading', { name: title, exact: true })
  .locator('xpath=ancestor::div[contains(@class,"rounded-xl")][1]');

const joinClassThroughUi = async (session, className, accessCode) => {
  const { page } = session;
  await page.getByRole('button', { name: 'Join Class', exact: true }).click();
  await page.getByPlaceholder('Enter class code').fill(accessCode);
  const joined = waitForApiResponse(page, 'POST', '/api/student/join-class');
  await page.getByRole('button', { name: 'Join Class', exact: true }).last().click();
  expect((await joined).status()).toBe(200);
  await expect(page.getByRole('heading', { name: className, exact: true })).toBeVisible();
  await page.getByRole('heading', { name: className, exact: true }).click();
  await expect(page).toHaveURL(new RegExp(`/class-feed/${state.classroom.id}$`));
};

test('login uses runtime config, HttpOnly sessions, CSRF, and role guards', async ({ journey }) => {
  const anonymous = await journey.openAnonymous();
  const runtimeResponse = await anonymous.api('/runtime-config');
  const runtimeConfig = await responseJson(runtimeResponse);
  expect(runtimeResponse.headers()['cache-control']).toBe('no-store');
  expect(runtimeConfig).toMatchObject({
    csrf_cookie_name: 'litblogs_e2e_csrf',
    local_password_registration_enabled: true,
  });

  const undefinedClassRequests = [];
  anonymous.page.on('request', (request) => {
    if (request.url().includes('undefined')) undefinedClassRequests.push(request.url());
  });
  await anonymous.page.goto('/class-feed');
  await expect(anonymous.page).toHaveURL(/\/$/);
  expect(undefinedClassRequests).toEqual([]);

  const admin = await journey.openRole('admin');
  const teacher = await journey.openRole('teacher');
  const student = await journey.openRole('student');

  await expect(admin.page.getByRole('heading', { name: 'Admin Dashboard' })).toBeVisible();
  await expect(teacher.page.getByRole('button', { name: 'Classes', exact: true })).toBeVisible();
  await expect(student.page.getByRole('heading', { name: 'My Classes' })).toBeVisible();

  for (const session of [admin, teacher, student]) {
    const sessionMetadata = await responseJson(await session.api('/auth/session'));
    expect(sessionMetadata.role).toBe(session.role);

    const cookies = await session.context.cookies();
    const sessionCookie = cookies.find(({ name }) => name === 'litblogs_e2e_session');
    const csrfCookie = cookies.find(({ name }) => name === 'litblogs_e2e_csrf');
    expect(sessionCookie && {
      httpOnly: sessionCookie.httpOnly,
      secure: sessionCookie.secure,
      sameSite: sessionCookie.sameSite,
    }).toEqual({
      httpOnly: true,
      secure: false,
      sameSite: 'Strict',
    });
    expect(csrfCookie && {
      httpOnly: csrfCookie.httpOnly,
      secure: csrfCookie.secure,
      sameSite: csrfCookie.sameSite,
    }).toEqual({
      httpOnly: false,
      secure: false,
      sameSite: 'Strict',
    });
    const browserStorage = await session.page.evaluate(() => ({
      cookieNames: document.cookie
        .split(';')
        .map((part) => part.trim().split('=', 1)[0])
        .filter(Boolean),
      localToken: localStorage.getItem('token'),
      sessionToken: sessionStorage.getItem('token'),
      sessionRole: JSON.parse(sessionStorage.getItem('user_info') || '{}').role,
    }));
    expect(browserStorage.cookieNames).not.toContain('litblogs_e2e_session');
    expect(browserStorage.cookieNames).toContain('litblogs_e2e_csrf');
    expect(browserStorage.localToken).toBeNull();
    expect(browserStorage.sessionToken).toBeNull();
    expect(browserStorage.sessionRole).toBe(session.role);

    const rejectedWithoutCsrf = await session.page.evaluate(async () => {
      const response = await fetch('/api/auth/logout', {
        method: 'POST',
        credentials: 'same-origin',
      });
      return response.status;
    });
    expect(rejectedWithoutCsrf).toBe(403);
  }

  await teacher.page.goto('/student-hub');
  await expect(teacher.page.getByRole('alert')).toHaveText(/do not have access/i);
  await student.page.goto('/teacher-dashboard');
  await expect(student.page.getByRole('alert')).toHaveText(/do not have access/i);
  await admin.page.goto('/student-hub');
  await expect(admin.page.getByRole('alert')).toHaveText(/do not have access/i);

  await student.page.goto('/student-hub');
  await student.page.reload();
  await expect(student.page.getByRole('heading', { name: 'My Classes' })).toBeVisible();
});

test('teacher creates a class plus student-visible and staff-only assignments', async ({ journey }) => {
  const teacher = await journey.openRole('teacher');
  const { page } = teacher;
  const suffix = journey.credentials.run_id;
  const className = `E2E Browser Class ${suffix}`;
  const classDescription = 'Release-blocking browser journey class';
  const visibleTitle = `Visible Journey ${suffix}`;
  const privateTitle = `Staff Journey ${suffix}`;
  const dueDate = futureDateInput();

  await page.getByRole('button', { name: 'Classes', exact: true }).click();
  await expect(page.getByRole('heading', { name: 'My Classes' })).toBeVisible();
  await page.getByRole('button', { name: 'Create New Class', exact: true }).click();
  await page.getByPlaceholder('Enter class name').fill(className);
  await page.getByPlaceholder('Enter class description').fill(classDescription);
  const classCreated = waitForApiResponse(page, 'POST', '/api/classes');
  await page.getByRole('button', { name: 'Create Class', exact: true }).click();
  state.classroom = await responseJson(await classCreated);
  Object.assign(state, { className, visibleTitle, privateTitle });

  await expect(page.getByRole('heading', { name: className, exact: true })).toBeVisible();
  await page.getByRole('heading', { name: className, exact: true }).click();
  await page.getByRole('button', { name: 'Assignments', exact: true }).click();
  await expect(page.getByRole('heading', { name: 'Assignments', exact: true })).toBeVisible();

  await page.getByRole('button', { name: 'Create Assignment', exact: true }).click();
  await page.getByPlaceholder('Assignment title').fill(visibleTitle);
  await page.getByPlaceholder('Assignment description').fill('A visible submission journey');
  await page.locator('input[type="datetime-local"]').fill(dueDate);
  await expect(page.getByText('Assignment Audience', { exact: true })).toBeVisible();
  await page.getByRole('button', { name: 'Visible to Students', exact: true }).click();
  const visibleCreated = waitForApiResponse(
    page,
    'POST',
    `/api/classes/${state.classroom.id}/assignments`,
  );
  await page.getByRole('button', { name: 'Save Assignment', exact: true }).click();
  state.visibleAssignment = await responseJson(await visibleCreated);
  await expect(page.getByRole('heading', { name: visibleTitle, exact: true })).toBeVisible();

  await page.getByRole('button', { name: 'Create Assignment', exact: true }).click();
  await page.getByPlaceholder('Assignment title').fill(privateTitle);
  await page.getByPlaceholder('Assignment description').fill('Concealed from enrolled students');
  await page.locator('input[type="datetime-local"]').fill(dueDate);
  await page.getByRole('button', { name: 'Teachers/Admin Only', exact: true }).click();
  const privateCreated = waitForApiResponse(
    page,
    'POST',
    `/api/classes/${state.classroom.id}/assignments`,
  );
  await page.getByRole('button', { name: 'Save Assignment', exact: true }).click();
  state.privateAssignment = await responseJson(await privateCreated);
  await expect(page.getByRole('heading', { name: privateTitle, exact: true })).toBeVisible();
  await expect(page.getByText('Teacher/Admin Only', { exact: true })).toBeVisible();

  const teacherAssignments = await responseJson(
    await teacher.api(`/classes/${state.classroom.id}/assignments`),
  );
  expect(teacherAssignments.map(({ id }) => id)).toEqual(expect.arrayContaining([
    state.visibleAssignment.id,
    state.privateAssignment.id,
  ]));
  expect((await teacher.api(
    `/classes/${state.classroom.id}/assignments/${state.privateAssignment.id}/submissions`,
  )).status()).toBe(200);
});

test('students join, autosave and submit, while private work stays concealed', async ({ journey }) => {
  const student = await journey.openRole('student');
  await joinClassThroughUi(student, state.className, state.classroom.access_code);
  await expect(student.page.getByRole('heading', { name: state.visibleTitle })).toBeVisible();
  await expect(student.page.getByText(state.privateTitle, { exact: true })).toHaveCount(0);
  await expect(student.page.getByRole('button', { name: 'Open Submissions' })).toHaveCount(0);

  const listedAssignments = await responseJson(
    await student.api(`/classes/${state.classroom.id}/assignments`),
  );
  expect(listedAssignments.map(({ id }) => id)).toEqual([state.visibleAssignment.id]);

  const privateDraftGet = await student.api(
    `/assignments/${state.privateAssignment.id}/draft`,
  );
  expect(privateDraftGet.status()).toBe(404);
  expect((await student.api(`/assignments/${state.privateAssignment.id}/draft`, {
    method: 'PUT',
    data: { content: 'must not persist', expected_revision: 0 },
  })).status()).toBe(404);
  expect((await student.api(`/assignments/${state.privateAssignment.id}/submit`, {
    method: 'POST',
    data: { content: 'must not submit', expected_draft_revision: 0 },
  })).status()).toBe(404);
  expect((await student.api(
    `/classes/${state.classroom.id}/assignments/${state.privateAssignment.id}/submissions`,
  )).status()).toBe(404);

  const draftContent = `Browser draft ${journey.credentials.run_id}`;
  journey.redact(draftContent);
  const card = assignmentCard(student.page, state.visibleTitle);
  const draftLoaded = waitForApiResponse(
    student.page,
    'GET',
    `/api/assignments/${state.visibleAssignment.id}/draft`,
  );
  await card.getByRole('button', { name: 'Submit', exact: true }).click();
  expect((await draftLoaded).status()).toBe(200);
  const responseEditor = student.page.getByPlaceholder('Write your submission...');
  await expect(responseEditor).toBeEnabled();
  const draftSaved = waitForApiResponse(
    student.page,
    'PUT',
    `/api/assignments/${state.visibleAssignment.id}/draft`,
  );
  await responseEditor.fill(draftContent);
  const draftSaveResponse = await draftSaved;
  expect(draftSaveResponse.status()).toBe(200);
  const draftPayload = await draftSaveResponse.json();
  expect(draftPayload).toMatchObject({ has_draft: true, content: draftContent });
  const persistenceAudit = await student.page.evaluate(async (canary) => {
    const textContainsCanary = (value) => String(value || '').includes(canary);
    const storageSnapshot = (storage) => Object.fromEntries(
      Array.from({ length: storage.length }, (_unused, index) => storage.key(index))
        .filter(Boolean)
        .map((key) => [key, storage.getItem(key)]),
    );
    const localStorageContains = textContainsCanary(
      JSON.stringify(storageSnapshot(localStorage)),
    );
    const sessionStorageContains = textContainsCanary(
      JSON.stringify(storageSnapshot(sessionStorage)),
    );
    const historyContains = textContainsCanary(JSON.stringify(history.state));

    let cacheContains = false;
    let cacheEntries = 0;
    if ('caches' in window) {
      for (const cacheName of await caches.keys()) {
        const cache = await caches.open(cacheName);
        for (const request of await cache.keys()) {
          cacheEntries += 1;
          const response = await cache.match(request);
          const requestHeaders = JSON.stringify([...request.headers.entries()]);
          const responseHeaders = JSON.stringify([...(response?.headers.entries() || [])]);
          let requestBody = '';
          let responseBody = '';
          try {
            if (!['GET', 'HEAD'].includes(request.method)) {
              requestBody = await request.clone().text();
            }
          } catch {
            // An unreadable request body cannot expose data to application script.
          }
          try {
            responseBody = response ? await response.clone().text() : '';
          } catch {
            // An unreadable response body cannot expose data to application script.
          }
          cacheContains ||= [
            request.url,
            requestHeaders,
            requestBody,
            responseHeaders,
            responseBody,
          ].some(textContainsCanary);
        }
      }
    }

    const scanRecord = async (value, seen = new Set()) => {
      if (typeof value === 'string') return value.includes(canary);
      if (value === null || value === undefined) return false;
      if (value instanceof Blob) return (await value.text()).includes(canary);
      if (value instanceof ArrayBuffer) {
        return new TextDecoder().decode(value).includes(canary);
      }
      if (ArrayBuffer.isView(value)) {
        return new TextDecoder().decode(value).includes(canary);
      }
      if (typeof value !== 'object' || seen.has(value)) return false;
      seen.add(value);
      for (const key of Reflect.ownKeys(value)) {
        if (typeof key === 'string' && key.includes(canary)) return true;
        if (await scanRecord(value[key], seen)) return true;
      }
      return false;
    };

    let indexedDbContains = false;
    let indexedDbRecords = 0;
    const databaseDescriptions = typeof indexedDB.databases === 'function'
      ? await indexedDB.databases()
      : [];
    for (const description of databaseDescriptions) {
      if (!description.name) continue;
      const database = await new Promise((resolve, reject) => {
        const request = indexedDB.open(description.name);
        request.onsuccess = () => resolve(request.result);
        request.onerror = () => reject(request.error);
      });
      try {
        for (const storeName of Array.from(database.objectStoreNames)) {
          const records = await new Promise((resolve, reject) => {
            const transaction = database.transaction(storeName, 'readonly');
            const request = transaction.objectStore(storeName).getAll();
            request.onsuccess = () => resolve(request.result);
            request.onerror = () => reject(request.error);
          });
          indexedDbRecords += records.length;
          for (const record of records) {
            indexedDbContains ||= await scanRecord(record);
          }
        }
      } finally {
        database.close();
      }
    }

    return {
      localStorageContains,
      sessionStorageContains,
      historyContains,
      cacheContains,
      cacheEntries,
      indexedDbContains,
      indexedDbRecords,
      indexedDbDatabases: databaseDescriptions.length,
    };
  }, draftContent);
  expect(persistenceAudit).toMatchObject({
    localStorageContains: false,
    sessionStorageContains: false,
    historyContains: false,
    cacheContains: false,
    indexedDbContains: false,
  });

  const modal = responseEditor.locator('xpath=ancestor::div[contains(@class,"fixed inset-0")][1]');
  await modal.getByRole('button', { name: 'Cancel', exact: true }).click();
  await expect(responseEditor).toHaveCount(0);
  await assignmentCard(student.page, state.visibleTitle)
    .getByRole('button', { name: 'Resume Draft', exact: true })
    .click();
  const resumedEditor = student.page.getByPlaceholder('Write your submission...');
  await expect(resumedEditor).toHaveValue(draftContent);
  const resumedModal = resumedEditor.locator(
    'xpath=ancestor::div[contains(@class,"fixed inset-0")][1]',
  );
  const submitted = waitForApiResponse(
    student.page,
    'POST',
    `/api/assignments/${state.visibleAssignment.id}/submit`,
  );
  await resumedModal.getByRole('button', { name: 'Submit', exact: true }).click();
  state.submission = await responseJson(await submitted);
  await expect(assignmentCard(student.page, state.visibleTitle)
    .getByRole('button', { name: 'View Submission', exact: true })).toBeVisible();

  const student2 = await journey.openRole('student2');
  await joinClassThroughUi(student2, state.className, state.classroom.access_code);
  await expect(student2.page.getByRole('heading', { name: state.visibleTitle })).toBeVisible();
  await expect(student2.page.getByText(state.privateTitle, { exact: true })).toHaveCount(0);
  await expect(student2.page.getByRole('button', { name: 'Open Submissions' })).toHaveCount(0);
  const peerSubmissions = await responseJson(await student2.api(
    `/classes/${state.classroom.id}/assignments/${state.visibleAssignment.id}/submissions`,
  ));
  expect(peerSubmissions).toEqual([]);

  const teacher = await journey.openRole('teacher');
  const madePrivate = await teacher.api(
    `/classes/${state.classroom.id}/assignments/${state.visibleAssignment.id}`,
    {
      method: 'PUT',
      data: {
        title: state.visibleAssignment.title,
        description: state.visibleAssignment.description,
        due_date: state.visibleAssignment.due_date,
        allow_late: state.visibleAssignment.allow_late,
        visibility: 'private',
      },
    },
  );
  expect(madePrivate.status()).toBe(200);

  expect((await student.api(
    `/classes/${state.classroom.id}/assignments/${state.visibleAssignment.id}/submissions`,
  )).status()).toBe(404);
  expect((await student.api(
    `/classes/${state.classroom.id}/assignments/${state.visibleAssignment.id}`
      + `/submissions/${state.submission.id}/replies`,
  )).status()).toBe(404);
  const concealedAfterUpdate = await responseJson(
    await student.api(`/classes/${state.classroom.id}/assignments`),
  );
  expect(concealedAfterUpdate).toEqual([]);

  const admin = await journey.openRole('admin');
  const adminAssignments = await responseJson(
    await admin.api(`/classes/${state.classroom.id}/assignments`),
  );
  expect(adminAssignments.map(({ id }) => id)).toEqual(expect.arrayContaining([
    state.visibleAssignment.id,
    state.privateAssignment.id,
  ]));
  expect((await admin.api(
    `/classes/${state.classroom.id}/assignments/${state.visibleAssignment.id}/submissions`,
  )).status()).toBe(200);
});

test('pending uploads bind to a class post without escaping class ACLs', async ({ journey }) => {
  const owner = await journey.openRole('student');
  const classmate = await journey.openRole('student2');
  const outsider = await journey.openRole('outsider');
  const png = Buffer.from(
    'iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mP8/x8AAusB9Y9ZC6wAAAAASUVORK5CYII=',
    'base64',
  );

  const uploaded = await owner.api('/upload/image', {
    method: 'POST',
    multipart: {
      file: {
        name: 'journey.png',
        mimeType: 'image/png',
        buffer: png,
      },
    },
  });
  const uploadPayload = await responseJson(uploaded);
  expect(uploadPayload.url).toMatch(/^\/api\/uploads\//);
  expect((await owner.api(uploadPayload.url)).status()).toBe(200);
  expect((await outsider.api(uploadPayload.url)).status()).toBe(404);

  const postTitle = `Bound Upload ${journey.credentials.run_id}`;
  const boundPost = await owner.api(`/classes/${state.classroom.id}/posts`, {
    method: 'POST',
    data: {
      title: postTitle,
      content: '<p>Bound through an authenticated browser session.</p>',
      code_snippets: [],
      media: [{ type: 'image', url: uploadPayload.url, alt: 'Journey image' }],
      polls: [],
      files: [],
    },
  });
  state.post = await responseJson(boundPost);

  expect((await classmate.api(uploadPayload.url)).status()).toBe(200);
  expect((await outsider.api(uploadPayload.url)).status()).toBe(404);
  const renderedImage = classmate.page.waitForResponse((response) => (
    new URL(response.url()).pathname === uploadPayload.url
    && response.request().method() === 'GET'
  ));
  await classmate.page.goto(`/class-feed/${state.classroom.id}`);
  await expect(classmate.page.getByRole('heading', { name: postTitle, exact: true })).toBeVisible();
  await expect(classmate.page.getByRole('img', { name: 'Journey image', exact: true })).toBeVisible();
  expect((await renderedImage).status()).toBe(200);
});

test('admin disable revokes a live session and enable restores only sign-in', async ({ journey }) => {
  const student = await journey.openRole('student');
  const admin = await journey.openRole('admin');
  const studentUser = journey.credentials.users.student;

  await admin.page.getByPlaceholder('Search users').fill(studentUser.username);
  const disabledResponse = waitForApiResponse(
    admin.page,
    'PUT',
    `/api/users/${studentUser.id}/status`,
  );
  await admin.page.getByRole('button', {
    name: `Disable ${studentUser.username}`,
    exact: true,
  }).click();
  await admin.page.getByRole('button', { name: 'Confirm disable', exact: true }).click();
  expect((await disabledResponse).status()).toBe(200);
  await expect(admin.page.getByRole('button', {
    name: `Enable ${studentUser.username}`,
    exact: true,
  })).toBeVisible();

  expect((await student.api('/auth/session')).status()).toBe(401);
  await student.page.reload();
  await expect(student.page).toHaveURL(/\/sign-in$/);

  const disabledLogin = await journey.openAnonymous();
  await disabledLogin.page.goto('/sign-in');
  await disabledLogin.page.getByPlaceholder('Enter your email').fill(studentUser.email);
  await disabledLogin.page.getByPlaceholder('Enter your password').fill(studentUser.password);
  const rejectedLogin = waitForApiResponse(disabledLogin.page, 'POST', '/api/auth/login');
  await disabledLogin.page.getByRole('button', { name: 'Sign In', exact: true }).click();
  expect((await rejectedLogin).status()).toBe(401);
  await expect(disabledLogin.page).toHaveURL(/\/sign-in$/);

  const enabledResponse = waitForApiResponse(
    admin.page,
    'PUT',
    `/api/users/${studentUser.id}/status`,
  );
  await admin.page.getByRole('button', {
    name: `Enable ${studentUser.username}`,
    exact: true,
  }).click();
  await admin.page.getByRole('button', { name: 'Confirm enable', exact: true }).click();
  expect((await enabledResponse).status()).toBe(200);
  await expect(admin.page.getByRole('button', {
    name: `Disable ${studentUser.username}`,
    exact: true,
  })).toBeVisible();

  const restored = await journey.openRole('student');
  await expect(restored.page.getByRole('heading', { name: 'My Classes' })).toBeVisible();
});

test('logout revokes the cookie session and purges legacy durable private state', async ({ journey }) => {
  const student = await journey.openRole('student');
  await student.page.evaluate(() => {
    localStorage.setItem('token', 'legacy-local-token');
    localStorage.setItem('user_info', 'legacy-local-user');
    localStorage.setItem('class_info', 'legacy-local-class');
    localStorage.setItem('assignmentDraft:1:2:3', 'private assignment draft');
    localStorage.setItem('postDraft:1:2:new', 'private post draft');
    localStorage.setItem('darkMode', 'true');
    localStorage.setItem('nonSensitivePreference', 'keep');
    sessionStorage.setItem('token', 'legacy-session-token');
    sessionStorage.setItem('class_info', 'legacy-session-class');
    sessionStorage.setItem('assignmentDraft:1:2:3', 'private assignment draft');
    sessionStorage.setItem('postDraft:1:2:new', 'private post draft');
  });

  await student.page.locator('nav').getByRole('button').last().click();
  const loggedOut = waitForApiResponse(student.page, 'POST', '/api/auth/logout');
  await student.page.getByRole('button', { name: 'Sign Out', exact: true }).click();
  expect((await loggedOut).status()).toBe(204);
  await expect(student.page).toHaveURL(/\/$/);

  const storage = await student.page.evaluate(() => ({
    local: {
      token: localStorage.getItem('token'),
      user: localStorage.getItem('user_info'),
      classInfo: localStorage.getItem('class_info'),
      assignmentDraft: localStorage.getItem('assignmentDraft:1:2:3'),
      postDraft: localStorage.getItem('postDraft:1:2:new'),
      darkMode: localStorage.getItem('darkMode'),
      preference: localStorage.getItem('nonSensitivePreference'),
    },
    session: {
      token: sessionStorage.getItem('token'),
      user: sessionStorage.getItem('user_info'),
      classInfo: sessionStorage.getItem('class_info'),
      assignmentDraft: sessionStorage.getItem('assignmentDraft:1:2:3'),
      postDraft: sessionStorage.getItem('postDraft:1:2:new'),
    },
    cookieNames: document.cookie
      .split(';')
      .map((part) => part.trim().split('=', 1)[0])
      .filter(Boolean),
  }));
  expect(storage.local).toEqual({
    token: null,
    user: null,
    classInfo: null,
    assignmentDraft: null,
    postDraft: null,
    darkMode: 'true',
    preference: 'keep',
  });
  expect(storage.session).toEqual({
    token: null,
    user: null,
    classInfo: null,
    assignmentDraft: null,
    postDraft: null,
  });
  expect(storage.cookieNames).not.toContain('litblogs_e2e_session');
  expect(storage.cookieNames).not.toContain('litblogs_e2e_csrf');
  expect((await student.api('/auth/session')).status()).toBe(401);
});
