# Generated by Django 2.2.13 on 2021-09-12 06:32

from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('gatherer', '0057_digestgatheringiteration_saved_count'),
    ]

    operations = [
        migrations.AlterField(
            model_name='digestrecord',
            name='subcategory',
            field=models.CharField(blank=True, choices=[('EVENTS', 'events'), ('INTROS', 'intros'), ('OPENING', 'opening'), ('NEWS', 'news'), ('ORG', 'org'), ('DIY', 'diy'), ('LAW', 'law'), ('KnD', 'knd'), ('SYSTEM', 'system'), ('SPECIAL', 'special'), ('EDUCATION', 'education'), ('DATABASES', 'db'), ('MULTIMEDIA', 'multimedia'), ('MOBILE', 'mobile'), ('SECURITY', 'security'), ('SYSADM', 'sysadm'), ('DEVOPS', 'devops'), ('DATA_SCIENCE', 'data_science'), ('WEB', 'web'), ('DEV', 'dev'), ('TESTING', 'testing'), ('HISTORY', 'history'), ('MANAGEMENT', 'management'), ('USER', 'user'), ('GAMES', 'games'), ('HARDWARE', 'hardware'), ('MESSENGERS', 'messengers'), ('MISC', 'misc')], max_length=15, null=True, verbose_name='Subcategory'),
        ),
        migrations.AlterField(
            model_name='keyword',
            name='category',
            field=models.CharField(blank=True, choices=[('EVENTS', 'events'), ('INTROS', 'intros'), ('OPENING', 'opening'), ('NEWS', 'news'), ('ORG', 'org'), ('DIY', 'diy'), ('LAW', 'law'), ('KnD', 'knd'), ('SYSTEM', 'system'), ('SPECIAL', 'special'), ('EDUCATION', 'education'), ('DATABASES', 'db'), ('MULTIMEDIA', 'multimedia'), ('MOBILE', 'mobile'), ('SECURITY', 'security'), ('SYSADM', 'sysadm'), ('DEVOPS', 'devops'), ('DATA_SCIENCE', 'data_science'), ('WEB', 'web'), ('DEV', 'dev'), ('TESTING', 'testing'), ('HISTORY', 'history'), ('MANAGEMENT', 'management'), ('USER', 'user'), ('GAMES', 'games'), ('HARDWARE', 'hardware'), ('MESSENGERS', 'messengers'), ('MISC', 'misc')], max_length=15, null=True, verbose_name='Category'),
        ),
    ]
