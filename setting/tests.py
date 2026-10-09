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
from django.test import SimpleTestCase, TestCase
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


# --- Settings API (package-setting#4) ---------------------------------------

import importlib.util

from django.test import override_settings
from rest_framework.authtoken.models import Token
from rest_framework.test import APIClient

_CV_APP = ('class_visit.class_visit' if importlib.util.find_spec('class_visit.class_visit')
           else 'class_visit')
try:
    _CV_CLASS = __import__(f'{_CV_APP}.settings.class_visit',
                           fromlist=['class_visit']).class_visit
except Exception:  # pragma: no cover - tenant without class_visit
    _CV_CLASS = None

CV_KEY = 'class_visit'
BAD_SELECT = '[{"name": "q1", "label": "Q1", "type": "select"}]'


class SettingsAPITests(TestCase):
    """Token API over the configurators: reads, validated writes, dry runs,
    If-Match, history attribution and permissions."""

    def setUp(self):
        from .models.setting import SettingRecord
        self.admin = User.objects.create_user(
            username=f'su_{_sfx()}', email=f'su_{_sfx()}@x.com', password='x',
            is_superuser=True)
        self.nobody = User.objects.create_user(
            username=f'no_{_sfx()}', email=f'no_{_sfx()}@x.com', password='x')

        self.docs_record = SettingRecord.objects.create(
            app=SETTING_APP, name=SETTING_NAME, title='Support Docs',
            description='d', categories='1')
        Setting.objects.filter(key=SETTING_KEY).delete()
        Setting.objects.create(key=SETTING_KEY, value={
            'types': ['Transcript'], 'statuses': ['Pending', 'Approved'],
            'email_enabled': 'No', 'status_change_email_subject': 's',
            'status_change_email': 'b', 'satisfying_statuses': [],
            'document_check_registration_statuses': ['applied'],
        })

        if _CV_CLASS is not None:
            self.cv_record = SettingRecord.objects.create(
                app=_CV_APP, name='class_visit', title='Class Visit',
                description='d', categories='3')
            Setting.objects.filter(key=CV_KEY).delete()
            _CV_CLASS().install()

        self.api = self._client(self.admin)

    def _client(self, user=None):
        client = APIClient(REMOTE_ADDR='127.0.0.1')
        if user is not None:
            token, _ = Token.objects.get_or_create(user=user)
            client.credentials(HTTP_AUTHORIZATION=f'Token {token.key}')
        return client

    @staticmethod
    def _url(ref, suffix=''):
        return f'/api/v1/settings/{ref}/{suffix}'

    def _need_cv(self):
        if _CV_CLASS is None:
            self.skipTest('class_visit is not installed')

    def _cv_value(self):
        return Setting.objects.get(key=CV_KEY).value

    # -- read ---------------------------------------------------------------
    def test_superuser_token_reads_value_as_json(self):
        self._need_cv()
        response = self.api.get(self._url(CV_KEY))
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()['value'], self._cv_value())
        self.assertEqual(response.json()['record_id'], str(self.cv_record.id))
        self.assertTrue(response.json()['version'])
        self.assertEqual(response['ETag'], f'"{response.json()["version"]}"')

    def test_lookup_by_key_name_and_record_id_agree(self):
        by_key = self.api.get(self._url(SETTING_KEY)).json()
        by_name = self.api.get(self._url(SETTING_NAME)).json()
        by_id = self.api.get(self._url(self.docs_record.id)).json()
        self.assertEqual(by_key, by_name)
        self.assertEqual(by_key, by_id)

    def test_unknown_ref_is_404(self):
        self.assertEqual(self.api.get(self._url('no_such_setting')).status_code, 404)

    def test_list_filters_by_category_and_app(self):
        rows = self.api.get('/api/v1/settings/', {'app': SETTING_APP}).json()
        row = next(r for r in rows if r['id'] == str(self.docs_record.id))
        self.assertEqual(row['key'], SETTING_KEY)
        self.assertTrue(row['has_value'])
        self.assertTrue(all(r['app'] == SETTING_APP for r in rows))

        rows = self.api.get('/api/v1/settings/', {'category': '1'}).json()
        self.assertIn(str(self.docs_record.id), [r['id'] for r in rows])
        if _CV_CLASS is not None:
            self.assertNotIn(str(self.cv_record.id), [r['id'] for r in rows])

    def test_schema_lists_form_fields(self):
        fields = {f['name']: f for f in
                  self.api.get(self._url(SETTING_KEY, 'schema/')).json()['fields']}
        self.assertEqual(fields['email_enabled']['type'], 'ChoiceField')
        self.assertIn(['Yes', 'Yes'], fields['email_enabled']['choices'])
        self.assertTrue(fields['document_check_registration_statuses']['multiple'])

    # -- write (custom validation: class_visit) --------------------------------
    def test_put_valid_value_saves(self):
        self._need_cv()
        value = self.api.get(self._url(CV_KEY)).json()['value']
        value['visit_types'] = 'Initial|Annual'
        response = self.api.put(self._url(CV_KEY), {'value': value}, format='json')
        self.assertEqual(response.status_code, 200, response.content)
        self.assertEqual(self._cv_value()['visit_types'], 'Initial|Annual')

    def test_put_invalid_report_fields_is_400_and_stores_nothing(self):
        self._need_cv()
        before = self._cv_value()
        value = dict(before, report_fields_json=BAD_SELECT)
        response = self.api.put(self._url(CV_KEY), {'value': value}, format='json')
        self.assertEqual(response.status_code, 400)
        self.assertIn('non-empty "options" list',
                      ' '.join(response.json()['errors']['report_fields_json']))
        self.assertEqual(self._cv_value(), before)

    def test_patch_changes_only_the_given_key(self):
        self._need_cv()
        before = self._cv_value()
        response = self.api.patch(
            self._url(CV_KEY), {'value': {'is_active': 'Debug'}}, format='json')
        self.assertEqual(response.status_code, 200, response.content)
        after = self._cv_value()
        self.assertEqual(after['is_active'], 'Debug')
        changed = {k for k in after if after[k] != before.get(k)}
        self.assertEqual(changed, {'is_active'})

    def test_dry_run_never_saves_or_records_history(self):
        self._need_cv()
        setting = Setting.objects.get(key=CV_KEY)
        before, history = setting.value, setting.history.count()
        response = self.api.patch(
            self._url(CV_KEY) + '?dry_run=1',
            {'value': {'is_active': 'Debug'}}, format='json')
        self.assertEqual(response.status_code, 200, response.content)
        self.assertTrue(response.json()['dry_run'])
        self.assertEqual(response.json()['value']['is_active'], 'Debug')
        setting.refresh_from_db()
        self.assertEqual(setting.value, before)
        self.assertEqual(setting.history.count(), history)

        bad = self.api.patch(
            self._url(CV_KEY) + '?dry_run=1',
            {'value': {'report_fields_json': BAD_SELECT}}, format='json')
        self.assertEqual(bad.status_code, 400)

    def test_stale_if_match_is_refused(self):
        self._need_cv()
        version = self.api.get(self._url(CV_KEY)).json()['version']
        first = self.api.patch(self._url(CV_KEY), {'value': {'is_active': 'Yes'}},
                               format='json', HTTP_IF_MATCH=f'"{version}"')
        self.assertEqual(first.status_code, 200, first.content)
        stale = self.api.patch(self._url(CV_KEY), {'value': {'is_active': 'No'}},
                               format='json', HTTP_IF_MATCH=f'"{version}"')
        self.assertEqual(stale.status_code, 412)
        self.assertEqual(self._cv_value()['is_active'], 'Yes')

    def test_write_is_in_change_log_with_api_user(self):
        self._need_cv()
        setting = Setting.objects.get(key=CV_KEY)
        count = setting.history.count()
        self.api.patch(self._url(CV_KEY), {'value': {'is_active': 'Debug'}},
                       format='json')
        self.assertEqual(setting.history.count(), count + 1)
        latest = setting.history.order_by('-history_id').first()
        self.assertEqual(latest.history_user, self.admin)
        self.assertEqual(latest.value['is_active'], 'Debug')

        entries = self.api.get(self._url(CV_KEY, 'history/')).json()
        self.assertEqual(entries[0]['user'], str(self.admin))
        self.assertEqual(entries[0]['value']['is_active'], 'Debug')

    # -- write (generic path: stored shape differs from form shape) -----------
    def test_generic_configurator_round_trips(self):
        value = self.api.get(self._url(SETTING_KEY)).json()['value']
        value['statuses'] = ['Pending', 'Approved', 'Rejected']
        response = self.api.put(self._url(SETTING_KEY), {'value': value}, format='json')
        self.assertEqual(response.status_code, 200, response.content)
        stored = Setting.objects.get(key=SETTING_KEY).value
        self.assertEqual(stored['statuses'], ['Pending', 'Approved', 'Rejected'])
        self.assertEqual(stored['document_check_registration_statuses'], ['applied'])

    def test_generic_configurator_rejects_bad_choice(self):
        response = self.api.patch(
            self._url(SETTING_KEY), {'value': {'email_enabled': 'Maybe'}}, format='json')
        self.assertEqual(response.status_code, 400)
        self.assertIn('email_enabled', response.json()['errors'])
        self.assertEqual(Setting.objects.get(key=SETTING_KEY).value['email_enabled'], 'No')

    def test_unknown_keys_rejected_unless_allowed(self):
        response = self.api.patch(
            self._url(SETTING_KEY), {'value': {'bogus': 1}}, format='json')
        self.assertEqual(response.status_code, 400)
        self.assertIn('bogus', response.json()['errors']['__unknown__'][0])
        self.assertNotIn('bogus', Setting.objects.get(key=SETTING_KEY).value)

        response = self.api.patch(
            self._url(SETTING_KEY) + '?allow_unknown=1',
            {'value': {'bogus': 1}}, format='json')
        self.assertEqual(response.status_code, 200, response.content)
        self.assertEqual(Setting.objects.get(key=SETTING_KEY).value['bogus'], 1)

    def test_malformed_body_is_400(self):
        response = self.api.put(self._url(SETTING_KEY), {'types': []}, format='json')
        self.assertEqual(response.status_code, 400)

    # -- permissions -----------------------------------------------------------
    def test_no_token_is_401(self):
        response = self._client().get(self._url(SETTING_KEY))
        self.assertEqual(response.status_code, 401)

    def test_token_without_rights_is_403(self):
        client = self._client(self.nobody)
        self.assertEqual(client.get(self._url(SETTING_KEY)).status_code, 403)
        response = client.patch(
            self._url(SETTING_KEY), {'value': {'email_enabled': 'Yes'}}, format='json')
        self.assertEqual(response.status_code, 403)
        self.assertEqual(Setting.objects.get(key=SETTING_KEY).value['email_enabled'], 'No')

    def test_multi_campus_staff_cannot_write_shared_key(self):
        from django.conf import settings as dj_settings
        from rest_framework.test import APIRequestFactory, force_authenticate
        from cis.campus_context import campus_context
        from cis.models.course import Campus
        from .views.api import SettingDetailAPI

        campus = Campus.objects.create(
            name=f'C1-{_sfx()}', code=f'{dj_settings.CAMPUS_CODE_PREFIX}-{_sfx()}')
        staff = User.objects.create_user(
            username=f'ce_{_sfx()}', email=f'ce_{_sfx()}@x.com', password='x')
        staff.groups.add(Group.objects.get_or_create(name='ce')[0])
        staff.campus = {'manage_settings': 'Yes'}
        staff.save()
        staff.set_process_campuses([str(campus.id)])

        request = APIRequestFactory().patch(
            '/', {'value': {'email_enabled': 'Yes'}}, format='json')
        force_authenticate(request, user=staff)
        with override_settings(MULTI_CAMPUS=True), campus_context(campus):
            response = SettingDetailAPI.as_view()(request, ref=SETTING_KEY)
        self.assertEqual(response.status_code, 403)
        self.assertEqual(Setting.objects.get(key=SETTING_KEY).value['email_enabled'], 'No')

    # -- #5: lookup and listing by configurator identifier --------------------
    DOCS_ID = 'cis:support_docs'

    def test_list_carries_and_filters_by_configurator(self):
        rows = self.api.get('/api/v1/settings/', {'configurator': self.DOCS_ID}).json()
        self.assertEqual([r['id'] for r in rows], [str(self.docs_record.id)])
        self.assertEqual(rows[0]['configurator'], self.DOCS_ID)

    def test_lookup_by_configurator_matches_lookup_by_key(self):
        by_id = self.api.get(self._url(self.DOCS_ID))
        self.assertEqual(by_id.status_code, 200, by_id.content)
        self.assertEqual(by_id.json(), self.api.get(self._url(SETTING_KEY)).json())
        self.assertEqual(by_id.json()['configurator'], self.DOCS_ID)
        schema = self.api.get(self._url(self.DOCS_ID, 'schema/'))
        self.assertEqual(schema.json()['configurator'], self.DOCS_ID)

    def test_renaming_title_keeps_the_identifier(self):
        self.docs_record.title = 'Something Else'
        self.docs_record.save()
        self.assertEqual(self.api.get(self._url(self.DOCS_ID)).json()['configurator'],
                         self.DOCS_ID)

    def test_write_by_configurator_honours_dry_run_and_if_match(self):
        self._need_cv()
        ref = 'class_visit:class_visit'
        before = self._cv_value()
        dry = self.api.patch(self._url(ref) + '?dry_run=1',
                             {'value': {'is_active': 'Debug'}}, format='json')
        self.assertEqual(dry.status_code, 200, dry.content)
        self.assertEqual(self._cv_value(), before)

        version = self.api.get(self._url(ref)).json()['version']
        ok = self.api.patch(self._url(ref), {'value': {'is_active': 'Yes'}},
                            format='json', HTTP_IF_MATCH=f'"{version}"')
        self.assertEqual(ok.status_code, 200, ok.content)
        stale = self.api.patch(self._url(ref), {'value': {'is_active': 'No'}},
                               format='json', HTTP_IF_MATCH=f'"{version}"')
        self.assertEqual(stale.status_code, 412)

    def test_permissions_apply_to_configurator_lookup(self):
        response = self._client(self.nobody).get(self._url(self.DOCS_ID))
        self.assertEqual(response.status_code, 403)

    def test_unimportable_record_lists_null_configurator(self):
        from .models.setting import SettingRecord
        SettingRecord.objects.create(app='no_such_app', name='gone', title='Gone',
                                     description='d', categories='1')
        rows = {r['name']: r for r in self.api.get('/api/v1/settings/').json()}
        self.assertIsNone(rows['gone']['configurator'])

    def test_ambiguous_configurator_is_400(self):
        from .models.setting import SettingRecord
        # Same configurator registered twice (different category, so the
        # (name, categories) uniqueness constraint allows it).
        SettingRecord.objects.create(app=SETTING_APP, name=SETTING_NAME, title='Dup',
                                     description='d', categories='2')
        self.assertEqual(self.api.get(self._url(self.DOCS_ID)).status_code, 400)


