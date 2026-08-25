# Assignment draft revision migration

Revision `f0684bf8ff2e` is the authoritative migration for the ORM change in
`models.AssignmentDraft`. `0004_assignment_draft_revisions.sql` is retained only as a
semantic reference; do not execute or ship it as a parallel migration path.

The migration keeps existing draft content, gives those rows revision `0`, and
makes draft content nullable so cleared drafts remain as revision tombstones.
The application locks the stable student user row before draft lookup/create,
then compares and advances this revision in the same transaction.

Preflight:

```sql
SELECT COUNT(*) FROM assignment_drafts;
SELECT COUNT(*) FROM assignment_drafts WHERE content IS NOT NULL;
```

Postflight:

```sql
SELECT COUNT(*) FROM assignment_drafts WHERE revision IS NULL;
SELECT MIN(revision), MAX(revision) FROM assignment_drafts;
```

Rollback requires first stopping application writers. Dropping `revision`
also removes stale-write protection, and tombstone rows must be deleted before
restoring `content NOT NULL`; do not roll this migration back while the revised
application is serving traffic.
