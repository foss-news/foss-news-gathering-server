# Generated by Django 2.2.24 on 2021-10-16 09:44

from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('tbot', '0010_marked_users_group_name_as_unique'),
    ]

    operations = [
        migrations.AlterField(
            model_name='telegrambotdigestrecordcategorizationattempt',
            name='estimated_state',
            field=models.CharField(blank=True, choices=[('UNKNOWN', 'unknown'), ('IN_DIGEST', 'in_digest'), ('OUTDATED', 'outdated'), ('DUPLICATE', 'duplicate'), ('IGNORED', 'ignored'), ('FILTERED', 'filtered'), ('SKIPPED', 'skipped')], max_length=15, null=True, verbose_name='Estimated State'),
        ),
    ]