# -- #5: stable configurator identifier ------------------------------------------

def _fake_configurator(module, name):
    return type(name, (), {'__module__': module, 'key': f'{module}.{name}'})


class ConfiguratorIdTests(SimpleTestCase):
    """configurator_id() depends only on the class, not on layout or key (#5)."""

    def test_pip_and_dev_submodule_layouts_agree(self):
        from .views.api import configurator_id
        flat = _fake_configurator('drop_wd.settings.drop_wd_email', 'drop_wd_email')
        nested = _fake_configurator('drop_wd.drop_wd.settings.drop_wd_email', 'drop_wd_email')
        self.assertEqual(configurator_id(flat), 'drop_wd:drop_wd_email')
        self.assertEqual(configurator_id(nested), 'drop_wd:drop_wd_email')

    def test_tenant_prefixed_key_does_not_matter(self):
        from .views.api import configurator_id
        for prefix in ('EWU', 'LAMAR'):
            cls = _fake_configurator('grades.grades.settings.class_section_grades',
                                     'class_section_grades')
            cls.key = f'{prefix}_class_grades'
            self.assertEqual(configurator_id(cls), 'grades:class_section_grades')

    def test_self_rooted_and_non_adjacent_repeats(self):
        from .views.api import configurator_id
        self.assertEqual(configurator_id(_fake_configurator('cis.settings.support_docs',
                                                            'support_docs')), 'cis:support_docs')
        self.assertEqual(configurator_id(_fake_configurator('a.b.a.settings.x', 'x')), 'a.b.a:x')

    def test_module_without_settings_segment(self):
        from .views.api import configurator_id
        self.assertEqual(configurator_id(_fake_configurator('pkg.config', 'config')), 'pkg:config')


