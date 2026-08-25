import { spawn, spawnSync } from 'node:child_process';
import crypto from 'node:crypto';
import fs from 'node:fs';
import net from 'node:net';
import os from 'node:os';
import path from 'node:path';
import { fileURLToPath } from 'node:url';

import { chromium } from '@playwright/test';

import { requiresAvailableEnvironment } from './support/availability.mjs';

const backendDirectory = path.resolve(path.dirname(fileURLToPath(import.meta.url)), '..');
const supportDirectory = path.join(backendDirectory, 'e2e', 'support');
const executableName = (name) => process.platform === 'win32' ? `${name}.exe` : name;

const runCommand = (command, args, options = {}) => new Promise((resolve, reject) => {
  const child = spawn(command, args, {
    cwd: backendDirectory,
    env: options.env || process.env,
    shell: false,
    windowsHide: true,
  });
  let stdout = '';
  let stderr = '';
  child.stdout.on('data', (chunk) => { stdout += chunk.toString(); });
  child.stderr.on('data', (chunk) => { stderr += chunk.toString(); });
  child.once('error', reject);
  child.once('exit', (code) => {
    if (code === 0) {
      resolve({ stdout, stderr });
      return;
    }
    reject(new Error(options.failureMessage || `E2E command failed with exit code ${code}`));
  });
});

const commandWorks = (command) => {
  const result = spawnSync(command, ['--version'], {
    shell: false,
    stdio: 'ignore',
    windowsHide: true,
  });
  return result.status === 0;
};

const findPython = () => {
  const candidates = [
    process.env.E2E_PYTHON,
    path.join(
      backendDirectory,
      '.venv',
      process.platform === 'win32' ? 'Scripts/python.exe' : 'bin/python',
    ),
    process.platform === 'win32' ? 'python' : 'python3',
    'python',
  ].filter(Boolean);
  return candidates.find(commandWorks) || null;
};

const findPostgresBin = () => {
  const candidates = [
    process.env.E2E_POSTGRES_BIN,
    process.platform === 'win32' ? 'C:\\Program Files\\PostgreSQL\\17\\bin' : null,
    '/usr/lib/postgresql/17/bin',
    '/usr/local/pgsql/bin',
  ].filter(Boolean);
  return candidates.find((candidate) => (
    ['initdb', 'pg_ctl'].every((name) => (
      fs.existsSync(path.join(candidate, executableName(name)))
    ))
  )) || null;
};

const reservePort = () => new Promise((resolve, reject) => {
  const server = net.createServer();
  server.unref();
  server.once('error', reject);
  server.listen(0, '127.0.0.1', () => {
    const address = server.address();
    server.close(() => resolve(address.port));
  });
});

const assertPortFree = (port) => new Promise((resolve, reject) => {
  const server = net.createServer();
  server.unref();
  server.once('error', () => reject(new Error(`E2E port ${port} is unavailable`)));
  server.listen(port, '127.0.0.1', () => server.close(resolve));
});

const startService = (command, args, { env, logPath }) => {
  const output = fs.openSync(logPath, 'a');
  const child = spawn(command, args, {
    cwd: backendDirectory,
    env,
    shell: false,
    windowsHide: true,
    stdio: ['ignore', output, output],
  });
  child.once('exit', () => fs.closeSync(output));
  return child;
};

const waitForUrl = async (url, serviceName, child, timeoutMs = 60_000) => {
  const deadline = Date.now() + timeoutMs;
  while (Date.now() < deadline) {
    if (child?.exitCode !== null) {
      throw new Error(`${serviceName} exited before becoming ready`);
    }
    try {
      const response = await fetch(url, { redirect: 'manual' });
      if (response.ok) return;
    } catch {
      // The service is still starting.
    }
    await new Promise((resolve) => setTimeout(resolve, 250));
  }
  throw new Error(`${serviceName} did not become ready`);
};

const stopService = async (child) => {
  if (!child || child.exitCode !== null) return;
  child.kill();
  await Promise.race([
    new Promise((resolve) => child.once('exit', resolve)),
    new Promise((resolve) => setTimeout(resolve, 5_000)),
  ]);
};

