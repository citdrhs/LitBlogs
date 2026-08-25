import assert from 'node:assert/strict';
import fs from 'node:fs';
import os from 'node:os';
import path from 'node:path';
import test from 'node:test';

import SanitizedReporter from './sanitized-reporter.mjs';

test('removes raw attachments and redacts credential values', () => {
  const directory = fs.mkdtempSync(path.join(os.tmpdir(), 'litblogs-reporter-test-'));
  const credentialsFile = path.join(directory, 'credentials.json');
  const rawAttachment = path.join(directory, 'error-context.md');
  const outputDirectory = path.join(directory, 'sanitized-failures');
  const previousCredentialsFile = process.env.E2E_CREDENTIALS_FILE;
  const previousRedactionsFile = process.env.E2E_FAILURE_REDACTIONS_FILE;
  const password = 'synthetic-private-password';
  const draftCanary = 'synthetic-draft-canary';
  const unknownSessionCanary = 'unknown-session-csrf-cookie-canary';
  const redactionsFile = path.join(directory, 'redactions.json');

  try {
    fs.writeFileSync(credentialsFile, JSON.stringify({
      users: {
        student: {
          email: 'synthetic@example.com',
          username: 'synthetic-student',
          password,
        },
      },
    }));
    fs.writeFileSync(rawAttachment, `raw DOM containing ${password} ${draftCanary}`);
    fs.writeFileSync(redactionsFile, JSON.stringify([draftCanary]));
    process.env.E2E_CREDENTIALS_FILE = credentialsFile;
    process.env.E2E_FAILURE_REDACTIONS_FILE = redactionsFile;

    const result = {
      errors: [{
        message: `failed with ${password} and ${draftCanary} ${unknownSessionCanary}`,
        stack: `stack with ${password} and ${draftCanary}`,
        value: `${password} ${draftCanary}`,
      }],
      stdout: [`stdout ${password} ${draftCanary}`],
      stderr: [Buffer.from(`stderr ${password} ${draftCanary}`)],
      attachments: [
        {
          name: 'error-context',
          path: rawAttachment,
          contentType: 'text/markdown',
        },
        {
          name: 'sanitized-failure.json',
          body: Buffer.from(
            `{"title":"fixed browser journey ${unknownSessionCanary}",`
              + `"status":"failed","roles":["STUDENT"],`
              + `"error_count":1,"checkpoints":["fixed-checkpoint"],`
              + `"error_locations":[null],"detail":"${password} ${draftCanary} ${unknownSessionCanary}"}`,
          ),
          contentType: 'application/json',
        },
      ],
    };

    const reporter = new SanitizedReporter({ outputDirectory });
    reporter.onBegin();
    reporter.onTestEnd({ id: 'synthetic-reporter-test' }, result);
    const retainedFiles = fs.readdirSync(outputDirectory);
    assert.equal(retainedFiles.length, 1);
    const sanitizedAttachment = path.join(outputDirectory, retainedFiles[0]);

    assert.equal(fs.existsSync(rawAttachment), false);
    assert.equal(fs.existsSync(sanitizedAttachment), true);
    assert.deepEqual(result.attachments.map(({ name }) => name), [
      'sanitized-failure.json',
    ]);
    assert.equal(JSON.stringify(result.errors).includes(password), false);
    assert.equal(JSON.stringify(result.errors).includes(draftCanary), false);
    assert.equal(result.stdout.join('').includes(password), false);
    assert.equal(result.stdout.join('').includes(draftCanary), false);
    assert.equal(Buffer.concat(result.stderr).includes(Buffer.from(password)), false);
    assert.equal(Buffer.concat(result.stderr).includes(Buffer.from(draftCanary)), false);
    assert.equal(fs.readFileSync(sanitizedAttachment, 'utf8').includes(draftCanary), false);
    assert.equal(fs.readFileSync(sanitizedAttachment, 'utf8').includes(password), false);
    assert.equal(fs.readFileSync(sanitizedAttachment, 'utf8').includes(unknownSessionCanary), false);
    assert.equal(result.attachments[0].path, sanitizedAttachment);
    assert.equal(result.attachments[0].body, undefined);
    if (process.platform !== 'win32') {
      assert.equal(fs.statSync(outputDirectory).mode & 0o777, 0o700);
      assert.equal(fs.statSync(sanitizedAttachment).mode & 0o777, 0o600);
    }
    assert.match(result.errors[0].message, /\[redacted\]/);
  } finally {
    if (previousCredentialsFile === undefined) {
      delete process.env.E2E_CREDENTIALS_FILE;
    } else {
      process.env.E2E_CREDENTIALS_FILE = previousCredentialsFile;
    }
    if (previousRedactionsFile === undefined) {
      delete process.env.E2E_FAILURE_REDACTIONS_FILE;
    } else {
      process.env.E2E_FAILURE_REDACTIONS_FILE = previousRedactionsFile;
    }
    fs.rmSync(directory, { recursive: true, force: true });
  }
});

test('suppresses streamed output and global errors before they reach CI logs', () => {
  const reporter = new SanitizedReporter();
  const canary = 'streamed-private-output-canary';
  const originalStdoutWrite = process.stdout.write;
  const originalStderrWrite = process.stderr.write;
  let observed = '';

  process.stdout.write = (chunk) => {
    observed += String(chunk);
    return true;
  };
  process.stderr.write = (chunk) => {
    observed += String(chunk);
    return true;
  };
  try {
    assert.equal(reporter.printsToStdio(), true);
    reporter.onStdOut(Buffer.from(canary));
    reporter.onStdErr(canary);
    reporter.onError(new Error(canary));
  } finally {
    process.stdout.write = originalStdoutWrite;
    process.stderr.write = originalStderrWrite;
  }

  assert.equal(observed.includes(canary), false);
});

test('prints only a fixed aggregate summary after the run', () => {
  const directory = fs.mkdtempSync(path.join(os.tmpdir(), 'litblogs-reporter-summary-'));
  const reporter = new SanitizedReporter({ outputDirectory: directory });
  const originalStdoutWrite = process.stdout.write;
  let observed = '';

  process.stdout.write = (chunk) => {
    observed += String(chunk);
    return true;
  };
  try {
    reporter.onBegin();
    reporter.onTestEnd({ id: 'private-test-title' }, {
      status: 'passed', errors: [], stdout: [], stderr: [], attachments: [],
    });
    reporter.onTestEnd({ id: 'another-private-title' }, {
      status: 'skipped', errors: [], stdout: [], stderr: [], attachments: [],
    });
    reporter.onTestEnd({ id: 'secret-failing-title' }, {
      status: 'timedOut', errors: [], stdout: [], stderr: [], attachments: [],
    });
    reporter.onEnd();
  } finally {
    process.stdout.write = originalStdoutWrite;
    fs.rmSync(directory, { recursive: true, force: true });
  }

  assert.equal(observed, 'E2E summary: total=3 passed=1 failed=1 skipped=1\n');
  assert.equal(observed.includes('private'), false);
  assert.equal(observed.includes('secret'), false);
});
