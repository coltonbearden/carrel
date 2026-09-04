# Security policy

## Supported versions

Only the latest release on PyPI (`pip install carrel`) receives fixes. Older
versions are not patched — upgrade first, then re-test.

## Reporting a vulnerability

Please **do not open a public issue** for security problems.

Use GitHub's private vulnerability reporting for this repository:
<https://github.com/coltonbearden/carrel/security/advisories/new>. It opens a
private draft advisory that only the maintainer can see. You will get an
acknowledgement within 7 days and a fix or a documented decision within 30.

What helps: the carrel version (`carrel --version`), the command and flags,
a minimal input file that reproduces the problem, and what you expected to
happen instead.

## What counts

carrel is a local file toolkit that shells out to external binaries through
one adapter layer (`src/carrel/core/adapters.py`). Reports we care about most:

- path traversal or writes outside the requested output location,
- command injection through file names or user-supplied patterns
  (`watch --run` deliberately runs the user's own shell template — that is
  not a vulnerability, but a substituted value escaping its quoting would be),
- the MCP server (`carrel mcp`) reading or writing outside its root,
- redaction (`carrel redact`) leaving matched data behind.

## Supply chain

Releases are built and published by GitHub Actions via PyPI Trusted
Publishing (OIDC, no long-lived tokens), with PEP 740 attestations. All
workflow actions are pinned to commit SHAs and updated by Dependabot.
