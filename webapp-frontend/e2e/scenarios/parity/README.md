# Crimpd parity specs — one file per task

Add `<area>.spec.ts` here for each `CRIMPD …` issue (e.g. `settings.spec.ts`), importing helpers
from `../../fixtures/parity`. Use dedicated seeded users per width/theme when the test mutates
data. Files here run in the serial `parity` Playwright project. Do not append to
`../crimpd-parity.spec.ts` (kept for the baseline and the first blocks).
