import importlib.util
import logging

from django.core.management.base import BaseCommand
from django.contrib.auth.models import Group
from django.conf import settings
from django.http import HttpRequest
from django.db.utils import IntegrityError
from django.utils.module_loading import import_string

if importlib.util.find_spec('setting.setting'):
    from setting.setting.models.setting import SettingRecord
else:
    from setting.models.setting import SettingRecord
logger = logging.getLogger(__name__)


class Command(BaseCommand):
    '''
    Registers settings in DB

    CATEGORIES = [
        (1, STUDENTS),
        (2, HIGH_SCHOOLS),
        (3, CLASSES),
        (4, MISC),
        (5, INSTRUCTORS)
    ]
    '''
    help = 'Registers settings in DB'


    def _install_record(self, report_class, name):
        """Construct and install one setting; True if its record should be saved.

        STRICT (per-campus) settings raise NoCampusContext under the shared
        scope in multi-campus mode; those are installed once per campus.
        """
        from cis.campus_context import NoCampusContext
        try:
            report = report_class(HttpRequest())
            try:
                print(f'Installing default {name}')
                report.install()
            except NoCampusContext:
                report = None
            except Exception:
                logger.exception('Could not install default %s', name)
                return True
            else:
                return True
        except NoCampusContext:
            report = None

        if not self._is_multi_campus():
            return False
        return self._install_per_campus(report_class, name)

    def _is_multi_campus(self):
        from cis.campus_context import is_multi_campus
        return is_multi_campus()

    def _install_per_campus(self, report_class, name):
        from cis.campus_context import campus_context
        from cis.campus_gate import _prefixed_campuses
        any_ok = False
        for campus in _prefixed_campuses().order_by('name'):
            with campus_context(campus):
                try:
                    print(f'Installing default {name} for {campus}')
                    report_class(HttpRequest()).install()
                    any_ok = True
                except Exception:
                    logger.exception(
                        'Could not install default %s for %s', name, campus)
        return any_ok

    def register(self, records):
        for record in records:
            if SettingRecord.objects.filter(name=record['name']).exists():
                print(f'\'{record["name"]}\' exists')
                continue
            try:
                reports_path = record.get('app', 'cis') + '.settings'
                report_name = record['name']

                report_class = import_string(f'{reports_path}.{report_name}.{report_name}')
                if not self._install_record(report_class, report_name):
                    print(f'Skipping {report_name}: could not be installed')
                    continue

                print(f'Adding {record["name"]}')
                SettingRecord(
                    app=record.get('app', 'cis'),
                    name=record['name'],
                    title=record['title'],
                    description=record['description'],
                    categories=record['categories']
                ).save()
            except Exception as e:
                logger.exception('Could not register setting %s', record.get('name'))
                print(f'Skipping {record.get("name")}: {e}')

    def handle(self, *args, **kwargs):
        # Per-campus settings (cis #129) install their defaults on the shared
        # row; with no campus set, reading them would otherwise raise.
        from cis.models.settings import shared_settings
        with shared_settings():
            self._register_all()

    def _register_all(self):
        apps = getattr(settings, 'INSTALLED_APPS')
        for app in apps:
            try:
                app_class = import_string(app)
                
                if app_class.CONFIGURATORS:
                    print(f'Found settings in {app}')
                    self.register(app_class.CONFIGURATORS)
            except:
                ...
