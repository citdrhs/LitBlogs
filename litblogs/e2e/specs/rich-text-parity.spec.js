import { Buffer } from 'node:buffer';
import fs from 'node:fs';
import path from 'node:path';

import { expect, test } from '../support/fixtures.js';

const FIXTURE = Object.freeze({
  heading: 'A portable rich-text lesson',
  styled: 'Blue highlighted scholarship',
  quote: 'Reading closely makes the invisible visible.',
  bullets: ['Evidence from the opening', 'Evidence from the conclusion'],
  numbered: ['Draft the claim', 'Revise with evidence'],
  link: 'Open the student hub',
  code: 'const parity = true;',
  mediaAnchor: 'Lesson materials',
  pasted: 'Safe pasted strong context',
  editedTitleSuffix: ' — reviewed',
  imageAlt: 'Parity diagram',
  pdfName: 'course-reading.pdf',
});

const IMAGE = Object.freeze({
  name: 'parity-diagram.png',
  mimeType: 'image/png',
  buffer: Buffer.from(
    'iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mP8/x8AAusB9Y9ZC6wAAAAASUVORK5CYII=',
    'base64',
  ),
});

const PDF = Object.freeze({
  name: FIXTURE.pdfName,
  mimeType: 'application/pdf',
  buffer: Buffer.from(
    '%PDF-1.4\n1 0 obj<</Type/Catalog/Pages 2 0 R>>endobj\n'
      + '2 0 obj<</Type/Pages/Count 0>>endobj\ntrailer<</Root 1 0 R>>\n%%EOF\n',
    'utf8',
  ),
});

const responseJson = async (response, status = 200) => {
  expect(response.status()).toBe(status);
  return response.json();
};

const waitForApiResponse = (page, method, pathname) => page.waitForResponse((response) => {
  const url = new URL(response.url());
  return response.request().method() === method && url.pathname === pathname;
});

const monitorPage = (page, baseURL) => {
  const observations = { consoleErrors: [], externalRequests: [], pageErrors: [] };
  const origin = new URL(baseURL).origin;
  page.on('console', (message) => {
    if (message.type() === 'error') observations.consoleErrors.push(message.text());
  });
  page.on('pageerror', (error) => observations.pageErrors.push(error.message));
  page.on('request', (request) => {
    const url = new URL(request.url());
    if (['http:', 'https:'].includes(url.protocol) && url.origin !== origin) {
      observations.externalRequests.push(url.origin);
    }
  });
  return observations;
};

const expectCleanPage = (observations) => {
  expect(observations.pageErrors).toEqual([]);
  expect(observations.consoleErrors).toEqual([]);
  expect(observations.externalRequests).toEqual([]);
};

const selectTextRange = async (editor, startText, endText = startText) => {
  const selectionText = await editor.evaluate((root, selectionFixture) => {
    const walker = document.createTreeWalker(root, NodeFilter.SHOW_TEXT);
    const nodes = [];
    while (walker.nextNode()) nodes.push(walker.currentNode);
    const startNode = nodes.find((node) => node.data.includes(selectionFixture.startText));
    const endNode = [...nodes].reverse().find(
      (node) => node.data.includes(selectionFixture.endText),
    );
    if (!startNode || !endNode) throw new Error('Synthetic editor text was not found');
    const range = document.createRange();
    range.setStart(startNode, startNode.data.indexOf(selectionFixture.startText));
    range.setEnd(
      endNode,
      endNode.data.indexOf(selectionFixture.endText) + selectionFixture.endText.length,
    );
    root.focus();
    const selection = window.getSelection();
    selection.removeAllRanges();
    selection.addRange(range);
    document.dispatchEvent(new Event('selectionchange', { bubbles: true }));
    return selection.toString();
  }, { startText, endText });
  expect(selectionText).toContain(startText);
  expect(selectionText).toContain(endText);
  await editor.page().waitForTimeout(50);
};

const placeCaretAfterText = async (editor, text) => {
  const placed = await editor.evaluate((root, exactText) => {
    const walker = document.createTreeWalker(root, NodeFilter.SHOW_TEXT);
    let node = walker.nextNode();
    while (node && !node.data.includes(exactText)) node = walker.nextNode();
    if (!node) return false;
    const range = document.createRange();
    range.setStart(node, node.data.indexOf(exactText) + exactText.length);
    range.collapse(true);
    root.focus();
    const selection = window.getSelection();
    selection.removeAllRanges();
    selection.addRange(range);
    document.dispatchEvent(new Event('selectionchange', { bubbles: true }));
    return selection.isCollapsed && selection.anchorNode === node;
  }, text);
  expect(placed).toBe(true);
  await editor.page().waitForTimeout(50);
};

const generateWebm = async (page) => {
  const bytes = await page.evaluate(async () => {
    const canvas = document.createElement('canvas');
    canvas.width = 160;
    canvas.height = 90;
    const context = canvas.getContext('2d');
    const stream = canvas.captureStream(12);
    const preferredType = MediaRecorder.isTypeSupported('video/webm;codecs=vp8')
      ? 'video/webm;codecs=vp8'
      : 'video/webm';
    const recorder = new MediaRecorder(stream, { mimeType: preferredType });
    const chunks = [];
    recorder.addEventListener('dataavailable', (event) => {
      if (event.data.size) chunks.push(event.data);
    });
    const stopped = new Promise((resolve) => recorder.addEventListener('stop', resolve));
    recorder.start(40);
    for (let frame = 0; frame < 8; frame += 1) {
      context.fillStyle = frame % 2 ? '#1d4ed8' : '#fef3c7';
      context.fillRect(0, 0, canvas.width, canvas.height);
      context.fillStyle = '#111827';
      context.font = '18px sans-serif';
      context.fillText('LitBlogs parity', 12, 50);
      await new Promise((resolve) => setTimeout(resolve, 45));
    }
    recorder.stop();
    await stopped;
    stream.getTracks().forEach((track) => track.stop());
    const blob = new Blob(chunks, { type: 'video/webm' });
    return Array.from(new Uint8Array(await blob.arrayBuffer()));
  });
  expect(bytes.slice(0, 4)).toEqual([0x1a, 0x45, 0xdf, 0xa3]);
  return {
    name: 'parity-video.webm',
    mimeType: 'video/webm',
    buffer: Buffer.from(bytes),
  };
};

