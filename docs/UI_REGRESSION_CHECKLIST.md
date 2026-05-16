# UI Regression Checklist (Baseline: Stepper + Dropzone Polish)

Last updated: 2026-05-16
Scope: `static/index.html` UI surface only (no API contract changes)

## Automated smoke (Playwright)

- Test file: `tests/ui/ui-regression.smoke.spec.ts`
- Run:
  - `npm install`
  - `npx playwright install chromium`
  - `npm run ui:test`
- Optional custom target:
  - `UI_BASE_URL=http://127.0.0.1:8787 npm run ui:test`
  - If using FastAPI `/ui`: `UI_PATH=/ui npm run ui:test`
- CI:
  - Workflow: `.github/workflows/ui-smoke.yml`
  - Strategy: serve `static/index.html` via Python static server + Playwright API mocking

## 1) PDF upload works

- [ ] Open `/ui`
- [ ] Drag a valid PDF into dropzone
- [ ] Repeat once with click-to-select flow
- Expected:
  - File is accepted in both drag and click flows
  - Selected filename/confirmation state is visible in upload area
- Fail if:
  - Drag or click path does not attach file
  - No visible selected-state feedback

## 2) Stepper updates after parse/analyze flow

- [ ] Start from fresh page load
- [ ] Complete upload + parsing flow
- [ ] Trigger AI analysis flow
- Expected:
  - Current step changes color state in order: gray -> blue -> green
  - Completed previous step stays in completed style
- Fail if:
  - Step color/state does not advance
  - State order is skipped or regresses

## 3) AI result badges are correct

- [ ] Run one known document that returns mixed claim types
- [ ] Inspect badges in results card (claim level/source/review tags)
- Expected:
  - Badges render (no missing label)
  - Meaning matches payload values (no swapped colors/labels)
- Fail if:
  - Badge text is empty/incorrect
  - Badge style implies wrong status

## 4) Loading/error/success states are all visible

- [ ] Success path: normal upload + analysis
- [ ] Loading path: observe spinner/loading text during request
- [ ] Error path: submit with invalid file or force request failure
- Expected:
  - All three states are visually distinct and readable
  - Error message is actionable (not silent failure)
- Fail if:
  - Any state is not shown or indistinguishable
  - UI gets stuck in loading state

## 5) Mobile width does not break layout

- [ ] Test at ~375px and ~430px viewport widths
- [ ] Verify header, stepper, upload card, results card
- Expected:
  - No horizontal overflow for primary containers
  - Cards keep readable padding and stack correctly
- Fail if:
  - Horizontal scroll appears from core content
  - Text/buttons overlap or clip

## 6) Long text in Results does not break

- [ ] Use document/result containing long quoted text and long claims
- [ ] Check Risk table, Transparency box, section result cards
- Expected:
  - Long text wraps naturally
  - No card/header/table overflow
- Fail if:
  - Text spills outside container
  - Table row/column layout collapses

## Optional evidence capture (recommended)

- [ ] Save 3 screenshots per run:
  - Initial state (before upload)
  - After upload + stepper advanced
  - Results rendered (with badges + long text sample)
- [ ] Attach date and commit hash in PR/session note