# -- Quick search index ------------------------------------------------------------

class SearchIndexTests(TestCase):
    """search_index/ feeds the settings quick search: every record with its
    fields' plain-text labels, help text and values, CE-only, and tolerant of
    a configurator that won't load."""

    @classmethod
    def setUpClass(cls):
        if _login_history_post_login is not None:
            user_logged_in.disconnect(_login_history_post_login)
        super().setUpClass()

    @classmethod
    def tearDownClass(cls):
        super().tearDownClass()
        if _login_history_post_login is not None:
            user_logged_in.connect(_login_history_post_login)

    def setUp(self):
        from .models.setting import SettingRecord
        self.ce_user = User.objects.create_user(
            username=f'ce_{_sfx()}', email=f'ce_{_sfx()}@x.com', password='x')
        self.ce_user.groups.add(Group.objects.get_or_create(name='ce')[0])
        self.ce_user.save()
        self.nobody = User.objects.create_user(
            username=f'no_{_sfx()}', email=f'no_{_sfx()}@x.com', password='x')

        self.record = SettingRecord.objects.create(
            app=SETTING_APP, name=SETTING_NAME, title='Support Docs',
            description='<b>Support</b> document types', categories='1')
        Setting.objects.filter(key=SETTING_KEY).delete()
        Setting.objects.create(key=SETTING_KEY, value={
            'types': ['Transcript'], 'statuses': ['Pending', 'Approved']})

        self.client = self.client_class(REMOTE_ADDR='127.0.0.1')

    def _get(self, user):
        self.client.force_login(user)
        return self.client.get(reverse('setting:search_index'))

    def test_requires_settings_rights(self):
        self.assertEqual(self._get(self.nobody).status_code, 403)

    def test_lists_record_with_its_fields(self):
        response = self._get(self.ce_user)
        self.assertEqual(response.status_code, 200)
        rows = {r['id']: r for r in response.json()['records']}
        row = rows[str(self.record.id)]
        self.assertEqual(row['title'], 'Support Docs')
        self.assertEqual(row['description'], 'Support document types')
        self.assertEqual(row['key'], SETTING_KEY)
        self.assertEqual(row['categories'], [{'key': '1', 'label': 'Students'}])
        self.assertTrue(row['fields'])
        for field in row['fields']:
            self.assertEqual(set(field), {'name', 'label', 'help_text', 'value', 'heading'})
            self.assertNotIn('<', field['label'])

    def test_unloadable_configurator_keeps_its_title_searchable(self):
        from .models.setting import SettingRecord
        gone = SettingRecord.objects.create(
            app='no_such_app', name='gone', title='Gone', description='d',
            categories='1')
        response = self._get(self.ce_user)
        self.assertEqual(response.status_code, 200)
        rows = {r['id']: r for r in response.json()['records']}
        self.assertEqual(rows[str(gone.id)]['title'], 'Gone')
        self.assertEqual(rows[str(gone.id)]['fields'], [])
        self.assertTrue(rows[str(self.record.id)]['fields'])


