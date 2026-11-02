from django.apps import AppConfig


class SettingConfig(AppConfig):
    name = 'setting'

    def ready(self):
        from . import menu  # noqa: F401  sidebar items (cis.menu_registry)

class DevSettingConfig(AppConfig):
    name = 'setting.setting'

    def ready(self):
        from . import menu  # noqa: F401  sidebar items (cis.menu_registry)

