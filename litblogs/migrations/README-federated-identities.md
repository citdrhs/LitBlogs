# Federated identity migration runbook

Treat unresolved legacy OAuth accounts as a deployment blocker. The application now
authenticates a provider account by its verified provider, issuer or tenant, and
subject. A legacy account has no trustworthy subject stored in the database, so this
migration must never infer or backfill a binding from an email address.

## Preflight

1. Take and verify a restorable database backup. Record the application revision and
   user count.
2. Run this read-only legacy user inventory before the new table exists. It is a
   superset: local-password users also appear here, so a row is not evidence that the
   account previously used OAuth.

   ```sql
   SELECT id, email, created_at
   FROM users
   ORDER BY id;
   ```

3. Identify actual legacy federated accounts using an approved institutional record,
   not an email match. Confirm that every proposed binding has the expected provider,
   exact issuer or Microsoft tenant, stable provider subject, and local user ID.
4. Check the proposed mapping for duplicates on both `(provider, issuer, subject)` and
   `(provider, user_id)`. Abort the rollout if any mapping is missing, ambiguous, or
   duplicated.

## Approved recovery options

- Add an authenticated account-link flow after local credential recovery. The user
  must first authenticate the existing LitBlog account, then reauthenticate the
  provider with a verified ID token and explicitly confirm the link. Task 3 does not
  implement this flow.
- Obtain a school-IT provider subject export and perform an operator mapping. Reconcile
  it with a stable institutional identifier, require two-person review, and insert the
  reviewed bindings in one transaction. Do not use the provider email as the identity
  key.

If neither option is available for every affected OAuth-only account, stop before
deployment and keep the previous application revision active.

## Apply and validate in maintenance

Disable the application and authentication traffic. Apply
`0001_create_federated_identities.sql` with `ON_ERROR_STOP` enabled, then inventory
accounts that do not yet have a binding:

```sql
SELECT u.id, u.email, u.created_at
FROM users AS u
LEFT JOIN federated_identities AS f ON f.user_id = u.id
WHERE f.id IS NULL
ORDER BY u.id;
```

Load only an approved mapping, in a separate transaction, after the schema migration
succeeds. Validate that the two uniqueness rules hold, every mapped user still exists,
and the expected counts match the reviewed mapping. Keep the application disabled
until every affected OAuth-only account is mapped or has an approved recovery path.
Exercise login with a non-production test identity before routing production traffic
to the new revision.

## Abort and rollback

The schema script runs inside a transaction and rolls back automatically on an error.
For a preflight or mapping discrepancy, abort without enabling the new application.
If a post-deployment rollback is required, stop authentication traffic, restore the
previous application revision and the verified backup, and reconcile any bindings
created after the backup before retrying. Do not drop the table or silently remove
bindings from a live deployment.
