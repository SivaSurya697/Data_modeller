# Data Modeller

Data Modeller is a Flask application that helps product and analytics teams quickly draft, review, and export data models for their business domains. It combines collaborative workflows with OpenAI-powered suggestions to keep documentation and downstream artifacts up to date.

## Features

- **Domain management** – capture business domains and organise generated drafts per domain.
- **Guided model drafting** – collect operational settings, recent changes, and existing definitions to build rich prompts for the OpenAI Chat Completions API.
- **Impact analysis** – compare new drafts against the latest model and surface potential differences or review notes.
- **Change tracking** – persist notable adjustments as change sets tied to generated drafts.
- **Export pipeline** – generate markdown data dictionaries and PlantUML diagrams that are saved to the `outputs/` folder.
- **Rate limiting** – protect the service from overuse with a configurable per-minute limiter.

## Getting started

### 1. Install system prerequisites

- Python 3.11+
- A working virtual environment tool such as `venv` or `pyenv`

### 2. Clone the repository and install dependencies

```bash
python -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
```

### 3. Configure environment variables

Copy the sample configuration and update the secrets:

```bash
cp .env.example .env
```

| Variable | Description |
| --- | --- |
| `FLASK_ENV` | Deployment environment label. Use `development` for local work. |
| `DATABASE_URL` | SQLAlchemy connection string. Defaults to a SQLite file in the project root. |
| `OPENAI_API_KEY` | Secret key for the OpenAI account used to generate model drafts. |
| `OPENAI_BASE_URL` | Base URL for the OpenAI API. Useful for gateways or proxies. |
| `RATE_LIMIT_PER_MINUTE` | Number of requests allowed per minute. |
| `FLASK_SECRET_KEY` | Secret for signing sessions and CSRF tokens. |

The application automatically loads variables from the `.env` file when the Flask process starts.

### 4. Initialise the database

```bash
flask --app app.py init-db
```

This command creates the SQLite database (or any configured database) and applies the ORM schema defined in `src/models/tables.py`.

### 5. Run the development server

```bash
flask --app app.py --debug run
```

Navigate to `http://127.0.0.1:5000/` to access the UI.

## Usage workflow

1. **Configure operational settings** – Store any shared parameters or constraints in the Settings screen. They are injected into prompts for consistent guidance.
2. **Create domains** – Define domains and their descriptions from the Domains screen. Domains group related drafts and exports.
3. **Generate a draft** – From the Draft Review page, select a domain, optionally provide instructions, and submit. The application builds a contextual prompt and stores the generated entities and relationships.
4. **Review impact** – Inspect the impact analysis rendered alongside the draft to understand how it differs from previous entity snapshots.
5. **Capture change sets** – Document manual adjustments as change sets for traceability at the domain level.
6. **Export artifacts** – Produce PlantUML diagrams or markdown data dictionaries from the Exports screen. Generated files appear under `outputs/`.

## Project layout

```
app.py                 # Flask application factory and CLI
src/api/               # Blueprints backing the HTML pages
src/models/            # SQLAlchemy engine helpers and ORM tables
src/services/          # Domain services (prompting, LLM integration, exports, validation)
static/app.css         # Shared styling
templates/             # Jinja templates for each screen
outputs/               # Generated export files
```

## Development tips

- Run `python -m compileall .` to perform a lightweight syntax check across modules.
- The OpenAI client is instantiated with `OpenAI(api_key=..., base_url=...)` to comply with enterprise gateway requirements.
- Add new exporters in `src/services/exporters/` and register them in the exports blueprint.
- The SQLAlchemy session helper in `src/models/db.py` provides a `get_db()` context manager for transactional operations.

## Further reading

Refer to [`ARCHITECTURE.md`](ARCHITECTURE.md) for an in-depth look at system components and request flow.
