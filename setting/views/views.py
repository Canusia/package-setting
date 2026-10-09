import html
import json
import logging
import re

from django.conf import settings
from django.db import IntegrityError
from django.db.models import Q
from django.contrib import messages
from django.contrib.auth.decorators import user_passes_test, login_required
from django.utils.module_loading import import_string
from django.http import Http404, JsonResponse

from django.utils.encoding import force_str
from django.utils.html import strip_tags
from django.utils.safestring import mark_safe

from django.template.context_processors import csrf
from django.template.loader import render_to_string

from django.core.paginator import Paginator, EmptyPage, PageNotAnInteger
from django.shortcuts import get_object_or_404, redirect, render
from django.http import JsonResponse

from cis.models.settings import Setting
from cis.utils import user_has_cis_role

from crispy_forms.utils import render_crispy_form

from cis.utils import (
    user_has_cis_role, user_has_highschool_admin_role
)
from ..models.setting import SettingRecord
from ..forms import AddSettingForm

from cis.menu import cis_menu, draw_menu, HS_ADMIN_MENU

logger = logging.getLogger(__name__)

try:
    # package-cis >= v0.1.0a: per-campus settings access (MC-06, cis #30).
    from cis.campus_gate import (
        can_edit_setting_descriptions, can_edit_setting_key,
        can_manage_settings as _user_can_manage_settings)
except ImportError:
    def _user_can_manage_settings(user):
        """All CE settings are CE-only to view/edit. Superusers (platform admins)
        retain access. Anonymous users are rejected (user_has_cis_role guards that)."""
        return user_has_cis_role(user) or getattr(user, 'is_superuser', False)

    def can_edit_setting_key(user, key):
        return _user_can_manage_settings(user)

    def can_edit_setting_descriptions(user):
        return _user_can_manage_settings(user)


def _settings_forbidden():
    return JsonResponse(
        {'status': 'error', 'message': 'Permission denied'}, status=403)


def add_new(request):
    '''
    Add new page
    '''

    if not _user_can_manage_settings(request.user):
        messages.add_message(
            request,
            messages.SUCCESS,
            'You do not have permission to edit this',
            'list-group-item-danger')
        return redirect('cis:dashboard')

    base_template = 'cis/logged-base.html'
    template = 'setting/add_new.html'
    ajax = request.GET.get('ajax', None)

    if request.method == 'POST':
        form = AddSettingForm(request.POST)
        if form.is_valid():
            record = form.save(commit=False)
            record.save()

            try:
                report_path = request.POST.get("app", 'cis') + '.settings'
                report_name = request.POST.get("name")
                report_class = import_string(f'{report_path}.{report_name}.{report_name}')

                report = report_class(request)

                # Seed defaults only when nothing is stored yet. SettingRecord
                # and Setting live in different tables and can drift apart, so
                # re-adding a setting through this form can land on a key that
                # already holds a tenant's customised configuration. install()
                # used to be reached unconditionally here, which would replace
                # it (Canusia/package-setting#3). register_settings guards its
                # own install() call the same way.
                if not Setting.objects.filter(key=report.key).exists():
                    report.install()
            except Exception:
                # Previously a bare `except: pass`, which reported success to
                # the admin whatever happened -- and hid the fact that this
                # block referenced an undefined `reports_path` and so raised
                # NameError on every call, meaning defaults were never
                # installed at all. Still non-fatal (the SettingRecord is
                # saved and the setting is editable), but no longer silent.
                logger.exception(
                    'Could not install defaults for setting %r in app %r',
                    request.POST.get('name'), request.POST.get('app'))
                messages.add_message(
                    request,
                    messages.WARNING,
                    'The setting was added, but its default values could not '
                    'be installed. Open it and save to set them.',
                    'list-group-item-warning')

            messages.add_message(
                request,
                messages.SUCCESS,
                'Successfully added setting',
                'list-group-item-success')
            return redirect('setting:add_new')
    else:
        form = AddSettingForm()

    return render(
        request,
        template, {
            'form': form,
            'page_title': "Add New",
            'labels': {
                'all_items': 'All Settings'
            },
            'urls': {
                'all_items': 'setting:records'
            },
            'ajax': ajax,
            'base_template': base_template,
            'menu': draw_menu(cis_menu, 'settings', 'settings')
        })


def records(request):
    template = 'setting/index.html'

    if not _user_can_manage_settings(request.user):
        messages.add_message(
            request,
            messages.SUCCESS,
            'You do not have permission to edit this',
            'list-group-item-danger')
        return redirect('cis:dashboard')

    menu = draw_menu(cis_menu, 'settings', 'settings')

    return render(
        request,
        template, {
            'categories': SettingRecord.CATEGORIES,
            'menu': menu
        })


