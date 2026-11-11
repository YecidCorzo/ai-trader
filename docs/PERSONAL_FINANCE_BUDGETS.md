# Personal finance API — monthly budgets

Monthly budgets are local single-user records, following the security boundary in [PERSONAL_FINANCE_SECURITY.md](PERSONAL_FINANCE_SECURITY.md).

## Create a category budget

`POST /api/finance/budgets`

Example request:

```json
{
  "category_id": "existing-expense-category-id",
  "currency_code": "SEK",
  "year": 2026,
  "month": 11,
  "amount": "5000.00"
}
```

A budget belongs to one expense category, one currency and one calendar month. The database enforces uniqueness for that combination. A duplicate returns HTTP 409. Only active expense categories and supported currencies are accepted.

## Read budget progress

`GET /api/finance/budgets/progress?year=2026&month=11`

The response reports, for each configured category budget:
- `budget_minor`: configured limit in integer minor units.
- `spent_minor`: sum of matching expense transactions in that calendar month.
- `remaining_minor`: budget less spending; may be negative when overspent.
- `utilization_percent`: spending as a percentage of the budget.
- `status`: `within_budget` or `over_budget`.

Month boundaries are UTC calendar boundaries. Spending is matched by category and original transaction currency; other currencies are not converted or combined. The response explicitly sets `fx_applied` to false. Missing budgets are not fabricated, and budgets do not imply bank synchronization or transaction completeness.

This first version does not support editing/deleting budgets, carry-over, recurring budgets, alerts, or multi-user ownership. Add those only as separate reviewed changes.
