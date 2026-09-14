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

- **Development runs generate one for you.** With `ENVIRONMENT=development` and
  no `JWT_SECRET` set, the application writes a random secret to
  `backend/.jwt_secret` (git-ignored) and reuses it, so tokens survive a
  reload. It never leaves your machine. Any deployment and CI must set
  `JWT_SECRET` explicitly — the generated file is a local convenience, not a
  key-management strategy.

- **API keys go in your local `.env` or a GitHub Actions secret**, never in
  code, never in a test fixture, never in a commit message.
- CI runs with `AI_PROVIDER=mock` and needs no model credentials.
- If a secret is ever committed, rotate it first and rewrite history second —
  rotation is what actually protects you, because the value is already on
  someone's machine.

## API keys in a shared private repository

**A key in `.env` is private to your own machine. A key committed to the
repository is visible to every collaborator, permanently.**

`backend/.env` is git-ignored, so a key placed there never leaves your laptop.
That is the correct place for it. What does *not* work is trying to share one
key through the repository — there is no way to commit a value that some
collaborators can read and others cannot. Private means private *from the
public*, not private *between the three of us*.

So: **each team member uses their own API key from their own account.** Get one
at <https://console.anthropic.com>, put it in your own `backend/.env`, and set
a spend limit on your account while developing. If a key does leak, only one
person's account is affected and only one key needs rotating.

If the team genuinely needs one shared key — for a recorded demonstration, say —
the options are:

- **Run the demo on one machine.** Simplest and safest. Whoever owns the key
  runs it; nobody else needs a copy.
- **A GitHub Actions secret.** Correct for automation, but understand the
  limit: anyone with write access can add a workflow that prints or exfiltrates
  the secret. It protects against outsiders, not against collaborators.
- **A password manager with a shared vault.** Fine for people, never for a
  repository.

Whatever you choose, never paste a key into a commit message, a pull request
description, a test fixture, a screenshot, a Slack or Discord message, or a
submitted document. Anthropic keys are recognisable (`sk-ant-...`) and are
scanned for automatically once they reach a public surface.

**If a key is exposed, rotate it first.** Revoke it in the Anthropic console,
then worry about the git history. Rewriting history does not help — the value
is already in someone's clone, and a revoked key is worthless to whoever has
it.

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
