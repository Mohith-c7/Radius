# F-06 GitHub App live validation report

Copy this file to `REPORT.md` and fill it in. Link the generated `evidence/scenarios-*.md` log.

| Field | Value |
| --- | --- |
| Date (UTC) | |
| Validator | |
| Radius commit (`git rev-parse HEAD`) | |
| Sandbox repo / PR | |
| App id / installation id | |
| Tunnel (cloudflared / smee) | |
| Evidence log | `evidence/scenarios-....md` |

## Scenario results

Expected results come from the code as verified offline (see `RUNBOOK.md` section 0). Status: PASS / FAIL / BLOCKED.

| # | Scenario | Expected | Observed | Status | Screenshot | Defect |
| --- | --- | --- | --- | --- | --- | --- |
| 0 | App install + `installation` webhook | 202; repo connected; installation id stored on the organization | | | | |
| 0b | `ping` / redeliver ping | 202, no tenant lookup | | | | |
| 1 | Open PR | One completed `Radius confidence` check run on head SHA; one bot comment with marker | | | | |
| 2 | Push another commit | Completed check run on the new SHA; the same comment id edited in place | | | | |
| 3 | Edit title/description | `ignored`; no new check run or comment | | | | |
| 4 | Close PR | `ignored`; PR status closed; no new check run or comment | | | | |
| 5 | Reopen PR | Analysis reused for same head SHA; still one check run per SHA, one comment | | | | |
| 6 | Force-push | New SHA gets a completed check run; one comment; old SHA's check run left as is | | | | |
| 7 | Redeliver a webhook (same `X-GitHub-Delivery`) | 202 with stored response; no new analysis, check run or comment | | | | |
| 8 | Draft PR / `ready_for_review` | Draft ignored; ready_for_review analysed | | | | |
| 9 | Subscribed-but-ignored events (`issues`, `issue_comment`, `check_run`) | 202 `ignored`; the App's own check run and comment events do not loop | | | | |
| 10 | Private-repo clone with installation token | Worker clones, analysis completes | | | | |
| 11 | Check conclusion mapping | `neutral` without test evidence, `success` only for verified low/medium risk | | | | |

## Acceptance criteria (F-06)

- [ ] Written report with screenshots (this file)
- [ ] Check Run updates on each push
- [ ] No duplicate comments
- [ ] Webhooks idempotent on redelivery
- [ ] Fixtures added for every payload shape seen live

## Defects

| ID | Description | Severity | Link | Fixed in |
| --- | --- | --- | --- | --- |
| | | | | |

Known from offline review (confirm or close live):

1. ~~Installation sync hardcoded `default_branch=main`~~ Fixed offline: installation payloads carry no default branch, so a provisional `main` is stored and the first push/PR delivery corrects it; confirm live.
2. ~~`publish_in_progress` never called~~ Fixed offline: the worker opens the in-progress check at job start; confirm live (Checks tab shows In progress, then completes the same run).
3. ~~Clone auth used Bearer~~ Fixed offline: Basic `x-access-token:<token>` via the child environment (`runner.py`, `local_git.py`); confirm against real GitHub (private repo clone) and close.
4. ~~Closing a PR did not cancel analyses~~ Fixed offline for queued-not-started analyses (running ones intentionally finish); confirm live.
5. `installation` `deleted`/`removed` and `installation_repositories` `removed` are not handled.

## Notes and follow-ups
