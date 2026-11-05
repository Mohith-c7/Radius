```feature
Feature: Discounts
  Background:
    Given a logged in user

  Scenario Outline: Apply code
    Given a cart total of <total>
    When code <code> is applied
    Then the total becomes <result>

    Examples:
      | total | code | result |
      | 100   | A10  | 90     |
```