class SearchTextTests(SimpleTestCase):
    """A section header's HTML label is indexed as the words a user sees."""

    def test_html_label_becomes_plain_text(self):
        from .views.views import _search_text
        self.assertEqual(
            _search_text('<h3 class="mt-4">Parent Notification(s)</h3>'),
            'Parent Notification(s)')
        self.assertEqual(_search_text('Tom &amp; Jerry\n\n  <i>x</i>'), 'Tom & Jerry x')
        self.assertEqual(_search_text('abcdef', limit=3), 'abc')

    def test_heading_label_is_flagged(self):
        from django import forms
        from django.utils.safestring import mark_safe
        from .views.views import _is_heading
        header = forms.CharField(label=mark_safe('<h3 class="mt-4">Parent Notification(s)</h3>'))
        plain = forms.CharField(label='Parent/Counselor Email')
        self.assertTrue(_is_heading(header, ''))
        self.assertFalse(_is_heading(plain, 'x'))

    def test_credentials_are_not_indexed(self):
        from django import forms
        from .views.views import _is_secret
        self.assertTrue(_is_secret('sftp_login', forms.CharField(widget=forms.PasswordInput)))
        self.assertTrue(_is_secret('report_id', forms.CharField(widget=forms.HiddenInput)))
        for name in ('password', 'sftp_password', 'private_key', 'client_secret',
                     'api_key', 'apikey', 'access_token', 'secret_key',
                     'aws_secret_access_key'):
            self.assertTrue(_is_secret(name, forms.CharField()), name)
        # Email templates and blurbs about passwords are content, not credentials.
        for name in ('username', 'email_subject', 'bypass_review',
                     'post_password_reset_email', 'manage_password_blurb',
                     'token_expiry_days', 'sort_key'):
            self.assertFalse(_is_secret(name, forms.CharField()), name)

    def test_choice_values_are_indexed_as_their_labels(self):
        from django import forms
        from .views.views import _display_value
        status = forms.ChoiceField(choices=[('P', 'Pending'), ('A', 'Approved')])
        self.assertEqual(_display_value(status, 'A'), 'Approved')
        grouped = forms.ChoiceField(choices=[('Terms', [(17, 'Fall 2026'), (18, 'Spring 2027')])])
        self.assertEqual(_display_value(grouped, '17'), 'Fall 2026')
        many = forms.MultipleChoiceField(choices=[('P', 'Pending'), ('A', 'Approved')])
        self.assertEqual(_display_value(many, ['P', 'A']), 'Pending, Approved')
        # A select on a plain CharField, a value with no label, and no value.
        select = forms.CharField(widget=forms.Select(choices=[('y', 'Yes'), ('n', 'No')]))
        self.assertEqual(_display_value(select, 'n'), 'No')
        self.assertEqual(_display_value(status, 'gone'), 'gone')
        self.assertEqual(_display_value(status, None), '')
        self.assertEqual(_display_value(forms.CharField(), 'plain'), 'plain')


class SearchDisplayValueModelTests(TestCase):
    """A model select is indexed as the selected rows' labels."""

    def test_model_choice_values_are_indexed_as_their_labels(self):
        from django import forms
        from .views.views import _display_value
        a = Group.objects.create(name=f'Alpha {_sfx()}')
        b = Group.objects.create(name=f'Beta {_sfx()}')
        one = forms.ModelChoiceField(queryset=Group.objects.all())
        self.assertEqual(_display_value(one, a.pk), a.name)
        self.assertEqual(_display_value(one, a), a.name)
        many = forms.ModelMultipleChoiceField(queryset=Group.objects.all())
        self.assertEqual(_display_value(many, [str(a.pk), b.pk]), f'{a.name}, {b.name}')
        by_name = forms.ModelChoiceField(queryset=Group.objects.all(), to_field_name='name')
        self.assertEqual(_display_value(by_name, b.name), b.name)
        # A stored id with no row shows nothing in the select; index nothing.
        self.assertEqual(_display_value(one, 'not-a-pk'), '')
        self.assertEqual(_display_value(many, [a.pk, 987654321]), a.name)
