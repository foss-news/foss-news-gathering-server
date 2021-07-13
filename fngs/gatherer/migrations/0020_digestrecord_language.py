# Generated by Django 2.2.13 on 2021-07-13 06:07

from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('gatherer', '0019_set_project_field_to_be_optional'),
    ]

    operations = [
        migrations.AddField(
            model_name='digestrecord',
            name='language',
            field=models.CharField(blank=True, choices=[('ENGLISH', 'eng'), ('RUSSIAN', 'rus')], max_length=3, null=True, verbose_name='Language'),
        ),
    ]
