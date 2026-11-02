## Acceptance Criteria

```gherkin
Feature: Password reset

  Scenario: Request a reset
    Given a registered user
    When they request a reset
    Then an email is sent

  Scenario: Expired link
    Given a link older than 1 hour
    When the user opens it
    Then an error page is shown
```
