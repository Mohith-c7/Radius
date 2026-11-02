# PR: parse human duration strings

Add `parse_duration(text)` to `durations.py`.

- `"2h30m"` returns 9000; units are `h`, `m`, `s`; spaces are ignored.
- Text that is not a sequence of `<number><unit>` raises `ValueError`.
