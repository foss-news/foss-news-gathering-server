# Generated by Django 2.2.13 on 2021-08-22 11:40

from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('gatherer', '0042_fix_meta_description_language'),
    ]

    operations = [
        migrations.AlterField(
            model_name='digestissue',
            name='habr_url',
            field=models.CharField(max_length=128, unique=True, verbose_name='Link to Habr'),
        ),
        migrations.AlterField(
            model_name='digestissue',
            name='number',
            field=models.IntegerField(unique=True, verbose_name='Issue Number'),
        ),
    ]