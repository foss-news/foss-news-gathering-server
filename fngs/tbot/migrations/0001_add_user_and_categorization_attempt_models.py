# Generated by Django 2.2.13 on 2021-08-18 02:29

from django.db import migrations, models
import django.db.models.deletion


class Migration(migrations.Migration):

    initial = True

    dependencies = [
        ('gatherer', '0033_add_digestrecord_description'),
    ]

    operations = [
        migrations.CreateModel(
            name='TelegramBotUser',
            fields=[
                ('id', models.AutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('tid', models.IntegerField(verbose_name='Telegram User ID')),
                ('username', models.CharField(max_length=256, verbose_name='Telegram Username')),
            ],
        ),
        migrations.CreateModel(
            name='TelegramBotDigestRecordCategorizationAttempt',
            fields=[
                ('id', models.AutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('dt', models.DateTimeField(verbose_name='Attempt Date&Time')),
                ('estimated_state', models.CharField(blank=True, choices=[('UNKNOWN', 'unknown'), ('IN_DIGEST', 'in_digest'), ('OUTDATED', 'outdated'), ('IGNORED', 'ignored'), ('FILTERED', 'filtered')], max_length=15, null=True, verbose_name='Estimated State')),
                ('estimated_is_main', models.BooleanField(blank=True, null=True, verbose_name='Estimated Is Main Post')),
                ('estimated_category', models.CharField(blank=True, choices=[('UNKNOWN', 'unknown'), ('NEWS', 'news'), ('ARTICLES', 'articles'), ('VIDEOS', 'videos'), ('RELEASES', 'releases'), ('OTHER', 'other')], max_length=15, null=True, verbose_name='Estimated Category')),
                ('estimated_subcategory', models.CharField(blank=True, choices=[('EVENTS', 'events'), ('INTROS', 'intros'), ('OPENING', 'opening'), ('NEWS', 'news'), ('ORG', 'org'), ('DIY', 'diy'), ('LAW', 'law'), ('KnD', 'knd'), ('SYSTEM', 'system'), ('SPECIAL', 'special'), ('EDUCATION', 'education'), ('DATABASES', 'db'), ('MULTIMEDIA', 'multimedia'), ('MOBILE', 'mobile'), ('SECURITY', 'security'), ('SYSADM', 'sysadm'), ('DEVOPS', 'devops'), ('DATA_SCIENCE', 'data_science'), ('WEB', 'web'), ('DEV', 'dev'), ('TESTING', 'testing'), ('HISTORY', 'history'), ('MANAGEMENT', 'management'), ('USER', 'user'), ('GAMES', 'games'), ('HARDWARE', 'hardware'), ('MISC', 'misc')], max_length=15, null=True, verbose_name='Estimated Subcategory')),
                ('digest_record', models.ForeignKey(on_delete=django.db.models.deletion.PROTECT, to='gatherer.DigestRecord', verbose_name='Digest Record under Categorization')),
                ('telegram_bot_user', models.ForeignKey(on_delete=django.db.models.deletion.PROTECT, to='tbot.TelegramBotUser', verbose_name='Telegram Bot User')),
            ],
        ),
    ]
