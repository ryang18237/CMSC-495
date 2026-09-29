# Code Review Record

**Owner:** Ravonne Wade (Lead Architect)

Every change reached `main` through a pull request with CI green. This record
lists the reviews, what each one found, and what happened to every finding —
including the ones still open.

## How code is reviewed

| Layer | What checks it | When |
| --- | --- | --- |
| Automated review | ruff, mypy, ESLint, API contract tests, architecture boundary tests, complexity limit, coverage floors, OpenAPI drift check, module-graph drift check, end-to-end smoke test, performance benchmark | Every push and pull request (`.github/workflows/ci.yml`) |
| Peer review | A teammate reads the change against their own area of ownership | Each feature branch |
| Refinement review | Each member reviews another's contribution and records improvements | Unit 5 |
| Integration review | The merged system is checked as a whole before release | Final release |

Pull requests use `.github/pull_request_template.md`: modules touched,
interface impact, a checklist (CI green, tests added, no secrets, descriptive
commits) and verification output.

## Pull requests merged

| PR | Branch | Owner | Content |
| --- | --- | --- | --- |
| #1, #3 | `feature/alpha-skillbridge-platform` | Ryan Gant | Alpha platform: API, contracts, client, SkillBridge re-theme, cache, monitoring, one-command setup |
| #4 | `Ravonne_Assignment_5-patch-1` | Ravonne Wade | Architecture design document, boundary tests, module-graph generator, ADRs |
| #5 | `feature/agent-escalation-path` | Benjamin Madden | Anthropic provider, human escalation path, counsellor replies |
| — | `feature/final-interface` | Ryan Gant | Final interface: contract tests, OpenAPI export, CI delivery |
| — | `feature/ai-recommendations` | Benjamin Madden | Pathway recommender, peer-review fixes |
| — | `feature/docs-and-metrics` | Ravonne Wade | Documentation, coverage, benchmarks, quality metrics |

---

## 1. Peer review — AI Integration Module

Ryan Gant (Interface Designer) reviewing Benjamin Madden (Integration Lead).
Full text: [`../PEER_REVIEW_AI_Integration_Module.md`](../PEER_REVIEW_AI_Integration_Module.md).

| Finding | Severity | Status |
| --- | --- | --- |
| Worst-case turn ≈ 61 s against a 5 s target | High | **Fixed** — 8 s timeout, one retry, 5 s retry budget; worst case ≈ 13 s |
| Provider error text could carry content into logs | Medium | **Fixed** — capped at 200 characters, invariant documented |
| Truncated answers escalated as `AI_SERVICE_FAILURE` | Medium | **Fixed** — now `VALIDATION_FAILURE`, no enumeration change |
| `time.sleep` in retries holds a worker thread | Medium | **Open** — needs async routes; in the architecture debt register |
| Handoff document described a stub | Medium | **Fixed** — replaced by `docs/AI_FEATURES.md` |
| Data sent to the provider not listed in one place | Medium | **Fixed** — `AI_FEATURES.md`, "What leaves the platform" |
| Model alias, key rotation and rate limits undocumented | Medium | **Fixed** — documented |
| No test that the key never reaches a log | Low | **Fixed** — test added |
| `MAX_TOKENS` silently coupled to `max_response_length` | Low | **Fixed** — commented at both sites |
| Shared connection pool never closed | Low | **Fixed** — closed on shutdown |

## 2. Refinement review — architecture enforcement

Benjamin Madden reviewing Ravonne Wade's architecture documentation and
boundary tests (Unit 5).

| Recommendation | Status |
| --- | --- |
| Move cache and rate-limit state to shared infrastructure | **Open** — in the debt register; requires a managed cache |
| Asynchronous provider handling | **Open** — as above |
| Representative load testing | **Partly done** — single-instance HTTP benchmark added to CI (`BENCHMARKS.md`); multi-instance capacity not demonstrated |
| Expand production monitoring | **Open** — counters are still per instance |
| Keep ADR review for boundary changes | **Done** — the recommender added a new dependency and came with ADR 0006 |

## 3. Refinement review — AI integration

Ryan Gant reviewing Benjamin Madden's merged work (Unit 5).

| Recommendation | Status |
| --- | --- |
| Guard the shared HTTP client with a lock | **Fixed** — a 20-thread test creates 20 pools without it and one with it |
| Move `AgentReplyRequest` into the shared schema module | **Fixed** |
| Give truncation an accurate escalation reason | **Fixed** — `VALIDATION_FAILURE` |
| Load test the provider path | **Partly done** — measured with the mock provider; the real provider was not load tested (cost) |

## 4. Integration review — final release

Problems found by checking the merged system as a whole. Several were caught
by an automated check the moment it was switched on, which is the argument for
having the checks.

| Finding | How it was found | Resolution |
| --- | --- | --- |
| PR #4 uploaded its files under a top-level `Ravonne/` folder, so the sixteen boundary tests never ran and the design documents were not in `docs/` | The backend test count was 134 after all three merges, not the 150 the three branches added up to | Files moved to their real paths; CI now runs the tests and the module-graph check |
| `main.py` imported an AI provider directly, bypassing the module's entry point | Boundary test `test_no_provider_is_imported_outside_the_ai_module`, as soon as it ran | Shutdown now goes through `ai_integration.service.shutdown()` |
| The four counsellor-reply endpoints were not in `docs/API.md` | Manual review; now enforced by `test_every_route_is_documented` | Documented; the recommender endpoint was then caught by the same test before it was documented |
| An empty reply returned `INVALID_REQUEST` and a blank one `INVALID_REPLY` | Reading the contract against the code | One rule, one code: all bad replies return `INVALID_REPLY`, pinned by a test |
| `/agent/workload` had no response schema, so it was untyped in OpenAPI | Generating `docs/openapi.json` | `AgentWorkloadResponse` added |
| Routers imported a private helper from each other | Reading the imports | Shared projections moved to `api/v1/views.py` |
| `recommend()` had cyclomatic complexity 29 | `scripts/quality_report.py` | Split into four helpers; output verified identical; CI limit set at 15 |
| Frontend coverage 44.9%, counsellor screens untested | First coverage measurement | 19 tests added; 89.4% |
| Sign-in p95 near the target at 25 concurrent clients | Benchmark | Recorded in the debt register with its cause (bcrypt cost on 2 CPUs) |
| README's Windows prerequisites section cut off by a merge | Reading the rendered README | Rewritten; full setup moved to `docs/INSTALL.md` |

## Open items carried forward

Consolidated from the tables above and the architecture design's section 10.

1. Asynchronous provider and routes, so a slow model call does not hold a worker thread.
2. Cache and rate-limit counters in shared infrastructure, so instances are truly stateless.
3. Monitoring exported to a real backend, with alerting.
4. Multi-instance load test against the 10,000-user requirement.
5. Handling for a member in distress, designed before any real use.
