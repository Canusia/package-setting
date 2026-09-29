"""Tests for the add-setting admin flow.

Two defects live in the same block of `views.add_new`:

1. It referenced `reports_path` while assigning `report_path` — a name that is
   undefined in that scope, so `install()` raised NameError on every call and
   the bare `except: pass` swallowed it. Adding a setting through the UI never
   installed its defaults, and the admin was told it succeeded.

2. Once that typo is fixed, `install()` becomes reachable — and it was called
   with no check for an existing stored value, so re-adding a setting would
   overwrite a tenant's customised configuration (Canusia/package-setting#3).

The two must be fixed together: fixing the typo alone turns a dead call into a
live, unguarded one.
"""
import uuid

from django.contrib.auth import get_user_model
from django.contrib.auth.models import Group
from django.contrib.auth.signals import user_logged_in
from django.test import TestCase
from django.urls import reverse

from cis.models.settings import Setting

try:
    from django_login_history.models import post_login as _login_history_post_login
except Exception:  # pragma: no cover
    _login_history_post_login = None

User = get_user_model()

# A real settings module that ships with cis, so import_string resolves.
SETTING_APP = 'cis'
SETTING_NAME = 'support_docs'
SETTING_KEY = 'cis.settings.support_docs'


def _sfx():
    return uuid.uuid4().hex[:8]


class AddSettingInstallTests(TestCase):

    @classmethod
    def setUpClass(cls):
        # force_login's bare request crashes django_login_history's receiver;
        # same disconnect the cis view tests use.
        if _login_history_post_login is not None:
            user_logged_in.disconnect(_login_history_post_login)
        super().setUpClass()

    @classmethod
    def tearDownClass(cls):
        super().tearDownClass()
        if _login_history_post_login is not None:
            user_logged_in.connect(_login_history_post_login)

    def setUp(self):
        self.user = User.objects.create_user(
            username=f'ce_{_sfx()}', email=f'ce_{_sfx()}@x.com', password='x')
        self.user.groups.add(Group.objects.get_or_create(name='ce')[0])
        self.user.save()

        self.client = self.client_class(REMOTE_ADDR='127.0.0.1')
        self.client.force_login(self.user)

        Setting.objects.filter(key=SETTING_KEY).delete()

    def _post(self):
        return self.client.post(reverse('setting:add_new'), {
            'app': SETTING_APP,
            'name': SETTING_NAME,
            'title': 'Support Docs',
            'description': 'Support document types and statuses',
            'categories': '1',
        })

    def test_adding_a_setting_installs_its_defaults(self):
        """The NameError guard: install() must actually run."""
        self._post()

        setting = Setting.objects.filter(key=SETTING_KEY).first()
        self.assertIsNotNone(
            setting,
            'add_new did not install the setting — install() is not running')
        self.assertIn('types', setting.value)

    def test_readding_does_not_overwrite_a_customised_value(self):
        """The #3 guard: a live value must survive a re-add."""
        Setting.objects.create(
            key=SETTING_KEY,
            value={'types': ['Tenant Custom Type'], 'statuses': ['Approved']})

        self._post()

        setting = Setting.objects.get(key=SETTING_KEY)
        self.assertEqual(setting.value['types'], ['Tenant Custom Type'])
        self.assertEqual(setting.value['statuses'], ['Approved'])


class MultiCampusUpdateSettingTests(TestCase):
    """cis #30 (MC-06): in multi-campus mode a campus's settings admin may
    change only that campus's settings; shared keys and the shared
    title/description are superuser-only. Single-campus is unchanged."""

    def setUp(self):
        from django.conf import settings as dj_settings
        from cis.models.course import Campus
        from .models.setting import SettingRecord
        self.campus = Campus.objects.create(
            name=f'C1-{_sfx()}', code=f'{dj_settings.CAMPUS_CODE_PREFIX}-{_sfx()}')
        self.user = User.objects.create_user(
            username=f'ce_{_sfx()}', email=f'ce_{_sfx()}@x.com', password='x')
        self.user.groups.add(Group.objects.get_or_create(name='ce')[0])
        self.user.campus = {'manage_settings': 'Yes'}
        self.user.save()
        self.user.set_process_campuses([str(self.campus.id)])
        self.record = SettingRecord.objects.create(
            app=SETTING_APP, name=SETTING_NAME, title='Support Docs',
            description='d')
        Setting.objects.filter(key=SETTING_KEY).delete()

    def _post(self, **data):
        from django.test import RequestFactory
        from cis.campus_context import campus_context
        from .views.views import update_setting
        request = RequestFactory().post('/', {
            'record_id': str(self.record.id), 'title': 'Support Docs',
            'description': 'd', **data})
        request.user = self.user
        with campus_context(self.campus):
            return update_setting(request)

    def test_single_campus_staff_edit_as_before(self):
        response = self._post(title='Renamed', setting_value='{"types": []}')
        self.assertEqual(response.status_code, 200)
        self.record.refresh_from_db()
        self.assertEqual(self.record.title, 'Renamed')

    def test_multi_campus_staff_cannot_change_shared_key_or_title(self):
        from django.test import override_settings
        with override_settings(MULTI_CAMPUS=True):
            self.assertEqual(self._post(title='Renamed').status_code, 403)
            self.assertEqual(
                self._post(setting_value='{"types": []}').status_code, 403)
        self.record.refresh_from_db()
        self.assertEqual(self.record.title, 'Support Docs')
        self.assertFalse(Setting.objects.filter(key=SETTING_KEY).exists())
