from rest_framework import serializers

from gatherer.models import *


class DigestRecordSerializer(serializers.ModelSerializer):
    class Meta:
        model = DigestRecord
        fields = [
            'id',
            'dt',
            'gather_dt',
            'title',
            'url',
            'state',
            'digest_issue',
            'is_main',
            'category',
            'subcategory',
            'title_keywords',
            'projects',
            'language',
        ]


class DigestRecordDetailedSerializer(serializers.ModelSerializer):
    class Meta:
        model = DigestRecord
        depth = 1
        fields = [
            'id',
            'dt',
            'gather_dt',
            'title',
            'url',
            'state',
            'digest_issue',
            'is_main',
            'category',
            'subcategory',
            'title_keywords',
            'projects',
            'language',
        ]


class DigestRecordDuplicateSerializer(serializers.ModelSerializer):

    class Meta:
        model = DigestRecordDuplicate
        fields = [
            'id',
            'digest_issue',
            'digest_records',
        ]


class DigestRecordDuplicateDetailedSerializer(serializers.ModelSerializer):

    class Meta:
        model = DigestRecordDuplicate
        depth = 1
        fields = [
            'id',
            'digest_issue',
            'digest_records',
        ]


class ProjectSerializer(serializers.ModelSerializer):

    class Meta:
        model = Project
        fields = [
            'id',
            'name',
            'records',
        ]


class KeywordSerializer(serializers.ModelSerializer):

    class Meta:
        model = Keyword
        fields = [
            'id',
            'name',
            'category',
            'is_generic',
        ]
