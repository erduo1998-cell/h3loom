# Security

Do not put credentials, user inputs, generated media, model weights, or live task
receipts in an issue or pull request. Keep local task data in `work/`, `outputs/`,
and `secrets/`; these directories are ignored by Git.

ComfyUI listens on `127.0.0.1:8188` and is accessed over SSH. Do not expose that
port directly to the public internet. This project is a single-user workflow,
not a hosted multi-tenant video service.

For a suspected vulnerability, use GitHub's private vulnerability reporting if
enabled, or contact the maintainer privately through the contact shown in the
README. Describe the affected version and a minimal synthetic reproduction;
never attach actual passwords, tokens, private keys, or real user tasks.

Uncertain submissions are preserved for recovery. Do not delete reservations
or retry a paid request merely because a connection failed.
