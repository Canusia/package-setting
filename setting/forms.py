import logging
from django import forms
from django.conf import settings
from django.forms import ValidationError
from django.utils.translation import gettext_lazy as _
from django.utils.module_loading import import_string

from .models.setting import SettingRecord

LOGGER = logging.getLogger(__name__)

class AddSettingForm(forms.ModelForm):
    description = forms.CharField(
        widget=forms.Textarea()
    )

    class Meta:
        model = SettingRecord
        fields = [
            'name',
            'title',
            'description',
            'categories'
        ]

    def clean_name(self):
        report_name = self.cleaned_data['name']
        try:
            reports_path = getattr(settings, 'MY_CE').get('settings_repo', '')
            report_class = import_string(f'{reports_path}.{report_name}.{report_name}')
            return report_name
        except (ModuleNotFoundError, ImportError) as e:
            LOGGER.error(e)
            raise ValidationError(
                _(f"The setting file name was not found in {report_class}. Please check and try again")
            )
