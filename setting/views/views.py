import logging

from django.conf import settings
from django.db import IntegrityError
from django.db.models import Q
from django.contrib import messages
from django.contrib.auth.decorators import user_passes_test, login_required
from django.utils.module_loading import import_string
from django.http import Http404, JsonResponse

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

user_passes_test(user_has_cis_role, login_url='/')


def add_new(request):
    '''
    Add new page
    '''

    if not request.user.can_edit_users:
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
                # reports_path = getattr(settings, 'MY_CE').get(
                #     'settings_repo', '')
                report_path = request.POST.get("app", 'cis') + '.settings'
                report_name = request.POST.get("name")
                report_class = import_string(f'{reports_path}.{report_name}.{report_name}')

                report = report_class(request)
                report.install()
            except:
                pass

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

    if not request.user.can_edit_users:
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
    category = request.GET.get('category', None)
    if category:
        records_available = SettingRecord.get_records_in_category(
            category, request.user)
    else:
        records_available = {}
    return JsonResponse(records_available)


def record_details(request, report_id=None):

    if not request.user.can_edit_users:
        messages.add_message(
            request,
            messages.SUCCESS,
            'You do not have permission to edit this',
            'list-group-item-danger')
        return redirect('cis:dashboard')

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

        report_html = render_to_string(
            'setting/setting.html',
            {
                'form_html': form_html,
                'title': report.title,
                'description': report.description + '<br><p class="alert text-white">' + report_name + '</p>'
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

def show_preview(request):
    report_name = request.GET.get('setting')
    field_name = request.GET.get('field')

    try:
        # reports_path = getattr(settings, 'MY_CE').get('settings_repo', '')
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
    if request.method == 'POST':
        report = get_object_or_404(SettingRecord, pk=record_id)
        report_name = report.name

        try:
            # reports_path = getattr(settings, 'MY_CE').get('settings_repo', '')
            reports_path = report.app + '.settings'
            report_class = import_string(f'{reports_path}.{report_name}.{report_name}')

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
