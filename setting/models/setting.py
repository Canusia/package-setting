# users/models.py
import os, uuid, datetime
from django.conf import settings

from django.db import models, IntegrityError
from multiselectfield import MultiSelectField

from cis.utils import user_has_cis_role, user_has_highschool_admin_role

class SettingRecord(models.Model):
    """
    SettingRecord model
    """
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)

    app = models.CharField(max_length=100, default='cis')

    name = models.CharField(max_length=100, blank=True)
    title = models.CharField(max_length=100, blank=True)
    description = models.CharField(max_length=200, blank=True)

    STUDENTS = 'Students'
    HIGH_SCHOOLS = 'High Schools'
    CLASSES = 'Classes'
    MISC = 'Misc.'
    INSTRUCTORS = 'Instructors'

    CATEGORIES = [
        (1, STUDENTS),
        (2, HIGH_SCHOOLS),
        (3, CLASSES),
        (4, MISC),
        (5, INSTRUCTORS)
    ]
    categories = MultiSelectField(
        choices=CATEGORIES,
        max_choices=5,
        max_length=100
    )

    class Meta:
        unique_together = ['name', 'categories']

    def __str__(self):
        return self.name

    @classmethod
    def get_records_in_category(cls, category, user):
        records = SettingRecord.objects.filter(
            categories__icontains=category
        ).order_by('title')

        result = {
            'records':[]
        }
        for record in records:
            result['records'].append({
                'id':record.id,
                'title':record.title
            })
        return result
