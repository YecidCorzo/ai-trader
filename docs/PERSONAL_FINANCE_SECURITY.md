# Personal finance security boundary

## Current product contract

The personal-finance API is a **local, single-user feature** intended for one trusted user on their own development machine. It is not an authenticated or multi-user service.

The current SQLite schema has no user or tenant ownership boundary, and the finance endpoints do not authenticate callers. Anyone who can reach the API can read or change the local finance data. Do not expose this service to a LAN, public network, reverse proxy, tunnel, or shared hosting environment.

## Safe local startup

From the repository root, start the backend with an explicit loopback bind:

```bash
uvicorn main:app --app-dir backend --host 127.0.0.1 --port 8000
```

Do not replace `127.0.0.1` with `0.0.0.0` or a public interface. Keep the SQLite database file on a machine and filesystem controlled by the single user. Do not put the database in a shared folder or commit it to source control.

The dashboard is served by the same FastAPI application, so its normal browser requests are same-origin. Wildcard CORS is therefore unnecessary and has been removed. If a separate local frontend origin is introduced later, configure only its exact origin after reviewing the deployment boundary; CORS is not authentication.

## Required before remote or multi-user use

Do not deploy the finance API remotely or share it with other users until all of the following are designed, implemented and tested:

- Authentication on every finance read and write operation.
- User/tenant ownership on accounts, categories, transactions, opening balances and every related query.
- Database constraints and repository-level checks that prevent cross-user reads and writes (not only route-level filtering).
- Authorization tests proving one user cannot enumerate, read, update or associate another user's records.
- Explicit secret management, transport security, backup, retention and operational policies.
- A reviewed CORS allowlist for the actual frontend origins.

Adding CORS restrictions alone does not create an access-control boundary. A SQLite file without ownership fields must remain single-user.

## Scope safeguards

- No bank credentials or bank integrations are required for this local version.
- Finance endpoints record and report manually entered data; they do not move money.
- Trading remains PAPER MODE. No live order execution or exchange trading credentials are part of this feature.
