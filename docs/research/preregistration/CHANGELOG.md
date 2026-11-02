# Pre-registration Changelog and Freeze Mechanism (EP-02)

Applies to `PREREGISTRATION.md` in this folder.

## 1. Freeze mechanism

1. **Version.** `PREREGISTRATION.md` carries a version in its freeze block (`0.x-draft` while drafting, `1.0` at the first freeze).
2. **Canonical content hash.** SHA-256 of the file after (a) converting CRLF to LF and (b) deleting every line from `<!-- FREEZE-BLOCK-START -->` to `<!-- FREEZE-BLOCK-END -->` inclusive (the block records the hash, so it is excluded). Command (bash, run from this folder):

   ```
   tr -d '\r' < PREREGISTRATION.md | sed '/<!-- FREEZE-BLOCK-START -->/,/<!-- FREEZE-BLOCK-END -->/d' | sha256sum
   ```

3. **Freeze procedure (owner).** (i) Complete the checklist in `PREREGISTRATION.md` section 16 and answer section 17. (ii) Replace the freeze block: set "FROZEN", version, date (UTC), owner, and the hash from step 2. (iii) Add a row to the version table below with the same hash. (iv) Commit; create a signed git tag `prereg-v<version>` on that commit. (v) Deposit the file (and this changelog) in the external location chosen in decision 17.10 and record the location. (vi) Only then run confirmatory experiments.
4. **Verification.** Anyone can recompute the hash from the tagged commit; it must equal the table and the freeze block.
5. **After the freeze.** The body of `PREREGISTRATION.md` does not change. Every change is an amendment (section 3 here), never an edit. The freeze block alone may be updated to add the deposit location. If a re-draft is needed, create `PREREGISTRATION-v2.md`, keep v1 intact, and explain in the amendments log.
6. **Tuning-closed entries.** Before any test-split evaluation, add an entry to the "Tuning closed" log below (commit hash, `algo_version`, manifest hash, date). The test split is evaluated once per entry.

## 2. Versions

| Version | Date | Status | Canonical hash (SHA-256) | Notes |
|---|---|---|---|---|
| 0.1-draft | 2026-11-02 | DRAFT -- not frozen | not computed | Initial draft (EP-02). Incorporates EP-01 findings. |

## 3. Amendments (post-freeze)

Rule: every post-freeze change is an amendment with justification. Minor and major amendments are defined in `PREREGISTRATION.md` section 14. Entries are append-only.

Template:

```
### A<n> -- <short title>   (minor | major)
- Date (UTC):
- Author:
- Affects (RQs / sections):
- Text before:
- Text after:
- Justification:
- Test-split results seen before this amendment? (yes / no):
- Consequence for reporting (for example "RQ3 H3b reported as exploratory"):
- Chain hash: SHA-256 of (previous chain hash + newline + text of this entry); the first entry uses the frozen content hash as the previous hash.
```

None yet (not frozen).

## 4. Pre-freeze pilots

Any analysis run on dev data before the freeze is listed here (date, what, data used, whether it influenced any choice in `PREREGISTRATION.md`).

None recorded.

## 5. Tuning-closed log

None yet.

## 6. Unplanned deviations log

None yet.

## 7. History

- 2026-11-02: created with the 0.1 draft (EP-02). Not frozen.
