Scenario: Empty cart
Given an empty cart
When the user checks out
Then an error is shown
And the cart stays empty

Scenario: Paid cart
Given a cart with one item
When the user pays
Then an order is created
