# Maintainability Metrics

**Owner:** Ravonne Wade (Lead Architect)

Measured with [radon](https://radon.readthedocs.io/) over every Python file in
`backend/app`, grouped by the components of the architecture design. The table
between the markers is generated — run `python scripts/quality_report.py --write`
to refresh it. CI runs `python scripts/quality_report.py --max-cc 15` on every
push and fails if any function's cyclomatic complexity exceeds 15.

## How to read it

- **SLOC** — source lines, excluding comments and blank lines. The codebase is
  heavily commented, so SLOC is roughly half the physical line count.
- **Cyclomatic complexity (CC)** — independent paths through a function.
  A = 1–5, B = 6–10, C = 11–20, D = 21–30, E = 31–40, F = 41+. A and B are
  simple enough to test every branch.
- **Maintainability index (MI)** — a 0–100 blend of complexity, size and
  Halstead volume. Radon grades 20 and above as A. Comments raise it, which is
  why the API layer — thin routers with long docstrings — scores highest.

## Results

<!-- quality-report:start -->
| Component | Files | SLOC | Functions | Mean CC | Worst CC | Mean MI |
| --- | ---: | ---: | ---: | ---: | ---: | ---: |
| Conversation Management | 1 | 187 | 10 | 3.10 | 8 (B) | 59.1 |
| Customer Data Adapter | 1 | 189 | 10 | 4.90 | 13 (C) | 58.0 |
| Knowledge Base | 1 | 86 | 7 | 3.29 | 6 (B) | 60.4 |
| AI Integration | 6 | 585 | 59 | 3.41 | 11 (C) | 69.3 |
| Response Validation | 1 | 80 | 6 | 5.00 | 10 (B) | 64.7 |
| Escalation | 3 | 246 | 19 | 2.53 | 7 (B) | 75.6 |
| Feedback | 1 | 81 | 5 | 2.40 | 6 (B) | 66.4 |
| Learning Analytics Worker | 1 | 161 | 13 | 2.69 | 5 (A) | 50.0 |
| Cache | 1 | 92 | 24 | 1.62 | 4 (A) | 56.9 |
| Monitoring | 1 | 70 | 9 | 1.89 | 3 (A) | 67.2 |
| API layer | 9 | 475 | 24 | 1.96 | 5 (A) | 89.9 |
| Shared (config, schemas, errors, security, data) | 9 | 830 | 95 | 1.56 | 10 (B) | 72.4 |
| **Total** | 35 | 3082 | 281 | 2.42 | 13 | 73.9 |

**Cyclomatic complexity grades, all functions:** A: 258 · B: 20 · C: 3 · D: 0 · E: 0 · F: 0

**Maintainability index grades, all files:** A: 35 · B: 0 · C: 0

**Most complex functions**

| CC | Function |
| ---: | --- |
| 13 (C) | `backend/app/modules/customer_data/adapter.py::CustomerContext` |
| 12 (C) | `backend/app/modules/customer_data/adapter.py::CustomerContext.to_prompt_facts` |
| 11 (C) | `backend/app/modules/ai_integration/service.py::AIIntegrationService.generate_response` |
| 10 (B) | `backend/app/modules/validation/service.py::ResponseValidationService.validate_response` |
| 10 (B) | `backend/app/modules/ai_integration/recommender.py::_matched_terms` |
| 10 (B) | `backend/app/modules/ai_integration/providers/anthropic_provider.py::AnthropicProvider._parse` |
| 10 (B) | `backend/app/bootstrap.py::seed` |
| 9 (B) | `backend/app/modules/validation/service.py::ResponseValidationService` |
<!-- quality-report:end -->

## What the numbers say

**Complexity sits where the design puts the work.** The two components the
architecture expects to be intricate — AI Integration (prompting, provider
failure mapping, the recommender) and the Customer Data Adapter (translating
and minimising the legacy record) — hold the highest-complexity functions. The
components the design says must stay simple do: Cache, Monitoring and the
Escalation rules are all grade A on average, and the API layer's routers
average under 2.

**Every file is grade A for maintainability.** No file falls below MI 20.

**The limit caught a real problem before merge.** The first version of the
pathway recommender scored **CC 29 (grade D)** in a single `recommend()`
function — vectorising the member, scoring, explaining and ranking in one
loop. The report flagged it during integration review; it was split into four
named helpers, each grade A or B, and the evaluation output for every labelled
profile was confirmed byte-for-byte identical before and after. That is why the
CI limit is 15: it is below where that function started.

**Remaining C-grade code, and why it is left.** `CustomerContext.to_prompt_facts`
is one `if` per permitted field — long, but flat and fully covered by tests;
splitting it would scatter the single list that decides what reaches the model.
`AIIntegrationService.generate_response` carries the retry loop with its
budget check; its branches are each pinned by a test.

## Static analysis

| Tool | Scope | Result |
| --- | --- | --- |
| ruff (lint, rules E, F, I, B, UP, C4) | `backend/` | 0 findings |
| ruff format | `backend/` | 0 files to reformat |
| mypy (`check_untyped_defs`, `strict_equality`) | `backend/app`, 50 files | 0 errors |
| ESLint 9, including Allman brace style | `frontend/` | 0 findings |
| actionlint | `.github/workflows/ci.yml` | 0 findings |

All five run in CI; a finding fails the build.