@login_required(login_url='/')
def records_in_category(request):
    if not _user_can_manage_settings(request.user):
        return _settings_forbidden()

    category = request.GET.get('category', None)
    if category:
        records_available = SettingRecord.get_records_in_category(
            category, request.user)
    else:
        records_available = {}
    return JsonResponse(records_available)


def record_details(request, report_id=None):

    if not _user_can_manage_settings(request.user):
        return _settings_forbidden()

    if not report_id:
        report_id = request.GET.get('report_id', None)

    report = get_object_or_404(SettingRecord, pk=report_id)
    report_name = report.name

    try:
        # reports_path = getattr(settings, 'MY_CE').get('settings_repo', '')
        reports_path = report.app + '.settings'
        report_class = import_string(f'{reports_path}.{report_name}.{report_name}')

        initial = report_class.from_db()
        form = report_class(request, initial=initial)
        ctx = {}
        ctx.update(csrf(request))
        form_html = render_crispy_form(form, context=ctx)

        setting_json = '{}'
        try:
            setting_obj = Setting.objects.get(key=report_class.key)
            setting_json = json.dumps(setting_obj.value, indent=2)
        except Setting.DoesNotExist:
            pass

        report_html = render_to_string(
            'setting/setting.html',
            {
                'form_html': form_html,
                'title': report.title,
                'description': report.description + '<br><p class="alert text-white">' + report_name + '</p>',
                'raw_description': report.description,
                'is_superuser': request.user.is_superuser,
                'record_id': str(report.id),
                'setting_json': setting_json,
                'setting_key': report_class.key,
            }
        )
        data = {
            'status': 'success',
            'report': report_html,
        }
    except ModuleNotFoundError as e:
        logger.error(e)
        data = {
            'status': 'error',
            'message': 'Unable to locate report, ' + str(e)
        }
    except AttributeError as e:
        logger.error(e)
        data = {
            'status': 'error',
            'message': 'Unable to get report details ' + str(e)
        }
    return JsonResponse(data)

_SEARCH_VALUE_LIMIT = 2000


def _search_text(value, limit=None):
    """Plain, single-spaced text for the search index: tags stripped and
    entities decoded, so a label like '<h3>Parent Notification(s)</h3>' is
    indexed as the words a user sees."""
    text = ' '.join(html.unescape(strip_tags(force_str(value or ''))).split())
    if limit and len(text) > limit:
        text = text[:limit]
    return text


_HEADING_TAG = re.compile(r'<h[1-6][\s>]', re.IGNORECASE)


def _is_heading(field, value):
    """True for label-only section headers, e.g. a ReadOnlyField whose label is
    '<h3>Parent Notification(s)</h3>' and which renders no input."""
    if field.label and _HEADING_TAG.search(force_str(field.label)):
        return True
    return type(field.widget).__name__ == 'LongLabelWidget' and not value


@login_required(login_url='/')
def search_index(request):
    """Everything the settings quick search matches against, in one response:
    each record's title, description, categories and key, plus every form
    field's label, help text and current value. Fields are read from the
    configurator form without rendering it."""
    if not _user_can_manage_settings(request.user):
        return _settings_forbidden()

    from .api import _stringify

    category_labels = dict(SettingRecord.CATEGORIES)
    original_get = request.GET
    results = []

    for record in SettingRecord.objects.all().order_by('title'):
        entry = {
            'id': str(record.id),
            'title': record.title,
            'description': _search_text(record.description),
            'name': record.name,
            'key': '',
            'categories': [
                {'key': str(c), 'label': category_labels.get(str(c), str(c))}
                for c in (record.categories or [])],
            'fields': [],
        }
        try:
            report_class = import_string(
                f'{record.app}.settings.{record.name}.{record.name}')
            entry['key'] = force_str(getattr(report_class, 'key', '') or '')

            # Configurators build their form action from report_id, as they
            # would when record_details renders them.
            query = original_get.copy()
            query['report_id'] = str(record.id)
            request.GET = query

            form = report_class(request, initial=report_class.from_db())
            for name, field in form.fields.items():
                try:
                    value = form[name].value()
                    if isinstance(value, (list, tuple)):
                        value = ', '.join(_stringify(v) for v in value)
                    else:
                        value = _stringify(value)
                except Exception:
                    value = ''
                entry['fields'].append({
                    'name': name,
                    'label': _search_text(field.label) if field.label else '',
                    'help_text': _search_text(field.help_text),
                    'value': _search_text(value, _SEARCH_VALUE_LIMIT),
                    'heading': _is_heading(field, value),
                })
        except Exception as e:
            logger.warning(
                'Settings search could not index %s.%s: %s',
                record.app, record.name, e)
        finally:
            request.GET = original_get
        results.append(entry)

    return JsonResponse({'records': results})


