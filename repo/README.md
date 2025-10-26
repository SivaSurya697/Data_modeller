# Data Modeller

> 📚 Documentation: [Product Overview](README.md) · [User Guide](docs/USER_GUIDE.md) · [Developer Guide](docs/DEVELOPERS.md) · [Architecture](ARCHITECTURE.md)

Data Modeller is a collaborative web application that helps product and analytics teams capture business context, generate data models with OpenAI assistance, and share the resulting documentation.

## What it does

- **Guided drafting**: Assemble prompts from domain context, settings, and change history to generate entity-relationship models.
- **Impact visibility**: Compare each draft with the previous version to highlight additions, removals, and review notes.
- **Change tracking**: Record manual adjustments as change sets for compliance and audit needs.
- **Export automation**: Produce markdown dictionaries and PlantUML diagrams for downstream consumers in a single click.

## Who it serves

- **Product and analytics partners** use the UI to curate domains, request drafts, and review the resulting impact analysis.
- **Engineering teams** extend the service with new workflows, exporters, and integrations while maintaining a common data model.

## Quick orientation

- Launch the Flask server with `flask --app app.py --debug run` and visit `http://127.0.0.1:5000/` to explore the UI.
- Store configuration and secrets in a local `.env` file; the application automatically loads it on startup.

## Documentation

- Read the [User Guide](docs/USER_GUIDE.md) for page-by-page instructions on common tasks.
- Consult the [Developer Guide](docs/DEVELOPERS.md) for setup, tooling, and extension patterns.
- Explore the [Architecture overview](ARCHITECTURE.md) for component-level design details.

## Smoke testing the draft endpoint

Run the following loop after starting the local Flask server to ensure the autocorrection logic resolves metadata gaps:

```bash
# Force multiple drafts and check metadata issues disappear
for i in 1 2 3; do
  curl -s -X POST http://localhost:8000/api/model/draft \
    -H "Content-Type: application/json" \
    -d '{"domain":"Claims"}' \
  | jq '{attempts: .autocorrect_attempts, ok: .qa.ok, issues: .qa.issues}'
done
```
