# #5 — Settings API: a stable configurator identifier

> Implemented inline. Written against `v2026.2.9` / `dbac916`.

**Goal:** Every setting gets a `configurator` identifier that is the same on a pip-installed
tenant and a dev-submodule tenant, whatever the tenant's `CAMPUS_CODE_PREFIX`, and across
title/name edits. Tools can list, read and write by that identifier.

**Architecture:** `configurator_id(report_class)` derives the identifier from the configurator
**class**, not from the record:
1. Take `report_class.__module__` and drop the trailing `.settings.<module>`, giving e.g.
   `drop_wd.drop_wd` or `drop_wd`.
2. Collapse repeated adjacent segments, so `drop_wd.drop_wd` becomes `drop_wd`.
3. Append `:<class name>`.

Results: `drop_wd:drop_wd_email`, `grades:class_section_grades`, `cis:support_docs`,
`class_visit:class_visit`. No package needs changing, and `key` is untouched.

`resolve_record()` accepts the identifier (any ref containing `:`) before trying key and name.
Every route that resolves a record (detail GET/PUT/PATCH, `schema/`, `history/`) therefore
supports it with **the same permissions, `dry_run` and `If-Match`**, because it is the same code
path. The list endpoint gains a `configurator` field and a `?configurator=` filter; the
detail and schema responses gain the field.

The issue offered a `by-configurator/<id>/` route; it isn't needed. `/api/v1/settings/<configurator>/`
already resolves, and `?configurator=` covers the list.

## Review Focus
1. Two records whose classes resolve to one identifier → 400 "matches more than one", like key/name.
2. A record whose class won't import → `configurator: null` in the list, not a 500.
3. A key that happens to contain `:` → still found by key when no configurator matches.
4. A module without a `.settings.` segment → falls back to dropping the last segment.
5. A non-adjacent repeat (`a.b.a`) is not collapsed.

## Tasks
- [x] `configurator_id`, `_configurator_of`, resolve / list / detail / schema.
- [x] Tests in `setting/tests.py`.
- [x] README + CLAUDE.md, full suite, commit.
