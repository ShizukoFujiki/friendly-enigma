# Development and production rollout

## Current state

The \`dev\` branch now has a FastAPI upload route and a browser form wired to it. The live hostname still serves the older static page from \`main\`; this branch has not been deployed. Uploads are disabled unless the operator explicitly configures the service. The correct blank form is not in this repository.

The upload endpoint accepts anonymous public submissions after Cloudflare Turnstile verification. It accepts PDF, JPG, and PNG by file signature, limits uploads to five files, 20 MB per file, and 25 MB total, rate-limits each client IP in memory, scans with ClamAV, and writes random-named files under a private directory outside the web root. SMTP notification references are stored in a private queue and retried while the service is running. It does not provide a public file retrieval route or staff dashboard. The staff workflow for retrieving files must be approved and protected on the host.

## Development setup

Use dummy documents only. Create a virtual environment in the checkout and install \`server/requirements.txt\`. Copy \`.env.example\` to a private environment file for local testing. Keep \`ENABLE_UPLOADS=0\` unless the test Turnstile, SMTP, and ClamAV configuration is available.

## Linux service deployment

1. Create a dedicated unprivileged account named \`sunriver-intake\`. Install the checkout under \`/opt/sunriver-intake\`.
2. Create \`/var/lib/sunriver-intake/submissions\` and \`/var/lib/sunriver-intake/tmp\`, owned by that account, mode \`0700\`. These paths must remain outside the code and public web roots.
3. Create \`/etc/sunriver-intake.env\` from \`.env.example\`; set owner root and mode \`0600\`. Fill in real Turnstile keys, SMTP STARTTLS settings, and the approved notification address. Keep this file and all secrets out of GitHub.
4. Install and start ClamAV; verify \`clamdscan\` works for the service account.
5. Install the virtual environment and dependencies, then install \`server/sunriver-intake.service.example\` as a systemd unit.
6. Configure the existing TLS reverse proxy to send this hostname to \`127.0.0.1:8787\`. Enforce a 26 MB request-body limit (25 MB of files plus multipart overhead), preserve the host, and pass the real client address only from this trusted proxy. Do not expose port 8787 directly.
7. Verify the filesystem or encrypted volume, staff access method, backup, restore, retention, and monitoring plan. The service stores files with restrictive Unix permissions but does not add application-level encryption.
8. Confirm the blank PDF is the correct approved shareable form and add it only to a public forms directory after review. Never publish a completed personal copy.
9. Test in the dev environment with dummy files. Confirm successful upload, rejection of invalid/oversized files, virus scan behavior, private filesystem permissions, and generic email delivery before a production release.

\`ENABLE_UPLOADS=1\` is effective only when HTTPS public origin, Turnstile, SMTP, and ClamAV are all configured. The page stays in preview mode if the upload service is not fully configured. Email alerts contain only a random submission reference, never filenames or attachments.

## Environments and release

- \`dev\` is for staging and dummy-file checks.
- \`main\` is production. Deploy a reviewed commit manually and record the commit for rollback.
- Keep dev and production credentials, storage, alerts, logs, and backups separate.
- Do not store uploaded documents, PDFs, credentials, or patient information in this public repository.

This engineering checklist is not a HIPAA compliance certification. Before accepting ePHI, the responsible organization must approve the full environment and complete its own risk and contractual review. HHS states that a cloud service provider that creates, receives, maintains, or transmits ePHI on behalf of a covered entity or business associate requires a HIPAA-compliant BAA and compliance with the HIPAA Rules: [HHS cloud computing FAQ](https://www.hhs.gov/hipaa/for-professionals/faq/may-a-hipaa-covered-entity-or-business-associate-use-cloud-service-to-store-or-process-ephi/index.html).
