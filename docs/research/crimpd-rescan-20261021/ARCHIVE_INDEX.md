# Historical Crimpd rescan archive — inventory and integration boundary

Read-only inventory verified on 2026-11-17. This index does not import the
archive, establish fresh product parity, or accept proposed user journeys.
Current behavior remains governed by [PROJECT_SPEC](../../PROJECT_SPEC.md);
technical coordination follows [AGENT_EXECUTION_MODEL](../../AGENT_EXECUTION_MODEL.md).

## Exact source

- Archive: PR #361, `c584cafd331fbd281c8846b849f700c2dd3cbb15`.
- Historical work: 2026-10-21 through 2026-10-29.
- Merge-base and inventory baseline: `e3dd6400b2e26cbb01ba35bd03a74fe2de8752af`.
- Compared main: `dab8a695170cac38868f3c9665a849b1374b5b6f`.
- Separately reviewed Nov10 package: PR #385,
  `2877e17141e93e9ad58b9cf01ec868c77eea8f08`.

All 56 branch-only commits produce 1155 additions exclusively under this
research directory. There are no application or workflow changes in that
branch delta. A two-point diff against newer main also contains main's later
changes; those must not be attributed to the historical research branch.
None of the 1155 archive paths or blobs duplicates the compared main or PR385.
That proves distinct storage, not semantic novelty or privacy clearance.

| Archive area | Files |
| --- | ---: |
| Root documents and CSV | 42 |
| `evidence/` | 1078 |
| `our-app/` | 30 |
| `tools/` | 5 |
| Total | 1155 |

Formats: 419 PNG/JPG, 626 JSON, 24 CSV, 41 Markdown, 3 XML, 6 TXT,
31 `.done2`, and 5 Python files. Research utilities were not executed.

## Historical pointers, not imported evidence

These names refer to files at the exact archive SHA above. Their contents
remain outside main pending review; they are not broken local-file links.

| Archive file | Purpose or remaining limitation |
| --- | --- |
| `coverage.csv` | 105 historical coverage rows; not a fresh acceptance run |
| `observations.csv` | 157 historical observations; evidence strength must be retained |
| `comparison.csv` | 28 comparisons against the then-current application |
| `acceptance-matrix.csv` | 23 historical acceptance rows; not blanket acceptance |
| `acceptance-report.md` | Historical review state and unresolved cases |
| `remaining-queue.csv` | Remaining work must be reconciled with current scope |
| `proposals-for-paths.md` | Proposals are distinct from accepted product requirements |
| `links.md` | Historical paths-table pointer; no delivery/access proof here |

## Historical coverage review — 2026-11-20

The review used the status columns of `coverage.csv` and
`acceptance-matrix.csv` at archive head `c584cafd`. The coverage register
has 105 distinct scenario IDs.

| Scenario status | Observed evidence | Documentary evidence | Unknown evidence | Total |
| --- | ---: | ---: | ---: | ---: |
| OBSERVED | 87 | 0 | 0 | 87 |
| PARTIAL | 9 | 1 | 0 | 10 |
| BLOCKED | 0 | 1 | 7 | 8 |
| Total | 96 | 2 | 7 | 105 |

Nine partial scenarios have observed evidence for part of their scope.
Three blocked scenarios have no observation reference. The archive's
separate acceptance register has 14 `ВЫПОЛНЕНО`, seven `ЧАСТИЧНО` and
two `НЕДОСТУПНО` rows. These counts describe the historical registers
at the pinned head. The review used aggregate status fields and checked
neither the underlying media nor the reference app.

The later November 10 audit leaves C09 (skill-template instantiation)
and C10 (completion-to-plan-credit comparison) UNKNOWN. Keep these
items open in #348 and use the November report for its actual execution
scope. [November audit](../../audit/crimpd-20261110/REPORT.md#unexecuted-scope-and-ledger)

## Related tasks and next acceptance

- #347 is the research and path-agreement umbrella; this index does not close it.
- #348 has historical source material, but complete current coverage is unproven.
- #349 comparison Sheet: its technical delivery was verified and closed.
  The approved private result stays in place. [Completion receipt](https://github.com/bimoool/pullup-trainer-bot/issues/349#issuecomment-6952482107)
- #350 paths Sheet: its technical draft was verified and closed. Proposed
  journeys still require agreement under #347. [Completion receipt](https://github.com/bimoool/pullup-trainer-bot/issues/350#issuecomment-6949118811)

The original PR stays draft. Before transferring any more files, select a
bounded subset, review its contents and evidence provenance, retain UNKNOWN
and BLOCKED cases, and obtain current checks plus independent review.
Screenshots, JSON/XML/text dumps, ledgers and incident/support material need
individual privacy and necessity review. Public source location alone is not
approval to republish personal data. External Sheet URLs and account-derived
values are deliberately excluded from this index.

No reference-app session, account mutation, product test, production command,
new credential or Sheet write was performed for this inventory.
