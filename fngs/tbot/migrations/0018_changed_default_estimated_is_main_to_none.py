# Generated by Django 2.2.24 on 2021-11-08 03:17

from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('tbot', '0017_removed_obsolete_news_content_category'),
    ]

    operations = [
        migrations.AlterField(
            model_name='telegrambotdigestrecordcategorizationattempt',
            name='estimated_is_main',
            field=models.BooleanField(blank=True, default=None, null=True, verbose_name='Estimated Is Main Post'),
        ),
    ]
