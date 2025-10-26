# Gap Tracking

## Documented features
- End-to-end user journey captured in `docs/USER_FLOW.md`, covering setup through publishing and surfacing current UX gaps.【F:docs/USER_FLOW.md†L1-L57】

## Known gaps to address
1. Add top-level navigation to the quality dashboard so the `/quality/dashboard` analysis is discoverable from the UI.【F:docs/USER_FLOW.md†L59-L64】
2. Repair the fallback import/profile script on the Sources page (incorrect element IDs and missing closure) to make manual uploads usable without htmx.【F:docs/USER_FLOW.md†L65-L70】
3. Extend the change set workflow with controls for authoring individual change items so the merge and publish paths receive the expected detail.【F:docs/USER_FLOW.md†L71-L76】
