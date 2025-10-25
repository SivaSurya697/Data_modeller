# Developer Guide

> 📚 Documentation: [Product Overview](../README.md) · [User Guide](USER_GUIDE.md) · [Developer Guide](DEVELOPERS.md) · [Architecture](../ARCHITECTURE.md)

This guide expands on the operational details required to build, run, and extend the Data Modeller application.

## Environment setup

1. **Install prerequisites**
   - Python 3.11 or newer
   - A virtual environment manager such as `venv`, `pyenv`, or `conda`
   - (Optional) SQLite client tools for inspecting the default development database
2. **Clone the repository and create a virtual environment**

   ```bash
   python -m venv .venv
   source .venv/bin/activate
   pip install --upgrade pip
   pip install -r requirements.txt
   ```

3. **Provide environment variables**
   - Copy the example file and adjust secrets: `cp .env.example .env`
   - Set the following variables in `.env` or your shell:
     | Variable | Purpose |
     | --- | --- |
     | `FLASK_ENV` | Chooses the Flask configuration profile (`development` by default). |
     | `DATABASE_URL` | SQLAlchemy connection string. Defaults to `sqlite:///instance/data_modeller.db`. |
     | `OPENAI_API_KEY` | Credential for the OpenAI API used when drafting models. |
     | `OPENAI_BASE_URL` | Override the default OpenAI endpoint for proxies or gateways. |
     | `RATE_LIMIT_PER_MINUTE` | Requests allowed per minute for rate limiting. |
     | `FLASK_SECRET_KEY` | Secret used for session signing and CSRF protection. |
     | `SETTINGS_ENCRYPTION_KEY` | Fernet key for encrypting stored settings. |

4. **Initialise the database**

   ```bash
   flask --app app.py init-db
   ```

   The command uses the engine defined in `src/models/db.py` to create tables in the configured database.

5. **Run the development server**

   ```bash
   flask --app app.py --debug run
   ```

   Navigate to `http://127.0.0.1:5000/` to access the web UI.

## Dependency management

- Application dependencies live in `requirements.txt`.
- Use the project virtual environment when installing new packages: `pip install <package>`.
- After adding or updating dependencies, lock them by running `pip freeze --local > requirements.txt` and commit the change.
- Rebuild the virtual environment when dependencies change to ensure deterministic installs: `rm -rf .venv && python -m venv .venv && ...`.

## Database tooling

- The default SQLite database resides under `instance/`. When switching to another RDBMS, update `DATABASE_URL` accordingly.
- SQLAlchemy models are defined in `src/models/tables.py` and sessions are managed via the `get_db()` helper in `src/models/db.py`.
- To inspect or modify data locally, open a Python shell with the Flask context: `flask --app app.py shell` and use `get_db()` to run queries.
- For schema migrations across environments, integrate Alembic using the existing SQLAlchemy engine configuration exposed in `src/models/db.py`.

## Testing and quality checks

- Run a lightweight syntax check before committing changes: `python -m compileall .`.
- Feature blueprints and services are designed for unit testing with `pytest`. Create tests under a `tests/` directory and execute them via `pytest`.
- Consider enabling type checking with `mypy` when contributing larger features. Service modules primarily use dataclasses and pydantic models and benefit from static analysis.

## Extension points

- **Blueprints**: Add new UI surfaces under `src/api/` and connect templates through `templates/`. Register the blueprint in `app.py` via `register_blueprints()`.
- **Services**: Encapsulate business logic inside `src/services/`. Follow the established patterns in `context_builder.py`, `llm_modeler.py`, and `impact.py` to keep orchestration testable.
- **Exporters**: Implement additional exporters in `src/services/exporters/` following the signature of `export_dictionary()` and `export_plantuml()`. Register them in `src/api/exports.py` to expose them through the UI.
- **CLI commands**: Extend the Flask CLI by adding functions decorated with `@app.cli.command()` in `app.py` or modules imported there.
- **Configuration**: Surface new configuration switches through `src/services/settings.py` to ensure they can be managed from the Settings screen.

Refer to [ARCHITECTURE.md](../ARCHITECTURE.md) for a detailed explanation of how these components interact.
