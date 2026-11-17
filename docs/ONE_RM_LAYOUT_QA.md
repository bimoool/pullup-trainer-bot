# 1RM speed layout evidence — #359 (2026-11-17)

The speed choices overlap in the original built app at 320 and 390 CSS pixels,
in both light and dark themes. Three long labels inherited the five-column
effort grid. The scoped responsive grid gives each label its own readable target.
This addresses only the overlapping speed choices in #359; its other feedback
remains open.

## Reproduction and fix

Chromium mobile viewport emulation rendered the production React build against
the real FastAPI application and a fresh, isolated PostgreSQL database. The
Telegram fixture supplies the signed synthetic identity and SDK bridge. This is
browser evidence, not physical iPhone or Telegram WebView acceptance.

Each case follows the actual flow: fresh onboarding (M=16, birth date 1992-04-15,
Moscow timezone), add the shipped course to the plan, open the planned workout,
enter body mass 80 kg and load step 2.5 kg, then start 1RM. Real API ladder
responses advance BW×5 → +7.5×3 → +15×1. No API/domain response or application
state is injected into these layout cases. No existing profile/history is reused
or changed; no seed or calendar-harness entry is added.

| Viewport / theme | Original target width | Fixed target | Font before / after |
| --- | ---: | ---: | ---: |
| 320 / light | 54.39 px | 288×56 px | 16 / 16 px |
| 320 / dark | 54.39 px | 288×56 px | 16 / 16 px |
| 390 / light | 66.80 px | 358×56 px | 16 / 16 px |
| 390 / dark | 66.80 px | 358×56 px | 16 / 16 px |

The word «Получилось» alone measures 89.41 px in the original layout. At 320 px
its first text range starts at x=-1.5 while its button starts at x=16. All fixed
text ranges stay inside their button, all centers hit their own button, and
button bounds do not intersect. Full measurements for all four cases are in
[measurements.json](captures/feedback-359/measurements.json).

| Case | Before | After |
| --- | --- | --- |
| 320 light | [Screenshot](captures/feedback-359/320-light-before.png) | [Screenshot](captures/feedback-359/320-light-after.png) |
| 390 dark | [Screenshot](captures/feedback-359/390-dark-before.png) | [Screenshot](captures/feedback-359/390-dark-after.png) |

## Regression and local checks

`course-setup-one-rep-max.spec.ts` adds four cases covering both widths and themes.
They check complete labels, text containment, independent targets at least
44×44 px, actual center hits and no page overflow. Each case then clicks all
three speed choices, verifies `fast` / `normal` / `slow` in the real requests,
and checks subsequent loads +22.5 / +25 / +27.5 kg.

- Original layout: **4 failed** on text containment.
- Fixed layout: **11 setup cases passed**, including the four regressions.
- Exact rollback of both product files and rebuild: **4 failed** again on text containment.
- Restore both product files and rebuild: **11 setup cases passed** again.
- Existing real API 1RM completion/save/workout-unlock case: **1 passed**.
- Preserved Home partial-failure suite: **7 passed**.
- Seed registry integrity: **10 passed**; existing courseV5 unit file: **1 passed**.
- Production build (including frontend TypeScript), strict functional E2E
  typecheck and `git diff --check`: **passed**.

The existing setup and Home suites retain their deliberate negative-response
cases; the new four layout cases use successful real API responses throughout.
Synthetic identities and PostgreSQL belong to this isolated validation. The
owned API process is stopped after the checks. Full final-head CI and independent
review remain integration gates.
