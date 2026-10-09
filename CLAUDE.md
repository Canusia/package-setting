# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Overview

Dynamic settings/configurator registry and management interface. Apps register configurators via `CONFIGURATORS` attribute, which are then managed through a centralized UI.

## Key Components

### Model (`models/setting.py`)
**SettingRecord** - Registry of available settings:
- `app` - Which app the setting belongs to
- `name` - Setting identifier/class name
- `title` - Display title
- `categories` - Multi-select (Students, High Schools, Classes, Misc., Instructors)

### URL Structure (`/ce/settings/`)
- `/` - Main settings page organized by category
- `records_in_category/` - AJAX: Get settings for category
- `record_details/` - AJAX: Load setting form dynamically
- `run_record/<uuid>` - POST: Save setting values
- `update_setting/` - POST: Update setting metadata (title, description) and JSON value (superuser only)
- `setting_history/` - AJAX: Get change history for a setting (DataTables JSON)
- `search_index/` - AJAX: Every record with its form fields' label, help text and current value (tags stripped), for the quick search. Forms are instantiated, not rendered; a configurator that fails to load is returned with `fields: []`. Credential fields (`PasswordInput`/`HiddenInput` widgets, or names matching password/secret/private_key/api_key/token) are indexed with an empty value
- `add_new` - Register new configurator

### Settings API (`urls/api.py`, `views/api.py`; host mounts at `/api/v1/settings/`)
Token or session auth; no credentials → 401, no settings rights → 403. `<ref>` is a record UUID,
a **configurator identifier** (`drop_wd:drop_wd_email`, #5), a configurator `key`, or a unique
record `name`.
- `GET /` — list records (`?category=`, `?app=`, `?configurator=`); each row has `configurator`
- `GET /<ref>/` — `{key, configurator, record_id, title, description, value, updated_at, version}` + `ETag`
- `PUT|PATCH /<ref>/` — body `{"value": {...}}`; PATCH merges. `?dry_run=1`, `?allow_unknown=1`, `If-Match: <version>` (412 when stale)
- `GET /<ref>/schema/`, `GET /<ref>/history/`

Writes stage the candidate value (without history), run the configurator's `from_db()` to get
form data, bind and validate the form, then save via `run_record()` — so the API enforces exactly
what the UI enforces. Invalid → `400 {"errors": {...}}`, nothing stored. Views set
`login_required = False` so cis's `LoginRequiredMiddleware` doesn't redirect token callers.
Plan: `docs/plans/settings-api.md`.

`configurator_id(report_class)` is the stable handle for external tools. It is derived from the
**class** (module minus `.settings.<module>`, with the dev-submodule repeat collapsed, plus the
class name), so it doesn't move with install layout, a tenant prefix in `key`, or title edits.
Don't change the derivation: client_management keys workbook pushes off it.

## Commands

```bash
python manage.py register_settings  # Scan apps and register CONFIGURATORS
```

## Registering Configurators

In your app's `apps.py`:
```python
class MyAppConfig(AppConfig):
    CONFIGURATORS = [
        {
            'name': 'my_setting',
            'title': 'My Setting Title',
            'description': 'Description',
            'categories': '1,4',  # Category IDs (1=Students, 4=Misc)
            'app': 'myapp'
        }
    ]
```

Setting class location: `{app}.settings.{name}.{name}`

## Setting Class Interface

Each configurator class should implement:
```python
class my_setting(SettingForm):
    # Form fields...

    @classmethod
    def from_db(cls):
        # Load current values from Setting model

    def install(self):
        # Set default values on first registration

    def run_record(self, data):
        # Save form data to Setting model

    def preview(self, field):
        # Optional: Preview field behavior
```

## Setting Detail UI (`setting.html`)

The setting detail view has three tabs:

1. **Description** — Shows setting description. Superusers see an inline Edit button to update title, description, and raw JSON value via `update_setting/` endpoint.
2. **Setting** — Displays the current JSON value (`cis.Setting.value`) in a formatted `<pre>` block with a Copy to Clipboard button.
3. **Change Log** — DataTable showing change history via `django-simple-history`. Columns: Date, User, Action (Created/Changed/Deleted badges), Value (truncated preview, click for full JSON modal). Lazy-loads on tab show; auto-reloads after saves.

## Integration

- **Storage:** Values stored in `cis.models.settings.Setting` (key-value JSONField)
- **Change Tracking:** `cis.Setting` uses `django-simple-history` (`HistoricalRecords`) to track all value changes with user and timestamp
- **Permissions:** Requires `user.can_edit_users`; inline editing requires `is_superuser`
- **UI:** AJAX-driven forms with crispy-forms rendering, Bootstrap nav-tabs, DataTables for history
- **Dynamic Loading:** Uses `import_string()` to load setting classes at runtime

## Architecture

- `SettingRecord` = Metadata about available settings (registry)
- `cis.Setting` = Actual configuration values (storage, with `HistoricalRecords`)
- Setting classes = Form definition and save/load logic
