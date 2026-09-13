# Security practices for this repository

The repository is private, but several people have write access, so these rules
matter in practice.

## Secrets

- **Never commit a secret.** `.env`, `.env.*` (except `.env.example`), `*.pem`
  and `*.key` are git-ignored. `.env.example` holds placeholders only.
- **Generate your own JWT secret.** Do not share one in chat or in a document:

  ```bash
  python -c "import secrets; print(secrets.token_urlsafe(48))"
  ```

- **API keys go in your local `.env` or a GitHub Actions secret**, never in
  code, never in a test fixture, never in a commit message.
- CI runs with `AI_PROVIDER=mock` and needs no model credentials.
- If a secret is ever committed, rotate it first and rewrite history second —
  rotation is what actually protects you, because the value is already on
  someone's machine.

## Data

- All seed data is synthetic. Do not add real customer names, emails, order
  numbers or payment details to fixtures, screenshots or documentation.
- The Customer Data Adapter exposes only the fields an inquiry type needs, so
  prompts stay minimal by construction. Do not widen `_INQUIRY_FIELDS` without
  a reason.
- Security-sensitive messages and messages containing raw identifiers (SSN-like
  or card-like patterns) escalate before the model is called.
- Response validation rejects any answer containing those patterns, leaking
  internal instructions, or claiming an account action the assistant cannot
  perform.

## Access control

- Identity always comes from the verified token. No endpoint accepts a customer
  identifier from the client.
- Customers can reach only their own conversations (403 otherwise).
- Agent endpoints require the `AGENT` role (403 otherwise).
- Login returns the same message for an unknown address and a wrong password,
  so the endpoint does not disclose which accounts exist.

## Repository settings worth enabling

- Require a pull request before merging into `main`.
- Require the `backend`, `frontend` and `integration` checks to pass.
- Require at least one review from someone other than the author.
- Enable secret scanning and push protection (Settings → Code security).
- Keep collaborator access to the three team members plus the instructor.

## Reporting

Found something? Say so in the team channel and open a private issue. Do not
paste the credential itself into the issue.