const takeLocalVisual = async (page, name) => {
  const directory = process.env.E2E_LOCAL_VISUAL_DIR;
  if (!directory || process.env.CI) return;
  const resolved = path.resolve(directory);
  fs.mkdirSync(resolved, { recursive: true, mode: 0o700 });
  await page.screenshot({
    animations: 'disabled',
    caret: 'hide',
    fullPage: false,
    path: path.join(resolved, `${name}.png`),
  });
};

const headingProbe = (page, html, heading) => page.evaluate((fixture) => {
  const template = document.createElement('template');
  template.innerHTML = fixture.html;
  return {
    hasHeadingElement: [...template.content.querySelectorAll('h2')].some(
      (element) => element.textContent.trim() === fixture.heading,
    ),
    hasHeadingText: template.content.textContent.includes(fixture.heading),
  };
}, { heading, html });

const richTextSnapshot = (root, expected) => root.evaluate((content, fixture) => {
  const exact = (selector, text) => [...content.querySelectorAll(selector)].find(
    (element) => element.textContent.trim() === text,
  );
  const styledSpan = [...content.querySelectorAll('span[style]')].find(
    (element) => element.textContent.trim() === fixture.styled,
  );
  const mark = exact('mark', fixture.styled);
  const strong = exact('strong', fixture.styled);
  const underline = exact('u', fixture.styled);
  const image = content.querySelector(`img[alt="${fixture.imageAlt}"]`);
  const video = content.querySelector('video');
  const source = video?.querySelector('source');
  const attachment = content.querySelector('.file-attachment[data-file-url]');
  const rootBox = content.getBoundingClientRect();
  const box = (element) => {
    if (!element) return null;
    const bounds = element.getBoundingClientRect();
    return { height: bounds.height, width: bounds.width };
  };
  const styledStyle = styledSpan ? getComputedStyle(styledSpan) : null;
  const underlineStyle = underline ? getComputedStyle(underline) : null;
  return {
    attachment: attachment && {
      name: attachment.getAttribute('data-file-name'),
      role: attachment.getAttribute('role'),
      type: attachment.getAttribute('data-file-type'),
      url: attachment.getAttribute('data-file-url'),
    },
    blockquote: exact('blockquote', fixture.quote)?.textContent.trim() || null,
    bulletItems: [...content.querySelectorAll('ul > li')].map(
      (item) => item.textContent.trim(),
    ),
    code: exact('pre code', fixture.code)?.textContent.trim() || null,
    heading: exact('h2', fixture.heading)?.textContent.trim() || null,
    image: image && {
      alt: image.getAttribute('alt'),
      className: image.getAttribute('class'),
      computed: box(image),
      height: image.getAttribute('height'),
      src: image.getAttribute('src'),
      width: image.getAttribute('width'),
    },
    link: exact('a', fixture.link)?.getAttribute('href') || null,
    numberedItems: [...content.querySelectorAll('ol > li')].map(
      (item) => item.textContent.trim(),
    ),
    rootWidth: rootBox.width,
    styled: {
      backgroundColor: mark ? getComputedStyle(mark).backgroundColor : null,
      color: mark ? getComputedStyle(mark).color : styledStyle?.color || null,
      fontFamily: styledStyle?.fontFamily || null,
      fontSize: styledStyle?.fontSize || null,
      fontWeight: strong ? getComputedStyle(strong).fontWeight : null,
      textDecoration: underlineStyle?.textDecorationLine || null,
    },
    table: {
      cells: [...content.querySelectorAll('table tr')].map(
        (row) => row.querySelectorAll('th, td').length,
      ),
      rows: content.querySelectorAll('table tr').length,
    },
    video: video && {
      computed: box(video),
      controls: video.hasAttribute('controls'),
      height: video.getAttribute('height'),
      src: video.getAttribute('src') || source?.getAttribute('src') || null,
      type: source?.getAttribute('type') || null,
      width: video.getAttribute('width'),
    },
  };
}, expected);

const expectRichText = async (
  root,
  media,
  { onCheckpoint, rendered = true, wide = false } = {},
) => {
  await expect(root).toContainText(FIXTURE.heading);
  onCheckpoint?.('rich-root-heading-ready');
  if (rendered) {
    await expect(root.locator('.file-attachment[data-file-url]')).toHaveAttribute(
      'role',
      'button',
    );
    onCheckpoint?.('rich-rendered-attachment-ready');
  }
  const snapshot = await richTextSnapshot(root, FIXTURE);
  onCheckpoint?.('rich-snapshot-ready');
  expect(snapshot.attachment).toMatchObject({
    name: FIXTURE.pdfName,
    type: 'application/pdf',
    url: media.pdf,
  });
  onCheckpoint?.('rich-attachment-ready');
  expect(snapshot.blockquote).toBe(FIXTURE.quote);
  expect(snapshot.bulletItems).toEqual(FIXTURE.bullets);
  expect(snapshot.numberedItems).toEqual(FIXTURE.numbered);
  onCheckpoint?.('rich-blocks-ready');
  expect(snapshot.code).toBe(FIXTURE.code);
  onCheckpoint?.('rich-code-ready');
  expect(snapshot.heading).toBe(FIXTURE.heading);
  onCheckpoint?.('rich-heading-ready');
  expect(snapshot.link).toBe('/student-hub');
  onCheckpoint?.('rich-link-ready');
  expect(snapshot.image).toMatchObject({
    alt: FIXTURE.imageAlt,
    height: '360',
    src: media.image,
    width: '640',
  });
  onCheckpoint?.('rich-image-ready');
  expect(snapshot.styled).toMatchObject({
    backgroundColor: 'rgb(254, 243, 199)',
    color: 'rgb(29, 78, 216)',
    fontSize: '24px',
  });
  onCheckpoint?.('rich-styles-ready');
  expect(snapshot.table).toEqual({ cells: [3, 3, 3], rows: 3 });
  onCheckpoint?.('rich-table-ready');
  expect(snapshot.video).toMatchObject({
    controls: true,
    height: '360',
    src: media.video,
    type: 'video/webm',
    width: '640',
  });
  onCheckpoint?.('rich-video-ready');
  expect(snapshot.image.className).toContain('mx-auto');
  expect(snapshot.styled.fontFamily).toContain('Georgia');
  expect(Number.parseInt(snapshot.styled.fontWeight, 10)).toBeGreaterThanOrEqual(700);
  expect(snapshot.styled.textDecoration).toContain('underline');
  if (rendered) expect(snapshot.attachment.role).toBe('button');
  if (wide) {
    expect(snapshot.image.computed.width).toBeCloseTo(640, 0);
    expect(snapshot.image.computed.height).toBeCloseTo(360, 0);
    expect(snapshot.video.computed.width).toBeCloseTo(640, 0);
    expect(snapshot.video.computed.height).toBeCloseTo(360, 0);
  } else {
    expect(snapshot.image.computed.width).toBeLessThanOrEqual(snapshot.rootWidth + 1);
    expect(snapshot.video.computed.width).toBeLessThanOrEqual(snapshot.rootWidth + 1);
  }
  return snapshot;
};

