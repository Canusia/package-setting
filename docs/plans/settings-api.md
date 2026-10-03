# Token-authenticated settings API (package-setting#4)

## Goal

Let tooling outside the browser (first consumer: client_management's *Push to tenant*)
list, read, validate and write tenant settings, without logging in as staff or scraping HTML,
and without skipping the configurator's validation.

## Endpoints

The package ships `setting.urls.api`. The host mounts it at `api/v1/settings/`.

| Method & path | Does |
|---|---|
| `GET /` | Lists every `SettingRecord`: `id`, `key`, `name`, `app`, `title`, `description`, `categories`, `has_value`, `importable`. Filter with `?category=` and `?app=`. |
| `GET /<ref>/` | Returns `{key, record_id, title, description, value, updated_at, version}`. Sends an `ETag` header equal to `version`. |
| `PUT /<ref>/` | Replaces the value with the body `{"value": {...}}`. |
| `PATCH /<ref>/` | Merges the given keys into the stored value, then validates the result. |
| `GET /<ref>/schema/` | Lists the configurator's form fields: name, label, type, widget, required, disabled, choices, help_text, initial. |
| `GET /<ref>/history/` | Returns the change log: `id`, `date`, `user`, `action`, `value`, newest first. |

`<ref>` can be a record UUID, a configurator `key` (`class_visit`, `cis.settings.support_docs`)
or a record `name` when that name is unique. An ambiguous name returns `400`.

Write query parameters: `?dry_run=1` and `?allow_unknown=1`.

## Write path: validation goes through the configurator

The stored value and the form are often shaped differently. For example, `support_docs`
stores lists but its form edits newline-separated text. A JSON value therefore cannot be
bound to the form directly. Each configurator already converts stored → form in
`from_db()` and form → stored in `run_record()` / `_to_python()`, so the API reuses both.

All steps run in one `transaction.atomic()`, with the `Setting` row locked using
`select_for_update`:

1. **Concurrency.** If the request sends `If-Match` and it does not equal the current
   `version`, return `412`. (`*` matches any existing row.)
2. **Candidate.** For PUT, the candidate is the body value. For PATCH, it is `{**stored, **body}`.
3. **Stage.** Write the candidate to the row with `skip_history_when_saving`, so this
   intermediate step never appears in the Change Log.
4. **Form shape.** Call `report_class.from_db()` to convert the candidate to form-shaped
   initial data.
5. **Bind.** Bind it the way the HTML form would: `None`→`""`, `7`→`"7"`, bools→`"true"`/`"false"`,
   dict/list→JSON text, multi-select→a list of strings. Then call
   `report_class(request, data)`.
6. **Validate.** If `is_valid()` is false, return `400 {"errors": {field: [msg]}}` and roll back.
7. **Save.** Call `form.run_record()`, the same save the UI uses. History is recorded once,
   with the API user, because DRF sets the user on the underlying request and
   `HistoryRequestMiddleware` reads it.
8. **Unknown keys.** A submitted key that is missing from the stored result is one the
   configurator dropped. Without `allow_unknown`, return `400 {"errors": {"__unknown__": [...]}}`
   and roll back. With `allow_unknown`, write the key back into the stored value.
9. **Dry run.** With `dry_run`, roll back and return the value that would have been stored.
   Otherwise commit and return the GET payload.

A `from_db()` that raises on a malformed candidate, such as `types: 5`, returns `400`, not `500`.

## Permissions

These reuse the UI's rules rather than re-implementing them:

- **Read and list:** `can_manage_settings(user)`.
- **Write:** `can_edit_setting_key(user, key)`.
- **Campus scoping:** comes from `cis.campus_gate` (with the views' existing ImportError
  fallbacks). `can_manage_settings` re-checks the served campus. `CampusMiddleware` cannot do
  that check here, because it sees an anonymous user before DRF authenticates the token.
  `Setting.objects` narrows campus-scoped keys to the current campus.
- **Auth:** `TokenAuthentication` and `SessionAuthentication`. No credentials returns `401`
  (Token is first, so it supplies `WWW-Authenticate`). No rights returns `403`.
- **Login redirect:** the views carry `login_required = False`, so cis's
  `LoginRequiredMiddleware` does not redirect token callers to `/`.

## Out of scope

Editing `title` / `description`, and creating `SettingRecord`s.

## Tests (`setting/tests.py`, `SettingsAPITests`)

Two configurators are covered:

- `class_visit`, which has custom validation (skipped when that app is absent).
- `cis.settings.support_docs`, the generic path, where the stored shape differs from the form shape.

The tests cover:

- **Read:** a superuser token reads the value, and GET by key, name and UUID all agree.
- **PUT:** a valid PUT saves. A bad `report_fields_json` returns `400` with the
  `clean_report_fields_json` message and leaves the value untouched.
- **PATCH:** changes only the given key.
- **dry_run:** never saves and never writes history.
- **If-Match:** a stale value returns `412` and the current value succeeds.
- **History:** the Change Log gets one row per write, with the API user.
- **Unknown keys:** `400` without `allow_unknown`, kept with it.
- **Auth:** no token returns `401`, and a token without rights returns `403`.
- **Multi-campus:** CE staff cannot write a shared key.
- **Endpoints:** list filters, schema, history.

## Rollout

1. Implement in the package.
2. Add the host `myce/urls.py` mount to both the nested and the installed branch.
3. Release `v2026.2.9`: version bump, annotated tag, pin and gitlink. This waits for go-ahead.
