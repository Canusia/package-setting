MyCE - Setting
====================

Dynamic settings/configurator registry and management interface for Django.
Apps register configurators via ``CONFIGURATORS`` attribute, which are then
managed through a centralized UI with inline editing and change tracking.

Features
--------
- Dynamic setting registration via ``AppConfig.CONFIGURATORS``
- AJAX-driven forms with crispy-forms rendering
- Three-tab detail view: Description, Setting (raw JSON), Change Log
- Superuser inline editing of title, description, and raw JSON value
- Copy JSON to clipboard
- Change history tracking via ``django-simple-history``
- Change Log DataTable with date, user, action, and value snapshot

Installation
------------

1. Add the app to ``INSTALLED_APPS`` in ``settings.py``::

    # Production
    'setting.apps.SettingConfig'

    # Development (submodule)
    'setting.setting.apps.DevSettingConfig'

2. Add ``django-simple-history`` to ``INSTALLED_APPS`` and middleware::

    INSTALLED_APPS = [
        ...
        'simple_history',
    ]

    MIDDLEWARE = [
        ...
        'simple_history.middleware.HistoryRequestMiddleware',
    ]

3. Add ``HistoricalRecords`` to the ``Setting`` model in ``cis/models/settings.py``::

    from simple_history.models import HistoricalRecords

    class Setting(models.Model):
        key = models.CharField(max_length=50, unique=True)
        value = JSONField(blank=True)
        history = HistoricalRecords()

4. Add the static files path to ``STATICFILES_DIRS`` in ``settings.py``::

    import importlib.util

    def get_package_path(package_name):
        spec = importlib.util.find_spec(package_name)
        return os.path.dirname(spec.origin) if spec else None

    STATICFILES_DIRS = [
        ...
        # Submodule install
        os.path.join(get_package_path("setting.setting"), 'staticfiles')
        if importlib.util.find_spec('setting.setting')
        else os.path.join(get_package_path("setting"), 'staticfiles') if get_package_path("setting") else None,
    ]

5. In ``myce/urls.py``::

    path('ce/settings/', include('setting.urls.ce')),

7. Run migrations::

    python manage.py makemigrations cis
    python manage.py migrate

8. Register settings from all apps::

    python manage.py register_settings

Adding a Configurator
---------------------

1. Create ``{app}/settings/{name}.py``::

    from django import forms
    from django.conf import settings
    from django.http import JsonResponse
    from crispy_forms.helper import FormHelper
    from crispy_forms.layout import Submit
    from cis.models.settings import Setting

    class SettingForm(forms.Form):
        # Base form fields...

        def _to_python(self):
            return {field: self.cleaned_data[field] for field in self.fields}

    class my_setting(SettingForm):
        key = getattr(settings, 'CAMPUS_CODE_PREFIX') + "_my_setting"

        my_field = forms.CharField(...)

        def __init__(self, request, *args, **kwargs):
            super().__init__(*args, **kwargs)
            self.helper = FormHelper()
            self.helper.add_input(Submit('submit', 'Save Setting'))

        @classmethod
        def from_db(cls):
            try:
                return Setting.objects.get(key=cls.key).value
            except Setting.DoesNotExist:
                return {}

        def install(self):
            Setting.objects.get_or_create(
                key=self.key, defaults={'value': {'my_field': 'default'}})

        def run_record(self):
            setting, _ = Setting.objects.get_or_create(key=self.key)
            setting.value = self._to_python()
            setting.save()
            return JsonResponse({'message': 'Saved', 'status': 'success'})

2. Add to your app's ``AppConfig``::

    class MyAppConfig(AppConfig):
        CONFIGURATORS = [
            {
                'name': 'my_setting',
                'title': 'My Setting Title',
                'description': 'What this setting configures',
                'categories': '1,4',
                'app': 'myapp'
            }
        ]

3. Run ``python manage.py register_settings``

Management Commands
-------------------

- ``register_settings`` — Scan apps and register configurator definitions

Dependencies
------------
- Django 4.2+
- django-simple-history
- django-crispy-forms
- django-multiselectfield
