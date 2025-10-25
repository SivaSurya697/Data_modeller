# Architecture Overview

This document describes the major components, data flow, and extension points of the Data Modeller application.

## High-level design

The application follows a layered architecture:

1. **Presentation layer (`src/api/` + `templates/`)** – Flask blueprints expose HTML routes that orchestrate user interactions.
2. **Service layer (`src/services/`)** – Pure-Python modules implement business logic such as context assembly, model generation, validation, and exporting.
3. **Persistence layer (`src/models/`)** – SQLAlchemy manages the database engine, sessions, and ORM mappings for settings, domains, models, change sets, and exports.
4. **External providers** – The OpenAI Chat Completions API generates model drafts, and filesystem exporters produce downstream artifacts.

```
Browser ──▶ Flask blueprint ──▶ Service layer ──▶ ORM session ──▶ Database
                          │                     │
                          └────▶ OpenAI client ◀─┘
```

## Application bootstrap (`app.py`)

- Loads environment variables using `python-dotenv` and configures the database engine via `src/models/db.init_engine`.
- Configures the Flask app with shared settings and an `instance/` folder for local configuration.
- Ensures database tables exist via `src/models/db.create_all()` using the pre-configured SQLAlchemy engine.
- Sets up rate limiting with `flask-limiter` based on the configured requests-per-minute value.
- Registers the feature blueprints:
  - `settings` – manage configuration overrides stored in the database.
  - `domains` – CRUD operations for domains and viewing associated models.
  - `model` – trigger new drafts and review results.
  - `changesets` – capture human-authored change notes.
  - `exports` – execute exporters and list generated assets.

## Persistence layer

The ORM models in `src/models/tables.py` define the storage schema:

- `Settings` – per-user configuration including encrypted OpenAI credentials.
- `Domain` – group of related data models.
- `DataModel` – individual model drafts, including summary, markdown definition, and optional instructions.
- `ChangeSet` – human-authored change notes tied to a `DataModel`.
- `ExportRecord` – file metadata produced by exporters.

`src/models/db.py` provides:

- `engine` and `SessionLocal` configured from the application settings.
- `get_db()` context manager yielding a unit of work with commit/rollback semantics.
- `create_all()` to create tables on demand.

## Service layer

### Configuration (`src/services/settings.py`)

`save_user_settings()` persists encrypted API credentials for a user, while `get_user_settings()` decrypts and returns them as a `UserSettings` dataclass. Both helpers operate on a SQLAlchemy session and rely on a Fernet key supplied via the `SETTINGS_ENCRYPTION_KEY` environment variable.

### Prompt context (`src/services/context_builder.py`)

- `load_context(session, domain_id)` loads the target domain, latest models, change sets, and settings.
- `DomainContext.to_prompt_sections()` compiles human-readable sections for prompts.
- `build_prompt()` assembles the final prompt, optionally adding user instructions and requesting a JSON response.

### LLM orchestration (`src/services/llm_client.py` and `src/services/llm_modeler.py`)

- `LLMClient` wraps the OpenAI Chat Completions client. It always instantiates the SDK as `OpenAI(api_key=..., base_url=...)` to support custom gateways.
- `ModelingService.generate_draft()` orchestrates context loading, prompt construction, LLM invocation, ORM persistence, and impact analysis.
- `DraftResult` bundles the stored model and review notes for the blueprint.

### Impact analysis (`src/services/impact.py`)

Calculates a diff between the latest existing model definition and the newly generated one, optionally seeded with change hints returned from the LLM.

### Validation (`src/services/validators.py`)

Pydantic models validate form submissions for settings, domains, and draft requests. Validation errors bubble up to the blueprints and are displayed via `flask.flash()`.

### Exporters (`src/services/exporters/`)

Each exporter accepts a `DataModel` instance and writes artifacts to the `outputs/` directory:

- `dictionary.export_dictionary()` – generates a Markdown data dictionary summarising the model.
- `plantuml.export_plantuml()` – produces a PlantUML class diagram stub annotated with the model definition.

New exporters can be added by following the same signature and registering them in `src/api/exports.py`.

## Request flow example: generating a draft

1. A user submits the draft form from `templates/draft_review.html` handled by `src/api/model.py`.
2. The blueprint validates input via `DraftRequest` and opens a SQLAlchemy session using `get_db()`.
3. `ModelingService.generate_draft()` loads domain context, builds a prompt, invokes the OpenAI client, persists the new `DataModel`, and evaluates impact.
4. The blueprint commits the transaction, flashes a success message, and renders the updated draft alongside impact highlights.

## Request flow example: exporting artifacts

1. The user selects an exporter on the Exports page (`src/api/exports.py`).
2. The blueprint loads the `DataModel`, resolves the requested exporter function, and passes the configured `outputs/` directory.
3. The exporter writes the artifact to disk and `ExportRecord` captures metadata for the UI.
4. The page refreshes with the updated export list and filesystem links.

## Error handling and resilience

- Form validation uses Pydantic models to prevent malformed inputs.
- The LLM client raises a descriptive `ValueError` if the API key is missing or the response payload cannot be parsed.
- `get_db()` ensures transactions are rolled back on exceptions.
- Rate limiting mitigates abusive traffic patterns.

## Extensibility guidelines

- **Adding blueprints** – create a module in `src/api/`, define the routes, and register it via `register_blueprints()` in `app.py`.
- **Expanding the data model** – extend `src/models/tables.py` and run `flask --app app.py init-db` after updating the schema. For migrations across environments, integrate Alembic using the existing SQLAlchemy engine configuration.
- **New OpenAI workflows** – create dedicated services under `src/services/` to keep external calls isolated and testable.
- **Automation & tasks** – Flask CLI commands can be added in `app.py` or separate modules to cover seeding, maintenance, or batch operations.
