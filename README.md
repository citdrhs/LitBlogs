# LitBlogs

LitBlogs is a private-school blogging and classroom collaboration application. It uses a React/Vite frontend, a FastAPI backend, and PostgreSQL. Students can publish rich-text posts, comment, react, manage profiles, and complete assignments; teachers can manage classes, assignments, rosters, and student work.

## Local development

Supported development versions are Python 3.13 and Node.js 24 LTS. The frontend package, `.nvmrc`, and `.node-version` fail closed on a different Node major.

```bash
cd litblogs
python -m venv .venv
python -m pip install --require-hashes --only-binary=:all: -r requirements-dev.txt
npm ci
```

Copy `litblogs/.env.example` to an ignored local environment file and replace the development placeholders. The example is intentionally development-only; it is not a production secret template.

Initialize or advance the local SQLite schema explicitly before starting the API. The migration loader accepts this file only when `APP_ENV=development`, `LITBLOGS_MIGRATION_DATABASE_URL` exactly equals `DATABASE_URL`, and the named `.db`/`.sqlite*` file resolves inside `litblogs` without a symlink escape:

```bash
cd litblogs
set -a
. ./.env
set +a
python -m alembic -c alembic.ini upgrade head
python -m alembic -c alembic.ini current --check-heads
```

`upgrade head` is idempotent and is the required fresh-local initialization path; application startup never creates or resets schema.

Run the quality gates from the repository root:

```bash
python -m pytest litblogs/tests -q
npm --prefix litblogs run test:run
npm --prefix litblogs run lint
npm --prefix litblogs run build
python -m ruff check litblogs
python scripts/run-backend-bandit.py
```

## Production deployment

Do not deploy a Git branch, a developer checkout, or locally assembled files. Production releases must come from the reviewed, attested artifact produced by the `Build reviewed release artifact` GitHub Actions workflow.

- [Deployment layout and prerequisites](deploy/README.md)
- [Production deployment, migration, backup, restore, rollback, and incident runbook](docs/operations/production-runbook.md)

The deployment design keeps private uploads outside the source tree, runs the API only on loopback behind TLS-terminating Nginx, applies schema changes through Alembic, installs hash-locked dependencies, and uses hardened systemd units. A release remains blocked until the runbook's backup/restore rehearsal, migration checks, legacy federated-identity mapping, security gates, and smoke tests all pass.

## Security

Please report vulnerabilities privately using the process in [SECURITY.md](SECURITY.md). Never commit credentials, student data, production database copies, upload files, or environment files.

## Contribution workflow

All changes go through short-lived branches and reviewed pull requests. See [CONTRIBUTING.md](CONTRIBUTING.md) for required checks and repository workflow.
