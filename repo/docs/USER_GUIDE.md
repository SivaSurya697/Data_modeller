# User Guide

> 📚 Documentation: [Product Overview](../README.md) · [User Guide](USER_GUIDE.md) · [Developer Guide](DEVELOPERS.md) · [Architecture](../ARCHITECTURE.md)

This guide walks through the end-to-end workflow of the Data Modeller interface and explains how to complete common tasks.

## Accessing the application

1. Launch the web application (`flask --app app.py --debug run`).
2. Open `http://127.0.0.1:5000/` in a supported browser.
3. Use the navigation bar rendered from `templates/base.html` to switch between pages.

## Global layout

- **Header navigation**: Links to Settings, Domains, Draft Review, Change Sets, and Exports.
- **Flash messages**: Success and error notifications appear beneath the header after you submit a form.
- **Primary actions**: Each screen presents its core action on the left and supporting lists or history on the right.

## Configure settings

Location: [`templates/settings.html`](../templates/settings.html)

1. Visit **Settings**.
2. Provide optional prompt context such as data freshness notes or compliance requirements in the text area.
3. Enter your OpenAI API key and base URL if they are not already stored.
4. Click **Save settings**. Sensitive values are encrypted using the Fernet key defined by `SETTINGS_ENCRYPTION_KEY`.
5. The confirmation banner indicates the configuration is ready for drafting.

## Manage domains

Location: [`templates/domains.html`](../templates/domains.html)

1. Navigate to **Domains**.
2. Use **Create domain** to add a new business domain. Each domain groups drafts and exports.
3. The domain list on the right shows existing entries. Use **Edit** to update descriptions or **Delete** to remove a domain and associated drafts.

## Draft a model

Location: [`templates/draft_review.html`](../templates/draft_review.html)

1. Go to **Draft Review**.
2. Select the target domain from the dropdown.
3. Optionally add instructions that steer the generated draft (for example, "Highlight GDPR relevant fields").
4. Click **Generate draft**. The system composes a contextual prompt using domain data, change sets, and saved settings before calling the OpenAI API.
5. The resulting entities, attributes, and relationships appear in the Draft panel.

## Review impact and change history

Location: [`templates/draft_review.html`](../templates/draft_review.html)

- The **Impact analysis** panel highlights differences between the new draft and the most recent accepted model.
- Review the notes to decide whether additional manual adjustments are required.
- To capture manual changes, navigate to **Change Sets**.

### Record change sets

Location: [`templates/changesets.html`](../templates/changesets.html)

1. Choose the domain that the change set applies to.
2. Provide a descriptive title and notes outlining the manual adjustments.
3. Submit the form to log the change set. It will appear in the history table alongside timestamp and author.

## Export artifacts

Location: [`templates/exports.html`](../templates/exports.html)

1. Open **Exports** and select the domain.
2. Pick an exporter:
   - **Data Dictionary (Markdown)** generates a human-readable summary of entities and attributes.
   - **PlantUML Diagram** produces a class diagram describing entities and relationships.
3. Click **Run exporter**. Files are written to the `outputs/` directory and recorded in the exports table with download links.

## Troubleshooting tips

- Ensure environment variables are configured before generating drafts; missing OpenAI credentials will surface as validation errors.
- If drafts fail to generate, inspect the Flask server logs for API response details.
- Clearing the browser cache or refreshing the page resolves most display issues after data updates.

For a deeper look at how the application is structured, continue to the [Architecture overview](../ARCHITECTURE.md).
