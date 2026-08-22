# Upload asset registry migration reference

Revision `b983b7aebe7b` is the authoritative upload-registry migration in the reviewed
single-head Alembic chain. `0005_upload_asset_registry.sql` is retained only as a
semantic reference. It is not an Alembic migration; do not execute or ship it as a
parallel migration path. Exercise
the Alembic upgrade and rollback against a disposable PostgreSQL database and retain
the independent review evidence before applying it.

Legacy files are intentionally unavailable at runtime until they have a registry row. Migration is a maintenance-window operation:

1. Stop writes, take and verify database and upload-root backups, and inventory every legacy object plus every database reference.
2. Run `upload_legacy_inventory.inventory_legacy_uploads` with the operator-built binding manifest. Abort the entire import if any object is unmapped, maps to multiple blogs, has ambiguous ownership, has an unsupported or mismatched signature, is empty, or has a missing database target.
3. Verify every referenced user and blog still exists and that each blog belongs to the owner/class asserted by the manifest. The inventory helper validates filesystem facts; it does not replace these database checks.
4. Rescan each object with the configured production scanner, copy it to a staged opaque `objects/<prefix>/<uuid>.<ext>` key, verify size and SHA-256, and insert the matching `ACTIVE` registry row. Profile and cover rows require the partial uniqueness invariant; post rows derive their class only from `blog_id`.
5. Compare source count, staged-object count, registry count, aggregate bytes, and digest sets. Abort and remove the staged copies on any mismatch. Do not enable the new release with a partial manifest.
6. Atomically switch stored profile/cover and post references to canonical `/api/uploads/objects/...` URLs, then enable the release. Keep the old root read-only for the approved rollback window; the application never serves an unmapped legacy path.

This reference deliberately does not provide a permissive best-effort importer. Silent skipping would turn private school files into untracked objects and defeat the deny-by-default runtime boundary.

Production startup never calls ORM `create_all`. It verifies the externally migrated registry shape and also requires all three operator assertions below. Leave them false until their named gate has completed; setting them does not substitute for the evidence:

- `UPLOAD_REGISTRY_SCHEMA_READY=true` only after revision `b983b7aebe7b` and the final head have been exercised on disposable PostgreSQL.
- `UPLOAD_LEGACY_IMPORT_COMPLETE=true` only after the fail-closed inventory/import and count/digest comparison succeeds, including the valid empty-inventory case.
- `UPLOAD_BACKUP_RESTORE_VERIFIED=true` only after the coupled restore rehearsal described below succeeds.

## Runtime storage and scanner prerequisites

Production must provision the upload root before application startup (the deployment target is `/var/lib/litblogs/uploads`). Every existing ancestor must be root- or service-owned and not group/world writable; the root itself must be a real, non-symlink directory owned and writable by the service identity. The application creates only its private `objects` and `.incoming` children and fails closed if the configured root or those children lose custody.

Production scanning is mandatory. Configure `UPLOAD_SCANNER_HOST` to an explicitly allowlisted local/private ClamD service, keep the bounded scanner timeout, and verify the startup preflight before accepting traffic. A missing, unreachable, rejecting, or malformed scanner response blocks activation or the individual upload; the no-op scanner is development/test-only.

The application admits at most 20 upload attempts per authenticated user in five minutes per process and at most four concurrent staging/scanner jobs per process, before any body is staged. The database-locked registry check remains authoritative for the separate contract of 20 successful uploads in five minutes and the 1 GiB quota. A multi-worker deployment must also enforce equivalent authenticated-user/IP request and concurrency limits at the trusted ingress; process-local admission is defense in depth, not a cluster-wide counter.

Scanned data is fsynced in private `.incoming` storage, atomically renamed to a private opaque shard, and fsynced again before the registry transaction commits. A final object is request-immutable: an exception path never unlinks it. If COMMIT acknowledgement is lost, a fresh database session verifies the complete registry metadata, parent pointer (for profile/cover), size, digest, and final file before returning success. Otherwise the API returns a retryable 503 without a URL and reconciliation owns cleanup.

Reconciliation repairs a matching committed row from intact staged data, keeps missing/corrupt ACTIVE rows fail-closed for snapshot restoration, and removes unregistered staging/final objects only after a 24-hour grace period and an immediate registry recheck. Upload registry transactions set PostgreSQL lock, statement, and idle-in-transaction timeouts to at most 30 seconds, well below that grace period. Alert on missing/corrupt ACTIVE objects; never silently tombstone them.

## Backup and restore deployment gate

A database backup alone is not a complete upload backup. Treat the absence of a coupled, point-in-time upload-store snapshot as a **hard deployment blocker**. Before enabling this release, capture the database and upload root together, and produce an immutable manifest containing each registry row's `storage_key`, `state`, `size_bytes`, and `sha256_digest` plus the snapshot identifiers that tie both copies to the same maintenance window.

Complete a restore rehearsal into an isolated database and upload root before rollout. The rehearsal must prove that every ACTIVE registry row resolves beneath the restored upload root and that the restored object has exactly the registered `size_bytes` and `sha256_digest`. Missing, extra, path-escaping, size-mismatched, or digest-mismatched objects fail the rehearsal and block deployment. The registry adds authorization and lifecycle metadata; it does not make database-only backup or restore complete.
