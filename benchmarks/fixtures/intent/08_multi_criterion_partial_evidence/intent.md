# PR: password policy

Add `validate_password(pw)` to `validators.py`. A password is valid only if:

1. It has at least 8 characters.
2. It contains at least one digit.
3. It contains at least one uppercase letter.
4. It is not on the common-password list (compared case-insensitively).