const VIEWPORT_FIT = Object.freeze({
  detached: 'detached',
  evaluateError: 'evaluate-error',
  fits: 'fits',
  hidden: 'hidden',
  invalid: 'invalid-rect',
  leftOverflow: 'left-overflow',
  noClientRect: 'no-client-rect',
  notSampled: 'unavailable-or-not-sampled',
  rightOverflow: 'right-overflow',
  zeroHeight: 'zero-height',
  zeroWidth: 'zero-width',
});
const MOBILE_COMPOSER_MEASUREMENT_CHECKPOINT = Object.freeze({
  [VIEWPORT_FIT.detached]: 'mobile-edit-composer-measurement-detached',
  [VIEWPORT_FIT.evaluateError]: 'mobile-edit-composer-measurement-evaluate-error',
  [VIEWPORT_FIT.fits]: 'mobile-edit-composer-measurement-fits',
  [VIEWPORT_FIT.hidden]: 'mobile-edit-composer-measurement-hidden',
  [VIEWPORT_FIT.invalid]: 'mobile-edit-composer-measurement-invalid-rect',
  [VIEWPORT_FIT.leftOverflow]: 'mobile-edit-composer-measurement-left-overflow',
  [VIEWPORT_FIT.noClientRect]: 'mobile-edit-composer-measurement-no-client-rect',
  [VIEWPORT_FIT.notSampled]: 'mobile-edit-composer-measurement-unavailable-or-not-sampled',
  [VIEWPORT_FIT.rightOverflow]: 'mobile-edit-composer-measurement-right-overflow',
  [VIEWPORT_FIT.zeroHeight]: 'mobile-edit-composer-measurement-zero-height',
  [VIEWPORT_FIT.zeroWidth]: 'mobile-edit-composer-measurement-zero-width',
});

const measureDomViewportFit = async (locator) => locator.evaluate((element, categories) => {
  if (!element.isConnected) return categories.detached;
  const style = window.getComputedStyle(element);
  if (
    style.display === 'none'
    || style.visibility === 'hidden'
    || style.visibility === 'collapse'
  ) return categories.hidden;
  if (element.getClientRects().length === 0) return categories.noClientRect;
  const rect = element.getBoundingClientRect();
  const geometry = [rect.left, rect.right, rect.width, rect.height, window.innerWidth];
  if (
    !geometry.every(Number.isFinite)
    || rect.width < 0
    || rect.height < 0
    || window.innerWidth <= 0
  ) return categories.invalid;
  if (rect.width === 0) return categories.zeroWidth;
  if (rect.height === 0) return categories.zeroHeight;
  if (rect.left < -1) return categories.leftOverflow;
  if (rect.right > window.innerWidth + 1) return categories.rightOverflow;
  return categories.fits;
}, VIEWPORT_FIT, { timeout: 10_000 }).catch(() => VIEWPORT_FIT.evaluateError);

const assertFitsViewport = async (locator, { onFinalMeasurement } = {}) => {
  let lastMeasurement = VIEWPORT_FIT.notSampled;
  try {
    await expect.poll(async () => {
      lastMeasurement = await measureDomViewportFit(locator);
      return lastMeasurement;
    }, {
      intervals: [50, 100, 250],
      timeout: 15_000,
    }).toBe(VIEWPORT_FIT.fits);
  } finally {
    onFinalMeasurement?.(lastMeasurement);
  }
};

