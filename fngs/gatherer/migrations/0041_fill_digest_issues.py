# Generated by Django 2.2.13 on 2021-07-14 04:03

import os
import json

from django.db import migrations, models
from gatherer.models import DigestIssue


def fill_issues(apps, schema_editor):
    sources_path = os.path.join(os.path.dirname(os.path.realpath(__file__)),
                                'data',
                                'digestissues.json')
    with open(sources_path, 'r') as fin:
        issues = json.load(fin)

    for number, habr_url in issues:
        source = DigestIssue(number=number, habr_url=habr_url)
        source.save()


class Migration(migrations.Migration):

    dependencies = [
        ('gatherer', '0040_create_digestissue'),
    ]

    operations = [
        migrations.RunPython(fill_issues, migrations.RunPython.noop),
    ]