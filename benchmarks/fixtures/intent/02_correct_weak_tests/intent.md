# PR: add normalize_email

Add `normalize_email(addr)` to `emails.py`.

- It trims surrounding whitespace and lowercases the address.
- An address without an `@` raises `ValueError`.
