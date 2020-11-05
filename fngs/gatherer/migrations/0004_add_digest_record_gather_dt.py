# Generated by Django 2.2.3 on 2020-11-05 08:30

from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('gatherer', '0003_digest_record_new_field'),
    ]

    operations = [
        migrations.AddField(
            model_name='digestrecord',
            name='gather_dt',
            field=models.DateTimeField(blank=True, null=True, verbose_name='Date&time of record gather'),
        ),
    ]
