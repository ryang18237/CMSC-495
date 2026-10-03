# CI screenshots

Referenced by [`docs/CI_CD.md`](../../CI_CD.md). Save each capture here with
exactly this name so the document picks it up.

| File | What to capture |
| --- | --- |
| `01-workflow-runs.png` | Actions → CI, the list of recent runs on `main`, all green |
| `02-job-graph.png` | One run on `main`: backend and frontend → integration → delivery |
| `03-backend-job.png` | Backend job, contract check and the pytest `passed` line expanded |
| `04-integration-smoke-test.png` | Integration job, smoke-test step ending in `Smoke test passed.` |
| `05-delivery-artifact.png` | Run summary page: release table plus the `skillbridge-1.0.0-…` artifact |
| `06-pull-request-checks.png` | A merged pull request showing "All checks have passed" |
