#!/usr/bin/env bash
# One-time local repository setup for the Alpha release.
#
# Creates the git history in meaningful, reviewable commits, sets the remote,
# and creates the `develop` branch. It does NOT push -- the push command is
# printed at the end so you can review the history first.
#
# Run once, from the repository root:
#     bash scripts/git_setup.sh

set -euo pipefail

REMOTE_URL="${REMOTE_URL:-git@github.com:ryang18237/CMSC-495.git}"

if [ ! -f README.md ] || [ ! -d backend ]; then
  echo "Run this from the repository root (the folder containing README.md and backend/)." >&2
  exit 1
fi

if [ -d .git ]; then
  echo "A .git directory already exists. Remove it first if you intend to rebuild the history." >&2
  exit 1
fi

command -v git >/dev/null || { echo "git is not installed." >&2; exit 1; }

git config --global user.name  >/dev/null 2>&1 || {
  echo "Set your identity first:" >&2
  echo '  git config --global user.name "Ryan Gant"' >&2
  echo '  git config --global user.email "you@example.com"' >&2
  exit 1
}

git init -b main

commit() {
  local message="$1"
  shift
  git add -- "$@"
  git commit -q -m "$message"
  printf '  %s\n' "$message"
}

echo "Building commit history:"

commit "chore: initialize repository with tooling configuration and ignore rules" \
  .gitignore backend/ruff.toml backend/mypy.ini backend/pytest.ini \
  backend/requirements.txt backend/requirements-dev.txt backend/.env.example \
  .github/pull_request_template.md

commit "feat(api): define request/response contracts and the shared error contract" \
  backend/app/__init__.py backend/app/config.py backend/app/schemas.py backend/app/errors.py

commit "feat(data): add data model with an adapter-isolated legacy customer table" \
  backend/app/db.py backend/app/models.py

commit "feat(auth): add JWT authentication, role checks and synthetic seed data" \
  backend/app/security.py backend/app/rate_limit.py backend/app/bootstrap.py

commit "feat(modules): add customer data adapter and knowledge base service" \
  backend/app/modules/__init__.py backend/app/modules/customer_data backend/app/modules/knowledge

commit "feat(ai): isolate the model behind a provider interface with a mock provider" \
  backend/app/modules/ai_integration

commit "feat(escalation): add deterministic escalation rules and response validation" \
  backend/app/modules/validation backend/app/modules/escalation

commit "feat(conversation): orchestrate a customer turn across the core modules" \
  backend/app/modules/conversation

commit "feat(api): expose the v1 conversation, escalation, feedback and agent endpoints" \
  backend/app/api backend/app/main.py

commit "feat(analytics): record feedback to an outbox and aggregate it for human review" \
  backend/app/modules/feedback backend/app/modules/analytics

commit "test: cover every endpoint, authorization rule and escalation path" \
  backend/tests

commit "feat(web): add the React customer chat and human agent dashboard" \
  frontend

commit "ci: run lint, types, tests on PostgreSQL and an end-to-end smoke test" \
  .github/workflows scripts

commit "docs: document the API, architecture, security practices and AI handoff" \
  README.md docs

# Anything not matched above (there should be nothing).
if [ -n "$(git status --porcelain)" ]; then
  git add -A
  git commit -q -m "chore: add remaining project files"
  echo "  chore: add remaining project files"
fi

git branch develop
git remote add origin "$REMOTE_URL"

echo
echo "History created:"
git --no-pager log --oneline
echo
echo "Remote set to: $REMOTE_URL"
echo
echo "Review the history above, then push:"
echo "    git push -u origin main"
echo "    git push -u origin develop"
