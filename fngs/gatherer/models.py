from django.db import models
from enum import Enum


class DigestRecordState(Enum):
    UNKNOWN = 'unknown'
    IN_DIGEST = 'in_digest'
    OUTDATED = 'outdated'
    IGNORED = 'ignored'
    FILTERED = 'filtered'

    @classmethod
    def choices(cls):
        return tuple((i.name, i.value) for i in cls)


class DigestRecordCategory(Enum):
    UNKNOWN = 'unknown'
    NEWS = 'news'
    ARTICLES = 'articles'
    VIDEOS = 'videos'
    RELEASES = 'releases'
    OTHER = 'other'

    @classmethod
    def choices(cls):
        return tuple((i.name, i.value) for i in cls)


class Language(Enum):
    ENGLISH = 'eng'
    RUSSIAN = 'rus'

    @classmethod
    def choices(cls):
        return tuple((i.name, i.value) for i in cls)


class DigestRecordSubcategory(Enum):
    EVENTS = 'events'
    INTROS = 'intros'
    OPENING = 'opening'
    NEWS = 'news'  # Obsolete, should not be used
    ORG = 'org'
    DIY = 'diy'
    LAW = 'law'
    KnD = 'knd'
    SYSTEM = 'system'  # Obsolete, should not be used
    SPECIAL = 'special'
    EDUCATION = 'education'
    DATABASES = 'db'
    MULTIMEDIA = 'multimedia'
    MOBILE = 'mobile'
    SECURITY = 'security'
    SYSADM = 'sysadm'
    DEVOPS = 'devops'
    DATA_SCIENCE = 'data_science'
    WEB = 'web'
    DEV = 'dev'
    TESTING = 'testing'
    HISTORY = 'history'
    MANAGEMENT = 'management'
    USER = 'user'
    GAMES = 'games'
    HARDWARE = 'hardware'
    MISC = 'misc'

    @classmethod
    def choices(cls):
        return tuple((i.name, i.value) for i in cls)


class DigestRecord(models.Model):
    dt = models.DateTimeField(verbose_name='Date&time',
                              null=True,
                              blank=True)
    source = models.ForeignKey(to='DigestRecordsSource',
                               on_delete=models.PROTECT,
                               blank=True,
                               null=True)
    gather_dt = models.DateTimeField(verbose_name='Gather Date&time',
                                     null=True,
                                     blank=True)
    title = models.CharField(verbose_name='Title',
                             max_length=256,
                             blank=False)
    url = models.CharField(verbose_name='URL',
                           max_length=256,
                           unique=True,
                           blank=False)
    state = models.CharField(verbose_name='State',
                             choices=DigestRecordState.choices(),
                             max_length=15,
                             null=True,
                             blank=True)
    digest_number = models.IntegerField(verbose_name='Digest Number',  # Obsolete, should not be used
                                        null=True,
                                        blank=True)
    digest_issue = models.ForeignKey(to='DigestIssue',
                                     on_delete=models.PROTECT,
                                     null=True,
                                     blank=True)
    is_main = models.BooleanField(verbose_name='Is main post',
                                  null=True,
                                  blank=True)
    category = models.CharField(verbose_name='Category',
                                choices=DigestRecordCategory.choices(),
                                max_length=15,
                                null=True,
                                blank=True)
    subcategory = models.CharField(verbose_name='Subcategory',
                                   choices=DigestRecordSubcategory.choices(),
                                   max_length=15,
                                   null=True,
                                   blank=True)
    keywords = models.CharField(verbose_name='Keywords',  # Obsolete, should not be used
                                max_length=1024,
                                null=True,
                                blank=True)
    title_keywords = models.ManyToManyField(to='Keyword',
                                            blank=True,
                                            verbose_name='Title Keywords',
                                            related_name='records')
    projects = models.ManyToManyField(to='Project',
                                      blank=True,
                                      verbose_name='Projects',
                                      related_name='records')
    language = models.CharField(verbose_name='Language',
                                choices=Language.choices(),
                                max_length=15,
                                null=True,
                                blank=True)
    description = models.TextField(verbose_name='Description',
                                   null=True,
                                   blank=True)

    def projects_names(self):
        return f'{", ".join([p.name for p in self.projects.all()])}'

    def title_keywords_names(self):
        return f'{", ".join([k.name for k in self.title_keywords.all()])}'

    class Meta:
        verbose_name = 'Digest Record'
        verbose_name_plural = 'Digest Records'

    def __str__(self):
        return f'{self.dt} {self.title} {self.url} #{self.digest_number} state:"{self.state}" cat:"{self.category}" subcat: "{self.subcategory}" keywords: "{self.keywords}"'