test('the LitBlogs editor preserves one rich post across every author and course view', async ({
  baseURL,
  journey,
}, testInfo) => {
  test.setTimeout(180_000);
  const checkpoint = (description) => testInfo.annotations.push({ type: 'checkpoint', description });

  const teacher = await journey.openRole('teacher');
  const author = await journey.openRole('student');
  const peer = await journey.openRole('student2');
  const teacherObservations = monitorPage(teacher.page, baseURL);
  const authorObservations = monitorPage(author.page, baseURL);
  const peerObservations = monitorPage(peer.page, baseURL);
  const suffix = journey.credentials.run_id;
  const className = `Rich Text Parity ${suffix}`;
  const initialTitle = `Portable Lesson ${suffix}`;
  const finalTitle = `${initialTitle}${FIXTURE.editedTitleSuffix}`;
  journey.redact(className, initialTitle, finalTitle, ...Object.values(FIXTURE).flat());

  const classroom = await responseJson(await teacher.api('/classes', {
    method: 'POST',
    data: { name: className, description: 'Synthetic rich-text browser verification' },
  }));
  for (const session of [author, peer]) {
    await responseJson(await session.api('/student/join-class', {
      method: 'POST',
      data: { access_code: classroom.access_code },
    }));
  }
  checkpoint('class-and-enrollment-ready');

  await author.page.setViewportSize({ width: 1440, height: 900 });
  await author.page.goto(`/class-feed/${classroom.id}`);
  await expect(author.page.getByRole('heading', { name: className, exact: true })).toBeVisible();
  await author.page.getByRole('button', { name: 'Create New Post', exact: true }).click();
  let composer = author.page.getByRole('dialog', { name: 'Create post' });
  await expect(composer).toBeVisible();
  await expect(composer).toHaveAttribute('aria-modal', 'true');
  const titleInput = composer.getByPlaceholder('Enter a descriptive title for your post');
  await expect(titleInput).toBeFocused();

  await author.page.keyboard.press('Escape');
  await expect(composer).toHaveCount(0);
  await author.page.getByRole('button', { name: 'Create New Post', exact: true }).click();
  composer = author.page.getByRole('dialog', { name: 'Create post' });
  await expect(composer).toBeVisible();
  await composer.getByPlaceholder('Enter a descriptive title for your post').fill(initialTitle);

  const editor = composer.getByRole('textbox', { name: 'Post content' });
  const toolbar = composer.getByRole('toolbar', { name: 'Rich text formatting' });
  await expect(editor).toBeVisible();
  await expect(toolbar).toBeVisible();
  checkpoint('editor-open');
  await editor.click();
  const editorLines = [
    FIXTURE.heading,
    FIXTURE.styled,
    FIXTURE.quote,
    ...FIXTURE.bullets,
    ...FIXTURE.numbered,
    FIXTURE.link,
    FIXTURE.code,
    FIXTURE.mediaAnchor,
  ];
  for (const [index, line] of editorLines.entries()) {
    await author.page.keyboard.type(line);
    if (index < editorLines.length - 1) await author.page.keyboard.press('Enter');
  }

  await selectTextRange(editor, FIXTURE.heading);
  await toolbar.getByRole('combobox', { name: 'Block style' }).selectOption('heading-2');
  await selectTextRange(editor, FIXTURE.styled);
  await toolbar.getByRole('button', { name: 'Bold' }).click();
  await toolbar.getByRole('button', { name: 'Underline' }).click();
  await toolbar.getByRole('combobox', { name: 'Font family' }).selectOption({ label: 'Georgia' });
  await toolbar.getByRole('combobox', { name: 'Font size' }).selectOption({ label: '18 pt' });

  await toolbar.getByRole('button', { name: /Text color:/ }).click();
  const textPalette = composer.getByRole('dialog', { name: 'Text color palette' });
  await expect(textPalette).toBeVisible();
  const blueSwatch = textPalette.getByRole('button', { name: 'Blue #1d4ed8' });
  const blueSample = blueSwatch.locator('.litblogs-color-swatch__sample');
  await expect(blueSample).toBeVisible();
  expect(await blueSample.evaluate((sample) => getComputedStyle(sample).backgroundColor))
    .toBe('rgb(29, 78, 216)');
  await blueSwatch.click();

  await toolbar.getByRole('button', { name: /Highlight color:/ }).click();
  const highlightPalette = composer.getByRole('dialog', { name: 'Highlight color palette' });
  await expect(highlightPalette).toBeVisible();
  const amberSample = highlightPalette
    .getByRole('button', { name: 'Amber #fef3c7' })
    .locator('.litblogs-color-swatch__sample');
  await expect(amberSample).toBeVisible();
  expect(await amberSample.evaluate((sample) => getComputedStyle(sample).backgroundColor))
    .toBe('rgb(254, 243, 199)');
  await author.page.keyboard.press('ArrowRight');
  await author.page.keyboard.press('Enter');
  await expect(highlightPalette).toHaveCount(0);
  await expect(editor.locator('h2')).toHaveText(FIXTURE.heading);
  checkpoint('heading-ready-after-inline-formatting');

  await selectTextRange(editor, FIXTURE.quote);
  await toolbar.getByRole('combobox', { name: 'Block style' }).selectOption('blockquote');
  await selectTextRange(editor, FIXTURE.bullets[0], FIXTURE.bullets[1]);
  await toolbar.getByRole('button', { name: 'Bulleted list' }).click();
  await selectTextRange(editor, FIXTURE.numbered[0], FIXTURE.numbered[1]);
  await toolbar.getByRole('button', { name: 'Numbered list' }).click();
  await placeCaretAfterText(editor, FIXTURE.mediaAnchor);
  await author.page.keyboard.press('Enter');
  await expect(editor.locator('h2')).toHaveText(FIXTURE.heading);
  checkpoint('heading-ready-after-pdf-placement-enter');
  const pdfChooserPromise = author.page.waitForEvent('filechooser');
  await toolbar.getByRole('button', { name: 'Insert PDF attachment' }).click();
  const pdfChooser = await pdfChooserPromise;
  const pdfUploaded = waitForApiResponse(author.page, 'POST', '/api/upload/file');
  await pdfChooser.setFiles(PDF);
  const pdfAsset = await responseJson(await pdfUploaded);
  checkpoint('pdf-upload-response');
  if (await composer.locator('.litblogs-editor__upload-error').count()) {
    checkpoint('pdf-editor-alert-present');
  } else {
    checkpoint('pdf-editor-alert-absent');
  }
  const editorAttachment = editor.locator('[data-node-kind="attachment"]');
  await expect(editorAttachment).toBeAttached();
  await expect(editorAttachment.locator('.file-name')).toHaveText(FIXTURE.pdfName);
  checkpoint('pdf-ready');
  await expect(editor.locator('h2')).toHaveText(FIXTURE.heading);
  checkpoint('heading-ready-after-pdf');
  await expect(editor).toContainText(FIXTURE.code);
  checkpoint('code-text-after-pdf-ready');

  await placeCaretAfterText(editor, FIXTURE.mediaAnchor);
  await author.page.keyboard.press('Enter');
  await expect(editor.locator('h2')).toHaveText(FIXTURE.heading);
  checkpoint('heading-ready-after-table-placement-enter');
  await toolbar.getByRole('button', { name: 'Insert table' }).click();
  checkpoint('text-formatting-ready');
  await expect(editor.locator('h2')).toHaveText(FIXTURE.heading);
  checkpoint('heading-ready-after-table');
  await expect(editor).toContainText(FIXTURE.code);
  checkpoint('code-text-after-table-ready');

  await placeCaretAfterText(editor, FIXTURE.mediaAnchor);
  await author.page.keyboard.press('Enter');
  await expect(editor.locator('h2')).toHaveText(FIXTURE.heading);
  checkpoint('heading-ready-after-paste-placement-enter');
  await author.context.grantPermissions(
    ['clipboard-read', 'clipboard-write'],
    { origin: new URL(baseURL).origin },
  );
  await author.page.evaluate(async (pasteFixture) => {
    const html = `<p><strong>${pasteFixture.pastedText}</strong>`
      + `<img alt="Pasted browser image" src="data:image/png;base64,${pasteFixture.encodedImage}"></p>`;
    await navigator.clipboard.write([new ClipboardItem({
      'text/html': new Blob([html], { type: 'text/html' }),
      'text/plain': new Blob([pasteFixture.pastedText], { type: 'text/plain' }),
    })]);
  }, { encodedImage: IMAGE.buffer.toString('base64'), pastedText: FIXTURE.pasted });
  const clipboardProbe = await author.page.evaluate(async () => {
    const items = await navigator.clipboard.read();
    const htmlItem = items.find((item) => item.types.includes('text/html'));
    const html = htmlItem ? await (await htmlItem.getType('text/html')).text() : '';
    return {
      hasDataImage: html.includes('data:image/png;base64,'),
      hasStrongText: html.includes('<strong>Safe pasted strong context</strong>'),
    };
  });
  expect(clipboardProbe).toEqual({ hasDataImage: true, hasStrongText: true });
  checkpoint('clipboard-seeded');
  const pastedImageUploaded = waitForApiResponse(author.page, 'POST', '/api/upload/image');
  await editor.focus();
  const cdp = await author.context.newCDPSession(author.page);
  await cdp.send('Input.dispatchKeyEvent', {
    type: 'keyDown',
    modifiers: 2,
    key: 'v',
    code: 'KeyV',
    windowsVirtualKeyCode: 86,
    commands: ['Paste'],
  });
  await cdp.send('Input.dispatchKeyEvent', {
    type: 'keyUp',
    modifiers: 2,
    key: 'v',
    code: 'KeyV',
    windowsVirtualKeyCode: 86,
  });
  await cdp.detach();
  checkpoint('paste-event-dispatched');
  await expect(editor.locator('strong').filter({ hasText: FIXTURE.pasted })).toHaveText(
    FIXTURE.pasted,
  );
  checkpoint('paste-safe-text-ready');
  const pastedImageAsset = await responseJson(await pastedImageUploaded);
  await expect(editor.locator('img[alt="pasted-image.png"]')).toBeVisible();
  await expect(editor.locator('strong').filter({ hasText: FIXTURE.pasted })).toHaveText(
    FIXTURE.pasted,
  );
  expect(await editor.innerHTML()).not.toContain('data:image/');
  checkpoint('data-image-paste-ready');
  await expect(editor.locator('h2')).toHaveText(FIXTURE.heading);
  checkpoint('heading-ready-after-paste');
  await expect(editor).toContainText(FIXTURE.code);
  checkpoint('code-text-after-paste-ready');

  await placeCaretAfterText(editor, FIXTURE.mediaAnchor);
  await author.page.keyboard.press('Enter');
  await expect(editor.locator('h2')).toHaveText(FIXTURE.heading);
  checkpoint('heading-ready-after-image-placement-enter');
  await toolbar.getByRole('button', { name: 'Insert image' }).click();
  checkpoint('image-dialog-requested');
  const imageDialog = composer.getByRole('dialog', { name: 'Insert image' });
  await expect(imageDialog).toBeVisible();
  checkpoint('image-dialog-visible');
  await expect(imageDialog.getByRole('textbox', { name: 'School image URL' })).toBeFocused();
  checkpoint('image-dialog-focus-ready');
  const [imageChooser] = await Promise.all([
    author.page.waitForEvent('filechooser'),
    imageDialog.getByRole('button', { name: 'Upload from computer' }).click().then(() => {
      checkpoint('image-upload-button-clicked');
    }),
  ]);
  checkpoint('image-filechooser-acquired');
  const imageUploaded = waitForApiResponse(author.page, 'POST', '/api/upload/image');
  await imageChooser.setFiles(IMAGE);
  checkpoint('image-file-selected');
  const imageAsset = await responseJson(await imageUploaded);
  checkpoint('image-upload-response');
  await expect(composer.getByTestId('litblogs-editor')).not.toHaveAttribute('aria-busy', 'true');
  checkpoint('image-upload-idle');
  const editorImage = editor.locator(`img[alt="${IMAGE.name}"]`);
  await expect(editorImage).toBeVisible();
  checkpoint('image-editor-node-ready');
  await expect(editor.locator('h2')).toHaveText(FIXTURE.heading);
  checkpoint('heading-ready-after-image-upload');
  await editorImage.click();
  await expect(editor.locator('h2')).toHaveText(FIXTURE.heading);
  checkpoint('heading-ready-after-image-selection');
  await editor.getByRole('textbox', { name: 'Image description' }).fill(FIXTURE.imageAlt);
  await expect(editor.locator('h2')).toHaveText(FIXTURE.heading);
  checkpoint('heading-ready-after-image-alt');
  await editor.getByRole('combobox', { name: 'Image width' }).selectOption('50%');
  await expect(editor.locator('h2')).toHaveText(FIXTURE.heading);
  checkpoint('heading-ready-after-image-width-preset');
  await editor.getByRole('spinbutton', { name: 'Custom image width (pixels)' }).fill('640');
  await expect(editor.locator('h2')).toHaveText(FIXTURE.heading);
  checkpoint('heading-ready-after-image-custom-width');
  await editor.getByRole('spinbutton', { name: 'Custom image height (pixels)' }).fill('360');
  await expect(editor.locator('h2')).toHaveText(FIXTURE.heading);
  checkpoint('heading-ready-after-image-custom-height');
  await editor.getByRole('button', { name: 'Center image' }).click();
  checkpoint('image-ready');
  await expect(editor.locator('h2')).toHaveText(FIXTURE.heading);
  checkpoint('heading-ready-after-image');
  await expect(editor).toContainText(FIXTURE.code);
  checkpoint('code-text-after-image-ready');

  const video = await generateWebm(author.page);
  checkpoint('webm-ready');
  await placeCaretAfterText(editor, FIXTURE.mediaAnchor);
  await author.page.keyboard.press('Enter');
  await expect(editor.locator('h2')).toHaveText(FIXTURE.heading);
  checkpoint('heading-ready-after-video-placement-enter');
  await author.page.route('**/api/upload/video', async (route) => {
    await new Promise((resolve) => setTimeout(resolve, 500));
    await route.continue();
  }, { times: 1 });
  const videoChooserPromise = author.page.waitForEvent('filechooser');
  await toolbar.getByRole('button', { name: 'Insert video' }).click();
  const videoChooser = await videoChooserPromise;
  const videoUploaded = waitForApiResponse(author.page, 'POST', '/api/upload/video');
  await videoChooser.setFiles(video);
  await expect(composer.getByTestId('litblogs-editor')).toHaveAttribute('aria-busy', 'true');
  const publishButton = composer.locator('button[type="submit"]');
  await expect(publishButton).toBeDisabled();
  await expect(publishButton).toHaveText(/Uploading media/);
  const videoAsset = await responseJson(await videoUploaded);
  await expect(editor.locator('video')).toBeVisible();
  checkpoint('video-ready');
  await expect(editor.locator('h2')).toHaveText(FIXTURE.heading);
  checkpoint('heading-ready-after-video');
  await expect(editor).toContainText(FIXTURE.code);
  checkpoint('code-text-after-video-ready');
  await selectTextRange(editor, FIXTURE.code);
  await author.page.keyboard.press('Control+Alt+c');
  await expect(editor.locator('pre code')).toHaveText(FIXTURE.code);
  checkpoint('code-block-ready');
  await expect(editor.locator('h2')).toHaveText(FIXTURE.heading);
  checkpoint('heading-ready-after-code');
  await selectTextRange(editor, FIXTURE.link);
  await toolbar.getByRole('button', { name: 'Link' }).click();
  const linkDialog = composer.getByRole('dialog', { name: 'Edit link' });
  await expect(linkDialog).toBeVisible();
  await linkDialog.getByRole('textbox', { name: 'Link URL' }).fill('/student-hub');
  await author.page.keyboard.press('Enter');
  await expect(linkDialog).toHaveCount(0);
  await expect(editor.locator('a[href="/student-hub"]')).toHaveText(FIXTURE.link);
  checkpoint('link-ready');
  await expect(editor.locator('h2')).toHaveText(FIXTURE.heading);
  checkpoint('heading-ready-after-link');

  const media = {
    image: imageAsset.url,
    pastedImage: pastedImageAsset.url,
    pdf: pdfAsset.url,
    video: videoAsset.url,
  };
  const editorHtml = await editor.innerHTML();
  expect(editorHtml).not.toContain('data:image/');
  expect(await headingProbe(author.page, editorHtml, FIXTURE.heading)).toEqual({
    hasHeadingElement: true,
    hasHeadingText: true,
  });
  checkpoint('live-editor-heading-ready');
  await expect(editor.locator('iframe')).toHaveCount(0);
  checkpoint('media-ready');
  let alignmentTrigger = toolbar.getByRole('button', { name: 'Text alignment: Left' });
  await alignmentTrigger.click();
  const alignmentMenu = toolbar.getByRole('menu', { name: 'Text alignment' });
  await expect(alignmentMenu).toBeVisible();
  await expect(alignmentMenu.getByRole('menuitemradio')).toHaveCount(3);
  await takeLocalVisual(author.page, 'alignment-menu-desktop');
  await alignmentMenu.getByRole('menuitemradio', { name: 'Align center' }).click();
  alignmentTrigger = toolbar.getByRole('button', { name: 'Text alignment: Center' });
  await expect(alignmentTrigger).toBeVisible();
  await alignmentTrigger.click();
  await toolbar
    .getByRole('menu', { name: 'Text alignment' })
    .getByRole('menuitemradio', { name: 'Align left' })
    .click();
  await expect(toolbar.getByRole('button', { name: 'Text alignment: Left' })).toBeVisible();
  await takeLocalVisual(author.page, 'editor-desktop');

  const publishedResponse = waitForApiResponse(
    author.page,
    'POST',
    `/api/classes/${classroom.id}/posts`,
  );
  const readyPublishButton = composer.getByRole('button', { name: 'Publish', exact: true });
  await expect(readyPublishButton).toBeEnabled();
  checkpoint('publish-button-ready');
  await readyPublishButton.click();
  const rawPublishedResponse = await publishedResponse;
  checkpoint('publish-response-received');
  const publishStatus = rawPublishedResponse.status();
  checkpoint([200, 400, 403, 409, 413, 422, 500].includes(publishStatus)
    ? `publish-status-${publishStatus}`
    : 'publish-status-other');
  const requestBody = rawPublishedResponse.request().postDataJSON();
  expect(await headingProbe(author.page, requestBody.content, FIXTURE.heading)).toEqual({
    hasHeadingElement: true,
    hasHeadingText: true,
  });
  checkpoint('publish-request-heading-ready');
  const published = await responseJson(rawPublishedResponse);
  await expect(composer).toHaveCount(0);
  checkpoint('composer-closed');
  checkpoint(published.content.includes(FIXTURE.heading)
    ? 'published-heading-text-present'
    : 'published-heading-text-absent');
  checkpoint(/<h2(?:\s|>)/.test(published.content)
    ? 'published-heading-element-present'
    : 'published-heading-element-absent');
  expect(await headingProbe(author.page, published.content, FIXTURE.heading)).toEqual({
    hasHeadingElement: true,
    hasHeadingText: true,
  });
  checkpoint('published-heading-ready');
  expect(published.content).not.toContain('data:image/');
  checkpoint('stored-data-url-free');
  expect(published.content).toContain(`<strong>${FIXTURE.pasted}</strong>`);
  checkpoint('stored-safe-paste-ready');
  expect(published.content).not.toMatch(/contenteditable|editor-only|remove-btn|data-node-view/i);
  checkpoint('stored-editor-controls-free');
  for (const [kind, url] of Object.entries(media)) {
    expect(published.content).toContain(url);
    checkpoint(`stored-${kind.toLowerCase()}-reference-ready`);
  }
  checkpoint('published');

  const dimensionedContent = published.content.replace(
    /<video(?![^>]*\bwidth=)([^>]*)>/,
    '<video width="640" height="360"$1>',
  );
  expect(dimensionedContent).not.toBe(published.content);
  checkpoint('video-dimensions-import-ready');
  const dimensionImportResponse = await author.api(`/classes/${classroom.id}/posts/${published.id}`, {
    method: 'PUT',
    data: { title: initialTitle, content: dimensionedContent },
  });
  checkpoint('video-dimensions-response-received');
  const dimensionedPost = await responseJson(dimensionImportResponse);
  checkpoint(dimensionedPost.content.includes(FIXTURE.heading)
    ? 'dimensioned-heading-text-present'
    : 'dimensioned-heading-text-absent');
  checkpoint(/<h2(?:\s|>)/.test(dimensionedPost.content)
    ? 'dimensioned-heading-element-present'
    : 'dimensioned-heading-element-absent');
  expect(dimensionedPost.content).toContain(FIXTURE.heading);
  expect(dimensionedPost.content).toMatch(/<h2(?:\s|>)/);
  checkpoint('dimensioned-response-heading-ready');
  checkpoint('video-dimensions-imported');
  await author.page.reload();
  checkpoint('author-feed-reloaded');

  await author.page.setViewportSize({ width: 390, height: 844 });
  const authorPreview = author.page.getByTestId(`class-feed-post-preview-${published.id}`);
  await expect(authorPreview).toBeVisible();
  checkpoint('mobile-author-preview-ready');
  await author.page.getByRole('button', { name: `Post actions for ${initialTitle}` }).click();
  checkpoint('mobile-author-actions-open');
  const editLoaded = waitForApiResponse(
    author.page,
    'GET',
    `/api/classes/${classroom.id}/posts/${published.id}`,
  );
  await author.page.getByRole('menuitem', { name: 'Edit Post' }).click();
  checkpoint('mobile-author-edit-requested');
  const editResponse = await editLoaded;
  expect(editResponse.status()).toBe(200);
  const editPost = await editResponse.json();
  expect(editPost.content).toContain(FIXTURE.heading);
  expect(editPost.content).toMatch(/<h2(?:\s|>)/);
  checkpoint('mobile-edit-payload-heading-ready');
  checkpoint('mobile-author-edit-response-ready');
  const editComposer = author.page.getByRole('dialog', { name: 'Edit post' });
  await expect(editComposer).toBeVisible();
  checkpoint('mobile-edit-composer-ready');
  await assertFitsViewport(editComposer, {
    onFinalMeasurement: (measurement) => checkpoint(
      MOBILE_COMPOSER_MEASUREMENT_CHECKPOINT[measurement],
    ),
  });
  checkpoint('mobile-edit-composer-fit-ready');
  const editEditorRoot = editComposer.getByTestId('litblogs-editor');
  await expect(editEditorRoot).toBeVisible();
  checkpoint('mobile-edit-editor-root-visible');
  await assertFitsViewport(editEditorRoot);
  checkpoint('mobile-edit-editor-fit-ready');
  checkpoint('mobile-edit-layout-ready');
  const reopenedEditor = editComposer.getByRole('textbox', { name: 'Post content' });
  await expect(reopenedEditor).toBeVisible();
  checkpoint('mobile-edit-editor-visible');
  const reopenedProbe = await reopenedEditor.evaluate((root, heading) => ({
    hasAnyText: Boolean(root.textContent.trim()),
    hasExpectedHeading: [...root.querySelectorAll('h2')].some(
      (element) => element.textContent.trim() === heading,
    ),
    hasExpectedText: root.textContent.includes(heading),
  }), FIXTURE.heading);
  checkpoint(reopenedProbe.hasAnyText ? 'mobile-edit-text-present' : 'mobile-edit-text-empty');
  checkpoint(reopenedProbe.hasExpectedText
    ? 'mobile-edit-heading-text-present'
    : 'mobile-edit-heading-text-absent');
  checkpoint(reopenedProbe.hasExpectedHeading
    ? 'mobile-edit-heading-element-present'
    : 'mobile-edit-heading-element-absent');
  await expectRichText(reopenedEditor, media, { onCheckpoint: checkpoint, rendered: false });
  checkpoint('reopened');
  await takeLocalVisual(author.page, 'editor-mobile-reopened');
  checkpoint('reopened-visual-ready');
  await editComposer.getByPlaceholder('Enter a descriptive title for your post').fill(finalTitle);
  checkpoint('edit-title-ready');
  const updatedResponse = waitForApiResponse(
    author.page,
    'PUT',
    `/api/classes/${classroom.id}/posts/${published.id}`,
  );
  const updateButton = editComposer.getByRole('button', { name: 'Update Post', exact: true });
  await expect(updateButton).toBeEnabled();
  checkpoint('update-button-ready');
  await updateButton.click();
  checkpoint('update-clicked');
  const rawUpdatedResponse = await updatedResponse;
  checkpoint('update-response-received');
  const updated = await responseJson(rawUpdatedResponse);
  checkpoint('update-response-ready');
  expect(updated.title).toBe(finalTitle);
  await expect(editComposer).toHaveCount(0);
  checkpoint('edit-composer-closed');
  const updatedPreview = author.page.getByTestId(`class-feed-post-preview-${published.id}`);
  await expect(updatedPreview).toBeVisible();
  checkpoint('updated-preview-visible');
  const updatedCardTitle = updatedPreview.locator('xpath=../..').getByRole('heading', { level: 4 });
  checkpoint(await updatedCardTitle.evaluate((heading, expectedTitle) => (
    heading.textContent.trim() === expectedTitle
  ), finalTitle) ? 'updated-card-title-current' : 'updated-card-title-stale');
  await expect(updatedCardTitle).toHaveText(finalTitle);
  checkpoint('updated-title-visible');
  await expectRichText(
    updatedPreview,
    media,
    { onCheckpoint: checkpoint },
  );
  checkpoint('updated');

  for (const session of [author, peer, teacher]) {
    for (const url of Object.values(media)) {
      expect((await session.api(url)).status()).toBe(200);
    }
  }

  await peer.page.setViewportSize({ width: 768, height: 1024 });
  await peer.page.goto(`/class-feed/${classroom.id}`);
  await expect(peer.page.getByRole('heading', { name: finalTitle, exact: true })).toBeVisible();
  const peerPreview = peer.page.getByTestId(`class-feed-post-preview-${published.id}`);
  await expectRichText(peerPreview, media);
  await takeLocalVisual(peer.page, 'class-feed-tablet');
  checkpoint('peer-feed-ready');

  await peer.page.setViewportSize({ width: 1440, height: 900 });
  await peer.page.goto(`/class/${classroom.id}/post/${published.id}`);
  const desktopPost = peer.page.getByTestId('post-view-content');
  await expectRichText(desktopPost, media, { wide: true });
  await expect(desktopPost.locator(`img[alt="${FIXTURE.imageAlt}"]`)).toBeVisible();
  await expect(desktopPost.locator('video[controls]')).toBeVisible();
  const postUrl = peer.page.url();
  const pdfButton = desktopPost.getByRole('button', { name: `Open PDF ${FIXTURE.pdfName}` });
  await pdfButton.focus();
  await peer.page.keyboard.press('Enter');
  let pdfModal = peer.page.getByRole('dialog', { name: FIXTURE.pdfName });
  await expect(pdfModal).toBeVisible();
  expect(peer.page.url()).toBe(postUrl);
  await peer.page.keyboard.press('Escape');
  await expect(pdfModal).toHaveCount(0);
  await expect(pdfButton).toBeFocused();
  await pdfButton.click();
  pdfModal = peer.page.getByRole('dialog', { name: FIXTURE.pdfName });
  await expect(pdfModal).toBeVisible();
  await pdfModal.getByRole('button', { name: 'Close PDF preview' }).click();
  await expect(pdfModal).toHaveCount(0);
  await peer.page.setViewportSize({ width: 390, height: 844 });
  await expectRichText(desktopPost, media);
  await assertFitsViewport(desktopPost);
  await takeLocalVisual(peer.page, 'post-view-mobile');
  checkpoint('post-view-ready');

  await teacher.page.setViewportSize({ width: 1440, height: 900 });
  await teacher.page.evaluate(() => {
    localStorage.setItem('darkMode', 'true');
    let settings = {};
    try {
      settings = JSON.parse(localStorage.getItem('litblogs_settings') || '{}');
    } catch {
      settings = {};
    }
    localStorage.setItem('litblogs_settings', JSON.stringify({ ...settings, darkMode: true }));
  });
  await teacher.page.reload();
  await teacher.page.getByRole('button', { name: 'Classes', exact: true }).click();
  await teacher.page.getByRole('heading', { name: className, exact: true }).click();
  await teacher.page.getByRole('button', { name: 'Blogs', exact: true }).click();
  const classDetailsPreview = teacher.page.getByTestId(
    `class-details-post-preview-${published.id}`,
  );
  await expectRichText(classDetailsPreview, media, { wide: true });
  await expect(classDetailsPreview).not.toHaveClass(/rich-text-content--dark/);
  expect(await classDetailsPreview.evaluate((node) => getComputedStyle(node).color))
    .toBe('rgb(75, 85, 99)');
  expect(await classDetailsPreview.evaluate(
    (node) => getComputedStyle(node).getPropertyValue('--rich-text-surface').trim(),
  )).toBe('#ffffff');
  await takeLocalVisual(teacher.page, 'class-details-dark-dashboard-white-card');
  checkpoint('class-details-ready');

  await author.page.setViewportSize({ width: 768, height: 1024 });
  await author.page.goto('/student-hub');
  await author.page.getByRole('button', { name: 'Post History', exact: true }).click();
  const studentHubPreview = author.page.getByTestId(`student-hub-post-preview-${published.id}`);
  await expectRichText(studentHubPreview, media);
  checkpoint('student-hub-ready');

  await teacher.page.setViewportSize({ width: 768, height: 1024 });
  await teacher.page.goto(`/class/${classroom.id}/student/${journey.credentials.users.student.id}`);
  checkpoint('student-details-route-ready');
  const postsTab = teacher.page.getByRole('button', { name: 'Posts', exact: true });
  await expect(postsTab).toBeVisible();
  checkpoint('student-details-posts-tab-ready');
  await postsTab.click();
  checkpoint('student-details-posts-tab-clicked');
  const studentDetailsPreview = teacher.page.getByTestId(
    `student-details-post-preview-${published.id}`,
  );
  await expect(studentDetailsPreview).toBeVisible();
  checkpoint('student-details-preview-visible');
  await expectRichText(studentDetailsPreview, media, { onCheckpoint: checkpoint });
  checkpoint('student-details-rich-ready');
  await expect(studentDetailsPreview).toHaveClass(/rich-text-content--dark/);
  checkpoint('student-details-dark-class-ready');
  expect(await studentDetailsPreview.evaluate((node) => getComputedStyle(node).color))
    .toBe('rgb(229, 231, 235)');
  checkpoint('student-details-dark-color-ready');
  expect(await studentDetailsPreview.evaluate(
    (node) => getComputedStyle(node).getPropertyValue('--rich-text-surface').trim(),
  )).toBe('#0f172a');
  checkpoint('student-details-dark-surface-ready');
  await takeLocalVisual(teacher.page, 'student-details-dark-tablet');
  checkpoint('student-details-ready');

  expectCleanPage(authorObservations);
  expectCleanPage(peerObservations);
  expectCleanPage(teacherObservations);
});
