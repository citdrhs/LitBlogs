# Superseded federated-identity migration note

This file is retained as development history only. The former raw SQL migration
procedure is superseded and must not be used for a production or rehearsal rollout.
Do not execute `0001_create_federated_identities.sql`.

The only production operator instructions are in
`docs/operations/production-runbook.md`. Follow its verified Alembic baseline
adoption, migration, identity-mapping, restore-rehearsal, and abort gates exactly.
Never combine the historical raw SQL script with the Alembic identity revision.

The production runbook's preflight treats any incomplete legacy identity mapping
as a deployment blocker. Never perform an automatic email backfill. Every legacy
OAuth account instead needs a School-IT-approved provider subject or a supervised
authenticated account-link ceremony. Abort and keep the application disabled if
that evidence, the signed inventory, or a safe rollback point is missing.

For historical search context only, old drafts mentioned
`LEFT JOIN federated_identities`; that text is not an executable reconciliation
instruction. The reviewed runbook is the sole authority for cutover and rollback.