class DigestRecordDuplicate(models.Model):

    digest_number = models.IntegerField(verbose_name='Digest Number',
                                        null=True,
                                        blank=True)
    digest_issue = models.ForeignKey(to='DigestIssue',
                                     verbose_name='Digest Issue',
                                     on_delete=models.PROTECT,
                                     null=True,
                                     blank=True)
    digest_records = models.ManyToManyField(to=DigestRecord,
                                            verbose_name='Digest Record',
                                            related_name='duplicates',
                                            )

    class Meta:
        verbose_name = 'Digest Record Duplicate'
        verbose_name_plural = 'Digest Records Duplicates'

    def digest_records_titles(self):
        return f'{", ".join([dr.title for dr in self.digest_records.all()])}'

    def __str__(self):
        return self.digest_records_titles()


class Project(models.Model):

    name = models.CharField(verbose_name='Name', max_length=64)

    class Meta:
        verbose_name = 'Project'
        verbose_name_plural = 'Projects'

    def __str__(self):
        return self.name


class Keyword(models.Model):

    name = models.CharField(verbose_name='Name', max_length=64)
    category = models.CharField(verbose_name='Category',
                                choices=DigestRecordSubcategory.choices(),
                                max_length=15,
                                null=True,
                                blank=True)
    is_generic = models.BooleanField(verbose_name='Is generic',
                                     null=True,
                                     blank=True)

    class Meta:
        unique_together = (
            'name',
            'category',
        )
        verbose_name = 'Keyword'
        verbose_name_plural = 'Keywords'

    def __str__(self):
        return f'{self.name} ({self.category}, {"GENERIC" if self.is_generic else "NON-GENERIC"})'


class DigestRecordsSource(models.Model):

    name = models.CharField(verbose_name='Name',
                            max_length=128,
                            unique=True)
    enabled = models.BooleanField(verbose_name='Enabled')

    class Meta:
        verbose_name = 'Digest Records Source'
        verbose_name_plural = 'Digest Records Sources'

    def __str__(self):
        return self.name


class DigestIssue(models.Model):

    number = models.IntegerField(verbose_name='Issue Number',
                                 unique=True)
    habr_url = models.CharField(verbose_name='Link to Habr',
                                unique=True,
                                max_length=128,
                                blank=True,
                                null=True)

    class Meta:
        verbose_name = 'Digest Issue'
        verbose_name_plural = 'Digest Issues'

    def __str__(self):
        return f'#{self.number} {self.habr_url}'


class DigestGatheringIteration(models.Model):

    dt = models.DateTimeField(verbose_name='Date&time')
    gathered_count = models.IntegerField(verbose_name='Gathered Records Count')
    saved_count = models.IntegerField(verbose_name='Saved Records Count',
                                      blank=True,
                                      null=True)
    source = models.ForeignKey(to='DigestRecordsSource',
                               on_delete=models.PROTECT,
                               blank=True,
                               null=True)
    source_enabled = models.BooleanField(verbose_name='Source enabled',
                                         blank=True,
                                         null=True)
    source_error = models.TextField(verbose_name='Source error',
                                    blank=True,
                                    null=True)
    parser_error = models.TextField(verbose_name='Parser error',
                                    blank=True,
                                    null=True)

    class Meta:
        verbose_name = 'Digest Gathering Iteration'
        verbose_name_plural = 'Digest Gathering Iterations'