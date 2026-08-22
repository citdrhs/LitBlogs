import fs from 'node:fs';
import crypto from 'node:crypto';
import path from 'node:path';

const readSecrets = () => {
  const values = new Set();
  const credentialsFile = process.env.E2E_CREDENTIALS_FILE;
  if (credentialsFile && fs.existsSync(credentialsFile)) {
    try {
      const credentials = JSON.parse(fs.readFileSync(credentialsFile, 'utf8'));
      for (const user of Object.values(credentials.users || {})) {
        for (const key of ['email', 'username', 'password']) {
          if (user[key]) values.add(String(user[key]));
        }
      }
    } catch {
      // A malformed runner-temporary credential file must not be copied into artifacts.
    }
  }
  const redactionsFile = process.env.E2E_FAILURE_REDACTIONS_FILE;
  if (redactionsFile && fs.existsSync(redactionsFile)) {
    try {
      for (const value of JSON.parse(fs.readFileSync(redactionsFile, 'utf8'))) {
        if (value) values.add(String(value));
      }
    } catch {
      // A malformed redaction file is ignored; raw attachments are still removed.
    }
  }
  return values;
};

const redact = (value, secrets) => {
  let output = String(value || '');
  for (const secret of secrets) output = output.split(secret).join('[redacted]');
  return output;
};

export default class SanitizedReporter {
  constructor(options = {}) {
    this.outputDirectory = path.resolve(
      options.outputDirectory || 'test-results/e2e/sanitized-failures',
    );
  }

  onBegin() {
    fs.rmSync(this.outputDirectory, { recursive: true, force: true });
    fs.mkdirSync(this.outputDirectory, { recursive: true, mode: 0o700 });
  }

  printsToStdio() {
    // No other reporter may receive raw streamed output. Playwright still
    // treats this as the sole stdio reporter, while every payload is dropped.
    return true;
  }

  onStdOut() {}

  onStdErr() {}

  onError() {}

  onTestEnd(test, result) {
    const secrets = readSecrets();
    for (const error of result.errors || []) {
      error.message = redact(error.message, secrets);
      error.stack = redact(error.stack, secrets);
      if (error.value) error.value = redact(error.value, secrets);
    }
    for (const streamName of ['stdout', 'stderr']) {
      const chunks = result[streamName] || [];
      const sanitizedChunks = chunks.map((chunk) => {
        const value = Buffer.isBuffer(chunk) ? chunk.toString('utf8') : String(chunk);
        const sanitized = redact(value, secrets);
        return Buffer.isBuffer(chunk) ? Buffer.from(sanitized) : sanitized;
      });
      chunks.splice(0, chunks.length, ...sanitizedChunks);
    }

    const allowed = [];
    for (const attachment of result.attachments || []) {
      if (attachment.name === 'sanitized-failure.json') {
        let content = '';
        if (attachment.path && fs.existsSync(attachment.path)) {
          content = fs.readFileSync(attachment.path, 'utf8');
          fs.rmSync(attachment.path, { force: true });
        }
        if (attachment.body) {
          content = attachment.body.toString('utf8');
        }
        if (content) {
          const testIdentity = `${test.id || test.title || 'browser-journey'}:${result.retry || 0}`;
          const digest = crypto.createHash('sha256').update(testIdentity).digest('hex').slice(0, 16);
          const outputPath = path.join(this.outputDirectory, `failure-${digest}.json`);
          fs.writeFileSync(outputPath, redact(content, secrets), {
            encoding: 'utf8',
            mode: 0o600,
          });
          try {
            fs.chmodSync(outputPath, 0o600);
          } catch {
            // Windows runners preserve the current-user ACL instead of POSIX mode bits.
          }
          allowed.push({
            name: attachment.name,
            contentType: 'application/json',
            path: outputPath,
          });
        }
        continue;
      }
      if (attachment.path) {
        try {
          fs.rmSync(attachment.path, { force: true });
        } catch {
          // The artifact was already absent; never replace it with raw diagnostics.
        }
      }
    }
    result.attachments.splice(0, result.attachments.length, ...allowed);
  }
}
