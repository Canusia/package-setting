"""Token-authenticated settings API (Canusia/package-setting#4).

Lets tooling outside the browser list, read, validate and write settings.
Writes go through the configurator -- from_db() turns the submitted value into
form data, the form validates it, and run_record() stores it -- so the API
accepts exactly what the CE settings UI accepts, and nothing it would reject.

Permissions are the UI's (`can_manage_settings` to read, `can_edit_setting_key`
to write), including per-campus scoping on a multi-campus deployment.
"""
import json
import logging
import uuid

from django.db import transaction
from django.http import QueryDict
from django.utils.encoding import force_str
from django.utils.module_loading import import_string

from rest_framework import status
from rest_framework.authentication import (
    SessionAuthentication, TokenAuthentication)
from rest_framework.exceptions import NotFound, ParseError, PermissionDenied
from rest_framework.permissions import BasePermission, IsAuthenticated
from rest_framework.response import Response
from rest_framework.views import APIView

from cis.models.settings import Setting

from ..models.setting import SettingRecord
from .views import _user_can_manage_settings, can_edit_setting_key

logger = logging.getLogger(__name__)

_TRUE = ('1', 'true', 'yes', 'on')


def _flag(request, name):
    return str(request.query_params.get(name, '')).lower() in _TRUE


def _report_class(record):
    return import_string(f'{record.app}.settings.{record.name}.{record.name}')


def configurator_id(report_class):
    """A configurator's stable identifier (#5): '<package>:<class name>'.

    Taken from the class, so it is the same on a pip install
    (`drop_wd.settings.drop_wd_email`) and a dev submodule
    (`drop_wd.drop_wd.settings.drop_wd_email`), and does not move with a tenant
    prefix in `key` (package-grades) or with edits to a record's title.
    """
    module = report_class.__module__
    if '.settings.' in module:
        root = module.rsplit('.settings.', 1)[0]
    else:
        root = module.rsplit('.', 1)[0]
    parts = []
    for part in root.split('.'):
        if not parts or parts[-1] != part:  # collapse the nested-submodule repeat
            parts.append(part)
    return f"{'.'.join(parts)}:{report_class.__name__}"


def _configurator_of(record):
    """The record's configurator identifier, or None when its class won't import."""
    try:
        return configurator_id(_report_class(record))
    except Exception:
        return None


def _key_of(record):
    """The configurator's Setting key, or None when its class won't import."""
    try:
        return _report_class(record).key
    except Exception:
        return None


def resolve_record(ref):
    """The SettingRecord named by a record UUID, a configurator identifier
    ('drop_wd:drop_wd_email', #5), a configurator key, or a record name that is
    unique. Returns (record, report_class)."""
    try:
        record = SettingRecord.objects.filter(pk=uuid.UUID(str(ref))).first()
    except ValueError:
        record = None

    if record is None:
        records = list(SettingRecord.objects.all())
        by_configurator = (
            [r for r in records if _configurator_of(r) == ref] if ':' in str(ref) else [])
        by_key = [r for r in records if _key_of(r) == ref]
        by_name = [r for r in records if r.name == ref]
        matches = by_configurator or by_key or by_name
        if len(matches) > 1:
            raise ParseError(
                f'"{ref}" matches more than one setting; use its key or '
                f'record_id: ' + ', '.join(str(r.id) for r in matches))
        record = matches[0] if matches else None

    if record is None:
        raise NotFound(f'No setting "{ref}".')
    try:
        return record, _report_class(record)
    except Exception as exc:
        raise NotFound(f'Setting "{ref}" could not be loaded: {exc}')


def _latest_history(setting):
    if setting is None:
        return None
    return setting.history.order_by('-history_id').first()


def _version(setting):
    latest = _latest_history(setting)
    return str(latest.history_id) if latest else None


def _detail(record, report_class):
    setting = Setting.objects.filter(key=report_class.key).first()
    latest = _latest_history(setting)
    return {
        'key': report_class.key,
        'configurator': configurator_id(report_class),
        'record_id': str(record.id),
        'name': record.name,
        'app': record.app,
        'title': record.title,
        'description': record.description,
        'value': setting.value if setting else None,
        'updated_at': latest.history_date.isoformat() if latest else None,
        'version': str(latest.history_id) if latest else None,
    }


