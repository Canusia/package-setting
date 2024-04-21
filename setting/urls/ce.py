"""
    Support Ticket CE URL Configuration
"""
from django.urls import path

from ..views.views import (
    record_details,
    records_in_category,
    run_record,
    records,
    show_preview,
    add_new as add_new_setting
)

app_name = 'setting'

urlpatterns = [
    path('', records, name='records'),
    path('records_in_category/', records_in_category, name='records_in_category'),
    path('record_details/', record_details, name='record_details'),
    path('show_preview/', show_preview, name='show_preview'),
    path('run_record/<uuid:record_id>', run_record, name='run_record'),

    path('add_new', add_new_setting, name='add_new'),
]
