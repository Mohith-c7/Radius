# PR: add clamp

Add `clamp(value, lo, hi)` to `limits.py`.

- A value above `hi` returns `hi`.
- A value below `lo` returns `lo`.
- A value inside the range is returned unchanged.