def _stringify(value):
    """A scalar the way an HTML form would post it."""
    if value is None:
        return ''
    if isinstance(value, bool):
        return 'true' if value else 'false'
    if isinstance(value, (dict, list, tuple)):
        return json.dumps(value)
    return str(value)


def form_data(form):
    """Bind-ready data for `form`, from each field's effective initial value
    (the configurator's from_db() over the field's own initial), posted as the
    rendered HTML form would post it."""
    data = QueryDict(mutable=True)
    for name, field in form.fields.items():
        value = form[name].value()
        if getattr(field.widget, 'allow_multiple_selected', False):
            if value in (None, ''):
                value = []
            elif not isinstance(value, (list, tuple)):
                value = [value]
            data.setlist(name, [_stringify(v) for v in value])
        elif isinstance(value, bool) and not value:
            # An unchecked checkbox posts nothing.
            continue
        else:
            data[name] = _stringify(value)
    return data


def _errors(form):
    return {field: [force_str(m) for m in messages]
            for field, messages in form.errors.items()}


class _Rollback(Exception):
    """Raised inside the write transaction to undo it."""


class CanManageSettings(BasePermission):
    message = 'You do not have permission to manage settings.'

    def has_permission(self, request, view):
        return _user_can_manage_settings(request.user)


class SettingsAPIView(APIView):
    # Token first, so an anonymous call gets a 401 with WWW-Authenticate.
    authentication_classes = [TokenAuthentication, SessionAuthentication]
    permission_classes = [IsAuthenticated, CanManageSettings]
    pagination_class = None


class SettingListAPI(SettingsAPIView):
    def get(self, request):
        records = SettingRecord.objects.order_by('title')
        category = request.query_params.get('category')
        if category:
            records = records.filter(categories__icontains=category)
        app = request.query_params.get('app')
        if app:
            records = records.filter(app=app)

        records = list(records)
        configurators = {r.id: _configurator_of(r) for r in records}
        configurator = request.query_params.get('configurator')
        if configurator:
            records = [r for r in records if configurators[r.id] == configurator]
        keys = {r.id: _key_of(r) for r in records}
        stored = set(Setting.objects.filter(
            key__in=[k for k in keys.values() if k]).values_list('key', flat=True))
        return Response([{
            'id': str(r.id),
            'key': keys[r.id],
            'configurator': configurators[r.id],
            'name': r.name,
            'app': r.app,
            'title': r.title,
            'description': r.description,
            'categories': list(r.categories),
            'has_value': keys[r.id] in stored,
            'importable': keys[r.id] is not None,
        } for r in records])


