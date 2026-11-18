# Development and production rollout

## Current state

This repository contains a static browser prototype. It can display selected filenames locally; it has no upload API, no server-side storage, no email notification, and no linked blank form. The submit button is disabled. Do not use it for real documents.

## Environment flow

- `dev` is for staging changes and testing with dummy files only.
- `main` is the production release branch. Deploy production from a reviewed commit after the operational gates below are complete.
- Keep development and production configuration, storage paths, credentials, logs, and backups separate.
- Never put uploads, PDFs, credentials, or patient information in this repository or its build output.

## Production gates

Before enabling submission, the server owner must configure and verify:

1. TLS on the public host and an HTTPS redirect; only the reverse proxy is internet-facing.
2. A server-side upload endpoint with explicit file-size/type limits, generated storage names, access controls, abuse limits, and safe error handling.
3. Private storage outside the web root with restricted service-account permissions, encryption and backup/restore procedures.
4. An approved authentication/access model for staff and submitters.
5. A generic email alert that contains no document, patient details, or filenames.
6. Retention/deletion rules, access logging, monitoring, and a restore check.
7. The correct blank form and approved logo files.
8. A reviewed end-to-end staging run with dummy documents, followed by an explicit production release.

This checklist is an engineering handoff, not a compliance certification. Do not accept real or sensitive documents until the organization responsible for the service approves the hosting and handling arrangements.

## Deploy coordination

The server operator should record the staging URL, production URL, deployment user/service, and rollback commit in the team's operations notes. Keep production deployments reversible by pinning each release to a Git commit.
