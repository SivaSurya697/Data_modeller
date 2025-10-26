# User Journey & Flow

This guide summarises how a practitioner moves through the Data Modeller application based on the implemented routes, templates, and services.

## 1. Launch and global setup

- `app.py` loads environment variables, prepares the Flask application, configures database access, and registers every feature blueprint so that the navigation targets are available once the server is running.【F:app.py†L33-L169】
- Visiting `/` redirects to the Domains screen, establishing domain selection as the entry point for the rest of the workflow.【F:app.py†L73-L141】

## 2. Configure user settings

- `/settings/` renders the settings page where users can store encrypted OpenAI credentials and rate limit preferences.【F:src/api/settings.py†L15-L47】【F:templates/settings.html†L4-L33】
- Successful submissions flash a confirmation and persist values through `save_user_settings`, ensuring drafting is configured before modelling work begins.【F:src/api/settings.py†L26-L39】

## 3. Curate business domains

- `/domains/` accepts new domain submissions, validates input, and, on success, creates review tasks for impacted domains so stakeholders can coordinate follow-up work.【F:src/api/domains.py†L32-L86】
- The Domains template lists the existing entities and generated review tasks, helping users understand current coverage before drafting.【F:templates/domains.html†L4-L60】

## 4. Import and review source metadata

- The `/sources/` route assembles a view model of source systems, tables, and profiling data from the database before rendering the dashboard.【F:app.py†L77-L141】
- The Sources template exposes htmx-powered metadata import, profiling form controls, and detailed tables so analysts can connect upstream context to modelling decisions.【F:templates/sources.html†L6-L151】

## 5. Generate and inspect model drafts

- `/modeler/draft` orchestrates draft creation via `ModelingService`, handling validation and surfacing errors if the LLM call fails.【F:src/api/model.py†L563-L584】
- The draft review UI organises generated metadata, entity breakdowns, relationships, mapping automation, and coverage checks, enabling collaborative review of the AI-authored proposal.【F:templates/draft_review.html†L4-L200】

## 6. Capture and merge change sets

- `/changesets/` captures manual change notes tied to a domain and displays existing records sorted by recency.【F:src/api/changesets.py†L363-L400】
- The detail component allows reviewers to move change sets through draft/review/approval states, run dry-run merges, and publish merged outputs against the selected domain.【F:templates/components/changeset_detail.html†L1-L59】

## 7. Analyse model quality

- The quality blueprints provide JSON and HTML endpoints that calculate MECE coverage, highlight ontology gaps, and present naming suggestions for a selected domain.【F:src/api/quality.py†L1-L210】
- `templates/quality_dashboard.html` renders these metrics as badges, tables, and lists so teams can triage collisions and missing ontology coverage.【F:templates/quality_dashboard.html†L1-L70】

## 8. Export and publish artefacts

- `/exports/` validates export requests, resolves the correct exporter, writes artefacts to disk, and records metadata for download history.【F:src/api/exports.py†L17-L83】
- The exports interface lists previous runs and provides quick access to data dictionary and PlantUML outputs for downstream consumers.【F:templates/exports.html†L1-L120】
- `/api/model/publish` merges approved change sets (when provided), validates the resulting model JSON, and persists artefact metadata so a reviewed draft can be distributed.【F:src/api/model.py†L589-L705】

## Identified gaps

1. The quality dashboard blueprint is registered but the primary navigation omits a link, making the `/quality/dashboard` analysis difficult to discover without a direct URL.【F:app.py†L153-L169】【F:templates/base.html†L13-L19】
2. `templates/sources.html` contains a helper script that targets `importForm` and `importPayload`, but those elements do not exist (the markup uses `import-payload` and an htmx button), and the script never closes properly, so the fallback workflow cannot run.【F:templates/sources.html†L36-L195】
3. Change sets capture only a domain, title, and summary via the form, leaving no UI to append the change items that downstream merge and publish workflows expect.【F:templates/changesets.html†L4-L36】【F:src/api/changesets.py†L363-L400】

Use this flow to orient new contributors and to prioritise remediation of the gaps called out above.