def show_preview(request):
    if not _user_can_manage_settings(request.user):
        return _settings_forbidden()

    report_name = request.GET.get('setting')
    field_name = request.GET.get('field')

    try:
        report_names = report_name.split('.')
        if len(report_names) > 1:
            report_name = report_names[-1]
            app = report_names[0]

            if getattr(settings, 'DEBUG', False):
                app = f'{app}.{app}'

            report = get_object_or_404(SettingRecord, name=report_name, app=app)
        else:
            report = get_object_or_404(SettingRecord, name=report_name)

        reports_path = report.app + '.settings'        
        report_class = import_string(f'{reports_path}.{report_name}.{report_name}')

        initial = report_class.from_db()

        form = report_class(request, initial=initial)
        return form.preview(request, field_name)
    except Exception as e:
        print(e)
        logger.error(e)
        return JsonResponse({
            'message': 'Not found'
        }, status=400)
    
def run_record(request, record_id):
    if not _user_can_manage_settings(request.user):
        return _settings_forbidden()

    if request.method == 'POST':
        report = get_object_or_404(SettingRecord, pk=record_id)
        report_name = report.name

        try:
            # reports_path = getattr(settings, 'MY_CE').get('settings_repo', '')
            reports_path = report.app + '.settings'
            report_class = import_string(f'{reports_path}.{report_name}.{report_name}')

            if not can_edit_setting_key(request.user, report_class.key):
                return _settings_forbidden()

            form = report_class(request, request.POST)
            if form.is_valid():
                return form.run_record()
            else:
                return JsonResponse({
                    'message': 'Please correct the errors and try again.',
                    'errors': form.errors.as_json(),
                    'status': 'error'
                }, status=400)
        except ModuleNotFoundError as e:
            logger.error(e)
            return JsonResponse({
                'status': 'error',
                'message': 'Unable to locate report, ' + str(e)
            }, status=400)
        except Exception as e:
            logger.error(e)
            return JsonResponse({
                'message': 'Please correct the following errors and try again.',
                'details': 'Exception - ' + str(e),
                'status': 'error'
            }, status=400)

    return JsonResponse({
        'status': 'error',
        'message': 'Unable to locate setting,'
    }, status=400)

@login_required(login_url='/')
def update_setting(request):
    if not _user_can_manage_settings(request.user):
        return _settings_forbidden()

    if request.method != 'POST':
        return JsonResponse({'status': 'error', 'message': 'Invalid request'}, status=405)

    record_id = request.POST.get('record_id')
    record = get_object_or_404(SettingRecord, pk=record_id)

    title = request.POST.get('title', '').strip()
    description = request.POST.get('description', '').strip()
    setting_value = request.POST.get('setting_value', '').strip()

    if not title:
        return JsonResponse({'status': 'error', 'message': 'Title is required'}, status=400)

    # Titles and descriptions are shared by every campus.
    if (title, description) != (record.title, record.description):
        if not can_edit_setting_descriptions(request.user):
            return _settings_forbidden()
        record.title = title
        record.description = description
        record.save()

    if setting_value:
        try:
            parsed = json.loads(setting_value)
            report_name = record.name
            reports_path = record.app + '.settings'
            report_class = import_string(f'{reports_path}.{report_name}.{report_name}')
            if not can_edit_setting_key(request.user, report_class.key):
                return _settings_forbidden()
            setting_obj, created = Setting.objects.get_or_create(
                key=report_class.key, defaults={'value': parsed})
            setting_obj.value = parsed
            setting_obj.save()
        except json.JSONDecodeError:
            return JsonResponse({'status': 'error', 'message': 'Invalid JSON'}, status=400)

    return JsonResponse({'status': 'success', 'message': 'Setting updated successfully'})


@login_required(login_url='/')
def setting_history(request):
    if not _user_can_manage_settings(request.user):
        return JsonResponse({'data': []})

    setting_key = request.GET.get('setting_key', '')
    try:
        setting_obj = Setting.objects.get(key=setting_key)
        history = setting_obj.history.all().order_by('-history_date')
        records = []
        for h in history:
            records.append({
                'history_date': h.history_date.strftime('%Y-%m-%d %H:%M:%S'),
                'history_user': str(h.history_user) if h.history_user else '-',
                'history_type': h.get_history_type_display(),
                'value': json.dumps(h.value, indent=2),
            })
        return JsonResponse({'data': records})
    except Setting.DoesNotExist:
        return JsonResponse({'data': []})
