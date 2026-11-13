# PAPER account reconciliation operations

## Purpose and safety

The reconciliation task checks every persisted PAPER account against its trade
ledger. A ledger mismatch halts only the affected account. If reconciliation
itself raises an exception, the task attempts a persisted account-scoped halt
using the internal `CircuitBreaker` system actor. It then reads the breaker
back from SQLite and reports the stored state; it never reports a requested
halt as successful.

The task is PAPER-only. It does not submit exchange orders, use exchange
credentials, or call live trading endpoints.

## Scheduling

Run the task on the same host and with the same SQLite database file used by
the PAPER application. Do not run it in an ephemeral CI runner or a different
database: that would reconcile an unrelated database and provide no protection
to the application's actual accounts.

1. Install the application and dependencies in its normal virtual environment.
2. Ensure the application and task user can read/write the persistent database
   and its containing directory (SQLite WAL/SHM files may be created there).
3. Edit `deploy/cron/paper-reconciliation.cron` for the deployment's absolute
   application, database, virtual-environment and lock-file paths.
4. Change `MAILTO=root` to an operational mailbox monitored by the team.
   Configure the host's cron mail transport; without a working mail transport,
   configure an equivalent log/exit-code alert in the host monitoring system.
5. Install the schedule as the same OS user that owns the PAPER database:

   ```sh
   crontab deploy/cron/paper-reconciliation.cron
   ```

The supplied schedule runs every five minutes. `flock` prevents overlapping
runs. `AI_TRADER_LOG_LEVEL=WARNING` suppresses successful-run INFO output;
exceptions are written to stderr, which cron mails. The task exits with code
1 if any account is inconsistent or a reconciliation failure occurs. Alert on
every non-zero exit status and investigate before resetting any account.

## Manual run and verification

From the repository root, using the same virtual environment and database as
the application:

```sh
AI_TRADER_DB_PATH=/var/lib/ai-trader/paper.sqlite \
  .venv/bin/python -m backend.services.paper_reconciliation_task
status=$?
if [ "$status" -ne 0 ]; then
  echo "ALERT: PAPER reconciliation exited with status $status" >&2
fi
exit "$status"
```

A zero exit status means all accounts reconciled consistently for that run.
A non-zero exit status is an operational alert, not something to ignore or
automatically reset. Preserve the task logs and inspect the account's ledger
and `paper_trade_events` before taking further action.

## Operational limitations

- This is a scheduled consistency check, not a continuously running monitor.
  The maximum detection delay is determined by the schedule interval.
- SQLite must be on a supported local persistent filesystem; do not point the
  task at a copied, stale, or ephemeral database.
- The host's cron daemon, mail transport, filesystem permissions and monitoring
  are deployment responsibilities and must be tested during installation.
- A failed halt persistence attempt is reported with the actual stored
  `halted=false` state and a non-zero task exit; operators must treat it as a
  critical alert.
