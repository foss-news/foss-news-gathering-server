# Generated by Django 2.2.13 on 2021-07-14 04:03

from django.db import migrations
from gatherer.models import DigestRecordContentCategory, models


def migrate_to_new_org_subcategory(apps, schema_editor):
    dr_model = apps.get_model('gatherer', 'DigestRecord')
    for dr in dr_model.objects.all():
        if dr.subcategory == DigestRecordContentCategory.NEWS.name:
            dr.subcategory = DigestRecordContentCategory.ORG.name
            dr.save()


class Migration(migrations.Migration):

    dependencies = [
        ('gatherer', '0025_fill_empty_languages'),
    ]

    operations = [
        migrations.AlterField(
            model_name='digestrecord',
            name='subcategory',
            field=models.CharField(blank=True, choices=[('EVENTS', 'events'), ('INTROS', 'intros'), ('OPENING', 'opening'), ('NEWS', 'news'), ('ORG', 'org'), ('DIY', 'diy'), ('LAW', 'law'), ('KnD', 'knd'), ('SYSTEM', 'system'), ('SPECIAL', 'special'), ('EDUCATION', 'education'), ('DATABASES', 'db'), ('MULTIMEDIA', 'multimedia'), ('MOBILE', 'mobile'), ('SECURITY', 'security'), ('SYSADM', 'sysadm'), ('DEVOPS', 'devops'), ('DATA_SCIENCE', 'data_science'), ('WEB', 'web'), ('DEV', 'dev'), ('TESTING', 'testing'), ('HISTORY', 'history'), ('MANAGEMENT', 'management'), ('USER', 'user'), ('GAMES', 'games'), ('HARDWARE', 'hardware'), ('MISC', 'misc')], max_length=15, null=True, verbose_name='Subcategory'),
        ),
        migrations.RunPython(migrate_to_new_org_subcategory, migrations.RunPython.noop),
    ]
