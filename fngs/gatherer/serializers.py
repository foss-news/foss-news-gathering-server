from rest_framework import serializers

from gatherer.models import *


class DigestRecordSerializer(serializers.ModelSerializer):
    class Meta:
        model = DigestRecord
        fields = [
            'id',
            'dt',
            'gather_dt',
            'source',
            'title',
            'url',
            'additional_url',
            'state',
            'digest_issue',
            'is_main',
            'content_type',
            'content_category',
            'title_keywords',
            'projects',
            'language',
        ]


class SimilarDigestRecordsSerializer(serializers.ModelSerializer):

    class Meta:
        model = SimilarDigestRecords
        fields = [
            'id',
            'digest_issue',
            'digest_records',
        ]


class SimilarDigestRecordsDetailedSerializer(serializers.ModelSerializer):

    class Meta:
        model = SimilarDigestRecords
        depth = 2
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
            'content_category',
            'is_generic',
            'proprietary',
            'enabled',
        ]


class DigestRecordDetailedSerializer(serializers.ModelSerializer):
    not_proprietary_keywords = KeywordSerializer(many=True, read_only=True)
    proprietary_keywords = KeywordSerializer(many=True, read_only=True)

    class Meta:
        model = DigestRecord
        depth = 2
        fields = [
            'id',
            'dt',
            'gather_dt',
            'source',
            'title',
            'url',
            'additional_url',
            'state',
            'digest_issue',
            'is_main',
            'content_type',
            'content_category',
            'title_keywords',
            'not_proprietary_keywords',
            'proprietary_keywords',
            'projects',
            'language',
            'tbot_estimations',
        ]


class DigestIssueSerializer(serializers.ModelSerializer):

    class Meta:
        model = DigestIssue
        fields = [
            'id',
            'number',
            'is_special',
            'habr_url',
        ]
