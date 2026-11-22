# Document exchange development prototype

The \`dev\` branch contains a browser page and a FastAPI upload service. Uploads are disabled unless the server operator explicitly configures HTTPS origin validation, Cloudflare Turnstile, SMTP, ClamAV, and private filesystem paths outside the web root.

The form shows selected filenames before submission. Uploaded files are assigned random server-side names, stored privately, scanned, and never served by a public download route. Email alerts contain only a random submission reference. This repository contains no blank form PDF, uploaded documents, credentials, or patient information.

See [DEPLOYMENT.md](DEPLOYMENT.md) before deploying. This software is not a compliance certification. Do not accept real health documents until the organization responsible for the service has approved the host, storage, access, and contractual arrangements.
