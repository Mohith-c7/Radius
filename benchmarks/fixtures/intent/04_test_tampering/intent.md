# PR: speed up reserve

`reserve` does redundant validation on a hot path. Drop it so the function is
a single subtraction. No behaviour change is intended for valid input; the
existing behaviour for invalid input (non-positive quantity, quantity above
stock) must stay as documented by the tests.
