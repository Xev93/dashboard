# Security Policy

## Reporting a Vulnerability

If you discover a security vulnerability in this project, please report it responsibly.

**Email:** Open a GitHub issue with the label `security` (this is a personal project with no sensitive user data).

## Scope

This is a local terminal application that fetches public data from academic APIs and news aggregators. It:
- Does not handle authentication or user accounts
- Does not store or transmit sensitive data
- Uses SQLite for local caching only
- Makes outbound HTTP requests only to public APIs

## Dependencies

Dependencies are locked via `uv.lock` with integrity hashes. Run `pip-audit` to check for known vulnerabilities.
