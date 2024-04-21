from django.contrib import admin

from .models.setting import SettingRecord

# Register your models here.
@admin.register(SettingRecord)
class SettingRecordAdmin(admin.ModelAdmin):
    list_display = (
        'name', 'title', 'categories'
    )
    fields = [
        'name',
        'title',
        'description',
        'categories'
    ]