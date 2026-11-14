# AdvancedStrategy score categories

The strategy score is a deterministic rule score, not a statistical win
probability. A directional signal is eligible only when all three mandatory
categories confirm the same direction:

- **Trend (0–40):** EMA fast/slow relationship and price relative to trend EMA.
  Either trend rule confirms the category; both add their points.
- **Momentum (0–30):** RSI band and/or MACD histogram confirms direction.
  At least one must agree.
- **Volume (0–15):** VWAP must be available and price must be on the correct
  side of VWAP. Missing/zero-volume VWAP cannot confirm a direction.

Recent price structure can add up to 15 points but cannot replace any mandatory
category. After category confirmation, the directional score must also meet
`min_score` and exceed the opposing score.

The API response exposes per-category scores and direction-specific category
confirmation flags so a signal can be audited. If a required category is
missing, the strategy returns NEUTRAL and identifies the missing categories.
