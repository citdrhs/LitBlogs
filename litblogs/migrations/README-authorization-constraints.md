# Authorization constraint migration runbook

Apply `0002_add_authorization_constraints.sql` during a maintenance window after
`0001_create_federated_identities.sql`. The script is transactional, but its unique
indexes intentionally fail closed when legacy duplicate enrollments or submissions
exist. Do not delete or merge student work automatically.

## Preflight

1. Stop application writes and take a verified, restorable database backup.
2. Inventory duplicate enrollments:

   ```sql
   SELECT student_id, class_id, COUNT(*) AS duplicate_count,
          ARRAY_AGG(id ORDER BY enrolled_at, id) AS enrollment_ids
   FROM class_enrollments
   GROUP BY student_id, class_id
   HAVING COUNT(*) > 1;
   ```

3. Inventory duplicate submissions:

   ```sql
   SELECT assignment_id, student_id, COUNT(*) AS duplicate_count,
          ARRAY_AGG(id ORDER BY submitted_at, id) AS submission_ids
   FROM assignment_submissions
   GROUP BY assignment_id, student_id
   HAVING COUNT(*) > 1;
   ```

4. Inventory users with multiple password-reset records:

   ```sql
   SELECT user_id, COUNT(*) AS duplicate_count,
          ARRAY_AGG(id ORDER BY created_at DESC, id DESC) AS reset_ids
   FROM password_resets
   GROUP BY user_id
   HAVING COUNT(*) > 1;
   ```

5. If any query returns rows, stop. Have the owning teacher review duplicate student
   work. A school administrator may invalidate all duplicate reset links before
   retaining only the newest reset record; never retain multiple usable reset tokens.
   For enrollment or submission duplicates, have the owning teacher review every version,
   export the originals, and choose the canonical record. Preserve non-canonical
   content in an approved school record before a reviewed reconciliation transaction.

## Apply and validate

Run the script with PostgreSQL configured to stop on the first error:

```sh
psql --set ON_ERROR_STOP=on "$DATABASE_URL" --file migrations/0002_add_authorization_constraints.sql
```

Then verify the new column and indexes:

```sql
SELECT column_name, data_type
FROM information_schema.columns
WHERE table_name = 'class_enrollments' AND column_name = 'notes';

SELECT indexname, indexdef
FROM pg_indexes
WHERE indexname IN (
    'uq_class_enrollments_student_class',
    'uq_assignment_submissions_assignment_student',
    'uq_password_resets_user'
)
ORDER BY indexname;
```

Re-run all duplicate inventories and require zero rows. Exercise one teacher roster,
one notes update, one student class join, one assignment submission, and one queued
password-reset delivery using non-production accounts before restoring traffic. Confirm
the reset endpoint returns before SMTP delivery and only a successfully delivered token
can change a password.

## Abort and rollback

Any statement failure rolls back the transaction. Keep the application stopped,
capture the database error, and reconcile the underlying data rather than weakening a
constraint. If rollback is required after traffic resumes, restore the verified backup
and reconcile writes made after that backup; do not drop the unique indexes on a live
system as an emergency workaround.
