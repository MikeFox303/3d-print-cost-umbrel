# Pricing model (development)

Two customer-facing prices are produced:

- **Minimum price**: production cost + risk + tax/platform fees + minimum margin, with a global minimum order floor.
- **Recommended price**: minimum model plus an adaptive equipment payback contribution and target margin.

## Adaptive equipment payback

The monthly payback rate is calculated once per calendar month using only prior completed jobs:

1. Sum completed commercial print hours over the rolling window (default 90 days).
2. Convert to monthly-equivalent hours.
3. Use `max(monthly_equivalent, floor_hours)` as reference hours. This prevents low customer count from exploding the quote.
4. Divide remaining equipment balance by remaining target months and reference hours.
5. Clamp to configured min/max hourly payback rate (defaults 15–30 UAH/h).
6. Snapshot the rate into every order created that month.

When an order is completed, the realized payback is limited by the actual customer price and operating surplus. A configurable share of surplus above the planned contribution can accelerate recovery.

The 12-month target is therefore a goal, not a guarantee funded by the next customer.
