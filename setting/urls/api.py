"""
    Settings API URL Configuration (package-setting#4).

    The host mounts this at api/v1/settings/.
"""
from django.urls import path

from ..views.api import (
    SettingDetailAPI, SettingHistoryAPI, SettingListAPI, SettingSchemaAPI)

app_name = 'setting_api'


def _api(view_class):
    view = view_class.as_view()
    # Token callers have no session; cis's LoginRequiredMiddleware would
    # redirect them to '/' before DRF authenticates the token.
    view.login_required = False
    return view


urlpatterns = [
    path('', _api(SettingListAPI), name='list'),
    path('<str:ref>/', _api(SettingDetailAPI), name='detail'),
    path('<str:ref>/schema/', _api(SettingSchemaAPI), name='schema'),
    path('<str:ref>/history/', _api(SettingHistoryAPI), name='history'),
]