const skipLocallyOrFail = (reason) => {
  if (requiresAvailableEnvironment()) throw new Error(reason);
  process.env.E2E_LOCAL_SKIP_REASON = reason;
  return async () => {};
};

const randomPassword = () => crypto.randomBytes(48).toString('base64url');
const randomE2eCredential = (byteLength) => (
  `e2e-${crypto.randomBytes(byteLength).toString('hex')}`
);

export default async function globalSetup() {
  if (Number.parseInt(process.versions.node.split('.')[0], 10) !== 24) {
    return skipLocallyOrFail('Browser journeys require Node.js 24');
  }
  if (!fs.existsSync(chromium.executablePath())) {
    return skipLocallyOrFail('Chromium is unavailable; run `npx playwright install chromium`');
  }
  const python = findPython();
  if (!python) {
    return skipLocallyOrFail('Python with the backend dependencies is unavailable');
  }
  if (process.env.CI && !process.env.E2E_ADMIN_DATABASE_URL) {
    throw new Error('CI browser journeys require a disposable E2E_ADMIN_DATABASE_URL');
  }
  if (process.env.E2E_DISPOSABLE_DATABASE_CONFIRMED !== 'litblogs-e2e-only') {
    throw new Error(
      'Set E2E_DISPOSABLE_DATABASE_CONFIRMED=litblogs-e2e-only for the disposable PG17 service',
    );
  }

  const frontendPort = Number.parseInt(process.env.E2E_FRONTEND_PORT || '4173', 10);
  const backendPort = Number.parseInt(process.env.E2E_BACKEND_PORT || '8001', 10);
  await Promise.all([assertPortFree(frontendPort), assertPortFree(backendPort)]);

  const runDirectory = fs.mkdtempSync(path.join(os.tmpdir(), 'litblogs-e2e-'));
  try {
    fs.chmodSync(runDirectory, 0o700);
  } catch {
    // Windows applies the current-user ACL inherited by the runner temp directory.
  }
  const postgresData = path.join(runDirectory, 'postgres');
  const uploadRoot = path.join(runDirectory, 'uploads');
  const buildDirectory = path.join(runDirectory, 'frontend');
  const credentialsFile = path.join(runDirectory, 'credentials.json');
  const failureRedactionsFile = path.join(runDirectory, 'failure-redactions.json');
  const databaseMetadataFile = path.join(runDirectory, 'database.json');
  fs.mkdirSync(uploadRoot, { recursive: true, mode: 0o700 });

  process.env.E2E_RUN_DIR = runDirectory;
  process.env.E2E_CREDENTIALS_FILE = credentialsFile;
  process.env.E2E_FAILURE_REDACTIONS_FILE = failureRedactionsFile;
  process.env.E2E_CSRF_COOKIE_NAME = 'litblogs_e2e_csrf';

  const databaseName = `litblog_test_e2e_${crypto.randomBytes(8).toString('hex')}`;
  const rolePasswords = {
    E2E_MIGRATOR_PASSWORD: randomPassword(),
    E2E_RUNTIME_PASSWORD: randomPassword(),
    E2E_ACCOUNT_OPERATOR_PASSWORD: randomPassword(),
    E2E_INVITATION_OPERATOR_PASSWORD: randomPassword(),
  };
  const postgresLog = path.join(runDirectory, 'postgres.log');
  let adminDatabaseUrl = process.env.E2E_ADMIN_DATABASE_URL || '';
  let pgCtl = null;
  let postgresStarted = false;
  let databaseBootstrapped = false;
  let backend = null;
  let frontend = null;

  const stopPostgres = async () => {
    if (!postgresStarted || !pgCtl) return;
    await runCommand(
      pgCtl,
      ['--pgdata', postgresData, '--wait', '--mode', 'fast', 'stop'],
      { failureMessage: 'Disposable PostgreSQL shutdown failed' },
    ).catch(() => {});
    postgresStarted = false;
  };

  let databaseEnvironment = null;
  const cleanDatabase = async () => {
    if (!databaseBootstrapped || !databaseEnvironment) return;
    await runCommand(
      python,
      [path.join(supportDirectory, 'database.py'), 'cleanup'],
      {
        env: databaseEnvironment,
        failureMessage: 'Disposable PostgreSQL cleanup failed',
      },
    );
    databaseBootstrapped = false;
  };

  try {
    if (!adminDatabaseUrl) {
      const postgresBin = findPostgresBin();
      if (!postgresBin) {
        fs.rmSync(runDirectory, { recursive: true, force: true });
        return skipLocallyOrFail('Local PostgreSQL server binaries are unavailable');
      }
      const postgresPort = await reservePort();
      const clusterAdmin = 'litblogs_e2e_cluster_admin';
      const clusterPassword = randomPassword();
      const passwordFile = path.join(runDirectory, 'postgres-password.txt');
      fs.writeFileSync(passwordFile, `${clusterPassword}\n`, { mode: 0o600 });
      await runCommand(
        path.join(postgresBin, executableName('initdb')),
        [
          '--pgdata', postgresData,
          '--username', clusterAdmin,
          '--pwfile', passwordFile,
          '--auth-local', 'scram-sha-256',
          '--auth-host', 'scram-sha-256',
          '--encoding', 'UTF8',
          '--no-locale',
          '--data-checksums',
        ],
        { failureMessage: 'Disposable PostgreSQL initialization failed' },
      );
      fs.rmSync(passwordFile, { force: true });
      pgCtl = path.join(postgresBin, executableName('pg_ctl'));
      await runCommand(
        pgCtl,
        [
          '--pgdata', postgresData,
          '--log', postgresLog,
          '--options', (
            `-h 127.0.0.1 -p ${postgresPort} `
            + '-c password_encryption=scram-sha-256'
          ),
          '--wait',
          'start',
        ],
        { failureMessage: 'Disposable PostgreSQL startup failed' },
      );
      postgresStarted = true;
      adminDatabaseUrl = (
        `postgresql+psycopg2://${clusterAdmin}:${encodeURIComponent(clusterPassword)}`
        + `@127.0.0.1:${postgresPort}/postgres`
      );
    }

    databaseEnvironment = {
      ...process.env,
      ...rolePasswords,
      E2E_ADMIN_DATABASE_URL: adminDatabaseUrl,
      E2E_DISPOSABLE_DATABASE_CONFIRMED: process.env.E2E_DISPOSABLE_DATABASE_CONFIRMED,
      E2E_DATABASE_NAME: databaseName,
      E2E_DATABASE_METADATA_FILE: databaseMetadataFile,
    };
    await runCommand(
      python,
      [path.join(supportDirectory, 'database.py'), 'bootstrap'],
      {
        env: databaseEnvironment,
        failureMessage: 'Disposable PostgreSQL role bootstrap failed',
      },
    );
    databaseBootstrapped = true;
    const databaseMetadata = JSON.parse(
      fs.readFileSync(databaseMetadataFile, 'utf8'),
    );
    const migratorUrl = databaseMetadata.migrator_url;
    const runtimeUrl = databaseMetadata.runtime_url;

    const baseEnvironment = {
      ...process.env,
      APP_ENV: 'test',
      DATABASE_URL: runtimeUrl,
      SECRET_KEY: randomE2eCredential(48),
      TEACHER_INVITE_HMAC_KEY: randomE2eCredential(48),
      JWT_ISSUER: 'litblogs-e2e',
      JWT_AUDIENCE: 'litblogs-e2e-browser',
      ACCESS_TOKEN_EXPIRE_MINUTES: '30',
      RESET_DATABASE_ON_STARTUP: 'false',
      ADMIN_ACCESS_CODE: randomE2eCredential(24),
      ADMIN_CODE: randomE2eCredential(24),
      LOCAL_PASSWORD_REGISTRATION_ENABLED: 'true',
      FRONTEND_URL: `http://127.0.0.1:${frontendPort}`,
      BASE_URL: `http://127.0.0.1:${frontendPort}`,
      CORS_ALLOWED_ORIGINS: `http://127.0.0.1:${frontendPort}`,
      ALLOWED_HOSTS: '127.0.0.1,localhost',
      ALLOWED_EMAIL_DOMAINS: 'example.com',
      GOOGLE_CLIENT_ID: 'e2e-google-client-id',
      MICROSOFT_CLIENT_ID: 'e2e-microsoft-client-id',
      MICROSOFT_TENANT_ID: '871bd3e0-2dc0-4a40-9b07-9d03068c2364',
      MICROSOFT_ALLOWED_TENANT_IDS: '871bd3e0-2dc0-4a40-9b07-9d03068c2364',
      SESSION_COOKIE_NAME: 'litblogs_e2e_session',
      CSRF_COOKIE_NAME: 'litblogs_e2e_csrf',
      SESSION_COOKIE_SECURE: 'false',
      VAPID_PUBLIC_KEY: '',
      VAPID_PRIVATE_KEY: '',
      VAPID_SUBJECT: 'mailto:e2e@example.test',
      PUSH_NOTIFICATIONS_ENABLED: 'false',
      EMAIL_HOST: '127.0.0.1',
      EMAIL_PORT: '1025',
      EMAIL_USERNAME: 'e2e-mail-user',
      EMAIL_PASSWORD: randomE2eCredential(24),
      EMAIL_FROM: 'e2e@example.com',
      PASSWORD_RESET_WORKER_ENABLED: 'false',
      UPLOAD_ROOT: uploadRoot,
      UPLOAD_SCANNER_REQUIRED: 'false',
    };
    const migrationEnvironment = {
      ...baseEnvironment,
      DATABASE_URL: migratorUrl,
      TEST_DATABASE_URL: migratorUrl,
      TEST_POSTGRES_DATABASE: databaseName,
      LITBLOGS_MIGRATION_DATABASE_URL: migratorUrl,
    };
    await runCommand(
      python,
      ['-m', 'alembic', 'upgrade', 'head'],
      { env: migrationEnvironment, failureMessage: 'Alembic E2E migration failed' },
    );
    await runCommand(
      python,
      [path.join(supportDirectory, 'database.py'), 'finalize-acl'],
      {
        env: databaseEnvironment,
        failureMessage: 'Runtime database credential or ACL probe failed',
      },
    );
    await runCommand(
      python,
      ['-m', 'e2e.support.seed'],
      {
        env: {
          ...baseEnvironment,
          E2E_SEED_DATABASE_URL: migratorUrl,
          E2E_CREDENTIALS_FILE: credentialsFile,
        },
        failureMessage: 'E2E account seeding failed',
      },
    );

    const backendUrl = `http://127.0.0.1:${backendPort}`;
    backend = startService(
      python,
      ['-m', 'uvicorn', 'main:app', '--host', '127.0.0.1', '--port', String(backendPort)],
      {
        env: baseEnvironment,
        logPath: path.join(runDirectory, 'uvicorn.log'),
      },
    );
    await waitForUrl(`${backendUrl}/api/health/live`, 'Uvicorn', backend);
    await waitForUrl(`${backendUrl}/api/health/ready`, 'Uvicorn readiness', backend);

    const viteCli = path.join(backendDirectory, 'node_modules', 'vite', 'bin', 'vite.js');
    const frontendEnvironment = {
      ...process.env,
      E2E_BACKEND_URL: backendUrl,
      E2E_BUILD_DIR: buildDirectory,
      E2E_FRONTEND_PORT: String(frontendPort),
      VITE_APP_BASE_PATH: '/',
    };
    await runCommand(
      process.execPath,
      [viteCli, 'build', '--config', 'vite.e2e.config.js'],
      { env: frontendEnvironment, failureMessage: 'E2E frontend build failed' },
    );
    frontend = startService(
      process.execPath,
      [viteCli, 'preview', '--config', 'vite.e2e.config.js'],
      {
        env: frontendEnvironment,
        logPath: path.join(runDirectory, 'vite-preview.log'),
      },
    );
    await waitForUrl(`http://127.0.0.1:${frontendPort}/sign-in`, 'Vite preview', frontend);

    return async () => {
      await Promise.all([stopService(frontend), stopService(backend)]);
      try {
        await cleanDatabase();
      } finally {
        await stopPostgres();
        fs.rmSync(runDirectory, { recursive: true, force: true });
      }
    };
  } catch (error) {
    await Promise.all([stopService(frontend), stopService(backend)]);
    try {
      await cleanDatabase();
    } catch {
      // Preserve the original failure; the isolated cluster is still stopped below.
    }
    await stopPostgres();
    fs.rmSync(runDirectory, { recursive: true, force: true });
    throw error;
  }
}
