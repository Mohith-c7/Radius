# PR: add apply_discount

Add `apply_discount(price, percent)` to `pricing.py`.

- It returns the price reduced by `percent`, rounded to 2 decimals.
- `percent` must be within 0..100 inclusive; anything else raises `ValueError`.
