# Security Policy

## Scope

`hindsight` processes private local activity logs, transcripts, prompts, and summary outputs. Security and privacy bugs are therefore in scope even when they do not look like classic remote code execution vulnerabilities.

Examples that should be reported privately:

- unintended transmission of local transcripts, prompts, or metadata
- missing or incorrect redaction before LLM calls
- unsafe default filesystem permissions for the data directory or SQLite store
- command injection, path traversal, or arbitrary file overwrite in CLI/export/schedule flows
- secrets exposed in logs, exports, or error messages

## Supported versions

Until formal release maintenance starts, only the current default branch is treated as actively supported for security fixes.

## Reporting a vulnerability

Do not open a public GitHub issue for suspected security or privacy problems.

Use GitHub's private vulnerability reporting flow if it is enabled for the repository. If it is not available, contact the maintainer privately through the contact method listed on GitHub and share only the minimum detail needed to reproduce the issue.

Please include:

- affected command(s) and flags
- platform and Python version
- whether the issue affects collection, summarization, export, or scheduling
- a redacted reproduction or proof of concept
- impact assessment, especially whether local transcripts or credentials can leak

## Response expectations

- initial acknowledgment target: within 7 days
- status update target: within 14 days if the issue is confirmed
- coordinated disclosure after a fix is available or a mitigation is documented

## Handling sensitive data in reports

- never paste real API keys, tokens, cookies, or private transcripts into a public issue
- prefer minimal synthetic fixtures over real activity logs
- if you must share a digest snippet, redact people, hosts, project names, and credentials first
