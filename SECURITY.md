# Security Policy

## Supported versions

The latest LitBlog release and the current `main` branch receive security fixes. Unsupported deployments should be upgraded before requesting a patch.

## Report vulnerabilities privately

Do not open a public issue. Submit a [private repository security advisory](https://github.com/Antigro09/LitBlog/security/advisories/new) so the maintainers can investigate without exposing students, teachers, systems, or credentials.

Include a concise description, affected feature, sanitized reproduction steps, likely impact, and the version or commit tested. Use synthetic accounts and values. Do not attach logs, database exports, screenshots, or requests containing personally identifiable information (PII). If a minimal redacted excerpt is essential, remove names, email addresses, school identifiers, tokens, cookies, hostnames, and other identifying values first.

Report issues such as:

- authentication or authorization bypasses;
- cross-user exposure of student, teacher, or administrator data;
- injection, cross-site scripting, unsafe file/media handling, or request forgery;
- exposed secrets, tokens, private keys, or production configuration; and
- security control or deployment misconfiguration.

## Suspected credential exposure or incident

Treat a suspected disclosure as an incident. Stop using and sharing the affected value, preserve only sanitized evidence, notify the maintainers through the private advisory, and rotate or revoke the credential through its issuing system. Removing a value from Git does not invalidate it. Maintainers should review access logs through an approved private channel, assess affected data and users, document containment and recovery, and follow applicable school or organizational incident procedures.

## Responsible disclosure

Allow reasonable time for triage, remediation, credential rotation, and coordinated notification before public disclosure. The maintainers will use the private advisory to acknowledge the report and coordinate next steps.
