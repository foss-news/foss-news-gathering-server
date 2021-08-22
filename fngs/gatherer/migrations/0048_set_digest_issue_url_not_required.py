# Generated by Django 2.2.13 on 2021-08-22 13:26

from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('gatherer', '0047_fill_title_keywords'),
    ]

    operations = [
        migrations.AlterField(
            model_name='digestissue',
            name='habr_url',
            field=models.CharField(blank=True, max_length=128, null=True, unique=True, verbose_name='Link to Habr'),
        ),
    ]
