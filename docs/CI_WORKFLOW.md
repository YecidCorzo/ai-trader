# Backend CI workflow

The `.github/workflows/backend-tests.yml` workflow is the integration gate for the Python backend.

## Triggers

- Every pull request runs the complete backend checks. The target branch is intentionally not filtered, so stacked pull requests receive the same validation.
- Pushes to `main` run the same checks after integration. This verifies the resulting mainline commit rather than relying only on the pre-merge pull-request run.
- Pushes to the maintained work-branch families (`feature/**`, `fix/**`, `integration/**`, `platform/**`, `finance/**`, `trading/**`, `security/**`, and `ci/**`) run the checks during development.
- `workflow_dispatch` allows a maintainer to request a run manually.

## Checks

The job installs the pinned development requirements, checks dependency consistency with `pip check`, compiles `backend` and `tests`, then runs both the full pytest suite and unittest discovery.

## Release safety

A green workflow is evidence that these automated checks passed for the tested commit; it is not a release-readiness or profitability claim. PAPER remains simulation-only. No exchange credentials, live endpoints, or real orders are part of this workflow.