class SettingDetailAPI(SettingsAPIView):

    def get(self, request, ref):
        record, report_class = resolve_record(ref)
        payload = _detail(record, report_class)
        return Response(payload, headers=self._etag(payload['version']))

    def put(self, request, ref):
        return self._write(request, ref, merge=False)

    def patch(self, request, ref):
        return self._write(request, ref, merge=True)

    @staticmethod
    def _etag(version):
        return {'ETag': f'"{version}"'} if version else {}

    def _write(self, request, ref, merge):
        record, report_class = resolve_record(ref)
        key = report_class.key
        if not can_edit_setting_key(request.user, key):
            raise PermissionDenied('You may not change this setting.')

        body = request.data
        submitted = body.get('value') if isinstance(body, dict) else None
        if not isinstance(submitted, dict):
            raise ParseError('Body must be {"value": {...}}.')

        dry_run = _flag(request, 'dry_run')
        allow_unknown = _flag(request, 'allow_unknown')
        if_match = request.headers.get('If-Match')
        result = {}

        try:
            with transaction.atomic():
                setting = (Setting.objects.select_for_update()
                           .filter(key=key).first())

                if if_match is not None:
                    current = _version(setting)
                    wanted = if_match.strip().removeprefix('W/').strip('"')
                    ok = (setting is not None) if wanted == '*' else wanted == current
                    if not ok:
                        result['response'] = Response(
                            {'detail': 'The setting changed since you read it.',
                             'version': current},
                            status=status.HTTP_412_PRECONDITION_FAILED)
                        raise _Rollback

                stored = (setting.value if setting and isinstance(setting.value, dict)
                          else {})
                candidate = {**stored, **submitted} if merge else dict(submitted)

                # Stage the candidate so the configurator's from_db() can turn
                # it into form data. Not recorded: only the final save is.
                if setting is None:
                    setting = Setting(key=key)
                setting.value = candidate
                setting.skip_history_when_saving = True
                try:
                    setting.save()
                finally:
                    del setting.skip_history_when_saving

                try:
                    initial = report_class.from_db()
                    form = report_class(request._request, initial=initial)
                    data = form_data(form)
                    form = report_class(request._request, data)
                    valid = form.is_valid()
                except Exception as exc:
                    logger.exception('Settings API could not load %s', key)
                    result['response'] = Response(
                        {'errors': {'__all__': [
                            f'The value could not be loaded by the configurator: {exc}']}},
                        status=status.HTTP_400_BAD_REQUEST)
                    raise _Rollback

                if not valid:
                    result['response'] = Response(
                        {'errors': _errors(form)},
                        status=status.HTTP_400_BAD_REQUEST)
                    raise _Rollback

                form.run_record()
                saved = Setting.objects.get(key=key)
                value = saved.value if isinstance(saved.value, dict) else {}

                unknown = sorted(k for k in submitted if k not in value)
                if unknown:
                    if not allow_unknown:
                        result['response'] = Response(
                            {'errors': {'__unknown__': [
                                f'Not a field of this setting: {", ".join(unknown)}. '
                                f'Pass ?allow_unknown=1 to keep them.']}},
                            status=status.HTTP_400_BAD_REQUEST)
                        raise _Rollback
                    saved.value = {**value, **{k: submitted[k] for k in unknown}}
                    # Fold into the history row run_record() just wrote.
                    saved.skip_history_when_saving = True
                    saved.save()
                    latest = _latest_history(saved)
                    if latest is not None:
                        latest.value = saved.value
                        latest.save(update_fields=['value'])

                if dry_run:
                    result['response'] = Response({
                        'dry_run': True,
                        'key': key,
                        'value': saved.value,
                        'dropped_keys': sorted(k for k in stored if k not in saved.value),
                    })
                    raise _Rollback
        except _Rollback:
            return result['response']

        payload = _detail(record, report_class)
        return Response(payload, headers=self._etag(payload['version']))


class SettingSchemaAPI(SettingsAPIView):
    def get(self, request, ref):
        record, report_class = resolve_record(ref)
        form = report_class(request._request, initial=report_class.from_db())
        fields = []
        for name, field in form.fields.items():
            choices = getattr(field, 'choices', None)
            fields.append({
                'name': name,
                'label': force_str(field.label) if field.label else name,
                'type': type(field).__name__,
                'widget': type(field.widget).__name__,
                'required': field.required,
                'disabled': field.disabled,
                'multiple': bool(getattr(field.widget, 'allow_multiple_selected', False)),
                'choices': ([[force_str(v), force_str(l)] for v, l in choices]
                            if choices is not None else None),
                'help_text': force_str(field.help_text) if field.help_text else '',
                'initial': _jsonable(form[name].value()),
            })
        return Response({'key': report_class.key,
                         'configurator': configurator_id(report_class),
                         'record_id': str(record.id),
                         'fields': fields})


def _jsonable(value):
    try:
        json.dumps(value)
        return value
    except TypeError:
        return force_str(value)


class SettingHistoryAPI(SettingsAPIView):
    def get(self, request, ref):
        record, report_class = resolve_record(ref)
        setting = Setting.objects.filter(key=report_class.key).first()
        if setting is None:
            return Response([])
        return Response([{
            'id': h.history_id,
            'date': h.history_date.isoformat(),
            'user': str(h.history_user) if h.history_user else None,
            'action': h.get_history_type_display(),
            'value': h.value,
        } for h in setting.history.order_by('-history_id')])
