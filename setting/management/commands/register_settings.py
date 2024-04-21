from django.core.management.base import BaseCommand
from django.contrib.auth.models import Group
from django.conf import settings
from django.http import HttpRequest
from django.db.utils import IntegrityError
from django.utils.module_loading import import_string

from setting.models.setting import SettingRecord
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


    def register(self, records):
        for record in records:
             
            if not SettingRecord.objects.filter(name=record['name']).exists():
                reports_path = record.get('app', 'cis')
                report_name = record['name']

                report_class = import_string(f'{reports_path}.{report_name}.{report_name}')
                report = report_class(HttpRequest())
            
                db_record = SettingRecord(
                    app=record.get('app', 'cis'),
                    name=record['name'],
                    title=record['title'],
                    description=record['description'],
                    categories=record['categories']
                )
                try:
                    print(f'Adding {record["name"]}')
                    db_record.save()

                    try:
                        print(f'Installing default {record["name"]}')
                        report.install()
                    except Exception as e:
                        ...

                except Exception as e:
                    ...
            else:
                print(f'\'{record["name"]}\' exists')

    def handle(self, *args, **kwargs):
        apps = getattr(settings, 'INSTALLED_APPS')
        for app in apps:
            try:
                app_class = import_string(app)
                
                if app_class.CONFIGURATORS:
                    print(f'Found settings in {app}')
                    self.register(app_class.CONFIGURATORS)
            except:
                ...
