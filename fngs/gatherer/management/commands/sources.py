from typing import List, Tuple
from abc import ABCMeta, abstractmethod
import xml.etree.ElementTree as ET
from lxml import html
import requests
import re
from pprint import pprint
import traceback
import datetime
import dateutil
from copy import copy
import pytz

from gatherer.models import *
from .logger import logger


foss_news_project = Project.objects.get(name='FOSS News')
os_friday_project = Project.objects.get(name='OS Friday')
FOSS_NEWS_REGEXP = r'^FOSS News №\d+.*дайджест материалов о свободном и открытом ПО за.*$'


def shorten_text(s: str, max_length: int = 20):
    if s is None:
        return None
    elif len(s) < max_length:
        return s
    else:
        return s[:max_length - 3] + '...'


class PostData:

    def __init__(self,
                 dt: datetime.datetime,
                 title: str,
                 url: str,
                 brief: str,
                 filtered: bool = None):
        self.dt = dt
        self.title = title
        self.url = url
        self.brief = brief
        self.keywords = []
        self.filtered = None

    def __str__(self):
        return f'{self.dt} -- {self.url} -- {self.title} -- {shorten_text(self.brief)}'


class PostsData:

    def __init__(self,
                 source_name: str,
                 projects: List[Project],
                 posts_data_list: List[PostData],
                 language: Language,
                 warning: str = None):
        self.source_name = source_name
        self.projects = projects
        self.posts_data_list = posts_data_list
        self.language = language
        self.warning = warning


class FiltrationType(Enum):
    GENERIC = 'generic'
    SPECIFIC = 'specific'


class ParsingResult:

    def __init__(self, posts_data, source_enabled, source_error, parser_error):
        self.posts_data: List[PostData] or None = posts_data
        self.source_enabled: bool = source_enabled
        self.source_error: str or None = source_error
        self.parser_error: str or None = parser_error

    @property
    def success(self):
        return not(self.source_error or self.parser_error)


class DigestSourceException(Exception):

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)


class BasicParsingModule(metaclass=ABCMeta):

    source_name = None
    projects: Tuple[Project] = ()
    warning = None
    filtration_needed = False
    filters = []
    language: Language = None

    def parse(self, days_count: int) -> ParsingResult:
        if not DigestRecordsSource.objects.get(name=self.source_name).enabled:  # TODO: Check existence
            logger.warning(f'"{self.source_name}" is disabled')
            return ParsingResult([], False, None, None)
        try:
            posts_data: List[PostData] = self._parse()
        except DigestSourceException as e:
            logger.error(f'Failed to parse "{self.source_name}", source error: {str(e)}')
            return ParsingResult([], True, str(e), None)
        except Exception as e:
            logger.error(f'Failed to parse "{self.source_name}", parser error: {str(e)}')
            logger.error(traceback.format_exc())
            return ParsingResult([], True, None, str(e))
        try:
            filtered_posts_data: List[PostData] = self._filter_out(posts_data, days_count)
            self._fill_keywords(filtered_posts_data)
            return ParsingResult(filtered_posts_data, True, None, None)
        except Exception as e:
            logger.error(f'Failed to filter data parsed from "{self.source_name}" source: {str(e)}')
            logger.error(traceback.format_exc())
            return ParsingResult([], True, None, str(e))

    @abstractmethod
    def _parse(self) -> List[PostData]:
        pass

    def _fill_keywords(self, posts_data: List[PostData]):
        keywords_to_check = []
        keywords_to_check += [k.name for k in Keyword.objects.all()]
        for post_data in posts_data:
            for keyword in keywords_to_check:
                if keyword in post_data.keywords:
                    continue
                if self._find_keyword_in_title(keyword, post_data.title):
                    post_data.keywords.append(keyword)

    def _find_keyword_in_title(self, keyword, title):
        return re.search(rf'\b{re.escape(keyword)}\b', title, re.IGNORECASE)

    def _filter_out(self, source_posts_data: List[PostData], days_count: int):
        actual_posts_data = self._filter_out_old(source_posts_data, days_count)
        outdated_len = len(source_posts_data) - len(actual_posts_data)
        if outdated_len:
            logger.info(f'{len(source_posts_data) - len(actual_posts_data)}/{len(source_posts_data)} posts ignored for "{self.source_name}" as too old')
        filtered_posts_data = self._filter_out_by_keywords(actual_posts_data)
        nonactual_len = len(actual_posts_data) - len(filtered_posts_data)
        if nonactual_len:
            logger.info(f'{len(source_posts_data) - len(actual_posts_data)}/{len(source_posts_data)} posts ignored for "{self.source_name}" as not passed keywords filters')
        return filtered_posts_data

    def _filter_out_by_keywords(self, posts_data: List[PostData]):
        if not self.filtration_needed:
            return posts_data
        filtered_posts_data: List[PostData] = []
        keywords_to_check = []
        if FiltrationType.GENERIC in self.filters:
            keywords_to_check += [k.name for k in Keyword.objects.filter(is_generic=True)]
        if FiltrationType.SPECIFIC in self.filters:
            keywords_to_check += [k.name for k in Keyword.objects.filter(is_generic=False)]
        for post_data in posts_data:
            if not post_data.title:
                logger.error(f'Empty title for URL {post_data.url}')
                continue
            matched = False
            for keyword in keywords_to_check:
                if self._find_keyword_in_title(keyword, post_data.title):
                    matched = True
                    break
            processed_post_data = copy(post_data)
            if matched:
                logger.debug(f'"{post_data.title}" from "{self.source_name}" added because it contains keywords {post_data.keywords}')
                processed_post_data.filtered = False
            else:
                logger.warning(f'"{post_data.title}" ({post_data.url}) from "{self.source_name}" filtered out cause not contains none of expected keywords')
                processed_post_data.filtered = True
            filtered_posts_data.append(processed_post_data)
        return filtered_posts_data

    def _filter_out_old(self, posts_data: List[PostData], days_count: int) -> List[PostData]:
        filtered_posts_data: List[PostData] = []
        dt_now = datetime.datetime.now(tz=dateutil.tz.tzlocal())
        already_existing_digest_records_dt_updated_count = 0
        for post_data in posts_data:
            if post_data.dt is not None and (dt_now - post_data.dt).days > days_count:
                logger.debug(f'"{post_data.title}" from "{self.source_name}" filtered as too old ({post_data.dt})')
                similar_records = DigestRecord.objects.filter(url=post_data.url)  # TODO: Replace check for duplicates before and with "get"
                if similar_records:
                    if not similar_records[0].dt:
                        similar_records[0].dt = post_data.dt
                        logger.debug(f'{post_data.url} already exists in database, but without date, fix it')
                        already_existing_digest_records_dt_updated_count += 1
                        similar_records[0].save()
            else:
                filtered_posts_data.append(post_data)
        if already_existing_digest_records_dt_updated_count:
            logger.info(f'Few outdated sources found in database without dates, fixed for {already_existing_digest_records_dt_updated_count} sources')
        return filtered_posts_data


class RssBasicParsingModule(BasicParsingModule):

    rss_url = None
    item_tag_name = None
    title_tag_name = None
    pubdate_tag_name = None
    link_tag_name = None
    description_tag_name = None
    no_description = False

    def __init__(self):
        self.rss_data_root = None

    def _preprocess_xml(self, text: str):
        return text

    def _preprocess_date_str(self, date_str: str):
        return date_str

    def _parse(self):
        posts_data: List[PostData] = []
        response = requests.get(self.rss_url,
                                headers={'User-Agent': 'Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/91.0.4472.114 Safari/537.36'})
        if response.status_code != 200:
            raise DigestSourceException(f'"{self.source_name}" returned status code {response.status_code}')
        else:
            logger.debug(f'Successfully fetched RSS for "{self.source_name}"')
        self.rss_data_root = ET.fromstring(self._preprocess_xml(response.text))
        no_description_at_all = True
        for rss_data_elem in self.rss_items_root():
            if self.item_tag_name in rss_data_elem.tag:
                dt = None
                title = None
                url = None
                brief = None
                for rss_data_subelem in rss_data_elem:
                    tag = rss_data_subelem.tag
                    text = rss_data_subelem.text
                    if self.title_tag_name in tag:
                        if not text:
                            continue
                        title = text.strip()
                    elif self.pubdate_tag_name in tag:
                        text = self._preprocess_date_str(text)
                        text = self._date_from_russian_to_english(text) # TODO: Extract such filter to specific classes
                        dt: datetime.datetime = dateutil.parser.parse(text)
                        if dt.tzinfo is None:
                            dt = dt.replace(tzinfo=pytz.UTC)
                    elif self.link_tag_name in tag:
                        if text:
                            url = text
                        elif 'href' in rss_data_subelem.attrib:
                            url = rss_data_subelem.attrib['href']
                        else:
                            logger.error(f'Could not find URL for "{title}" feed record')
                    elif self.description_tag_name in tag:
                        brief = text
                        no_description_at_all = False
                    elif 'group' in tag:
                        for rss_data_subsubelem in rss_data_subelem:
                            subtag = rss_data_subsubelem.tag
                            if self.description_tag_name in subtag:
                                subtext = rss_data_subsubelem.text
                                brief = subtext
                                no_description_at_all = False
                url = self.process_url(url)
                if not url:
                    if title:
                        logger.error(f'Empty URL for title "{title}" for source "{self.source_name}"')
                    else:
                        logger.error(f'Empty URL and empty title for source "{self.source_name}"')
                    continue
                post_data = PostData(dt, title, url, brief)
                posts_data.append(post_data)
        if posts_data and no_description_at_all and not self.no_description:
            logger.error(f'No descriptions at all in {self.source_name} source feed')
        return posts_data

    def _date_from_russian_to_english(self,
                                      datetime_text: str):
        days_map = {
            'Пн': 'Mon',
            'Вт': 'Tue',
            'Ср': 'Wed',
            'Чт': 'Thu',
            'Пт': 'Fri',
            'Сб': 'Sat',
            'Вс': 'Sun',
        }
        months_map = {
            'янв': 'jan',
            'фев': 'feb',
            'мар': 'mar',
            'апр': 'apr',
            'май': 'may',
            'мая': 'may',
            'июн': 'jun',
            'июл': 'jul',
            'авг': 'aug',
            'сен': 'sep',
            'окт': 'oct',
            'ноя': 'nov',
            'дек': 'dec',
        }
        converted_datetime_text = datetime_text
        for ru_en_map in (days_map, months_map):
            for ru, en in ru_en_map.items():
                converted_datetime_text = converted_datetime_text.replace(ru, en)
        return converted_datetime_text

    def process_url(self, url):
        return url

    @abstractmethod
    def rss_items_root(self):
        pass


class SimpleRssBasicParsingModule(RssBasicParsingModule):

    item_tag_name = 'item'
    title_tag_name = 'title'
    pubdate_tag_name = 'pubDate'
    link_tag_name = 'link'
    description_tag_name = 'description'

    def rss_items_root(self):
        return self.rss_data_root[0]


class OpenNetRuParsingModule(SimpleRssBasicParsingModule):

    source_name = "OpenNetRu"
    projects = (
        foss_news_project,
    )
    rss_url = 'https://www.opennet.ru/opennews/opennews_all_utf.rss'
    language = Language.RUSSIAN


class LinuxComParsingModule(SimpleRssBasicParsingModule):

    source_name = "LinuxCom"
    projects = (
        foss_news_project,
        os_friday_project,
    )
    rss_url = 'https://www.linux.com/topic/feed/'
    language = Language.ENGLISH


class OpenSourceComParsingModule(SimpleRssBasicParsingModule):
    # NOTE: Provider provides RSS feed for less than week, more regular check is needed

    source_name = 'OpenSourceCom'
    projects = (
        foss_news_project,
        os_friday_project
    )
    rss_url = 'https://opensource.com/feed'
    language = Language.ENGLISH


class ItsFossComParsingModule(SimpleRssBasicParsingModule):

    source_name = 'ItsFossCom'
    projects = (
        foss_news_project,
    )
    rss_url = 'https://itsfoss.com/all-blog-posts/feed/'
    language = Language.ENGLISH


class LinuxOrgRuParsingModule(SimpleRssBasicParsingModule):

    source_name = 'LinuxOrgRu'
    projects = (
        foss_news_project,
    )
    rss_url = 'https://www.linux.org.ru/section-rss.jsp?section=1'
    language = Language.RUSSIAN


class AnalyticsIndiaMagComParsingModule(SimpleRssBasicParsingModule):

    source_name = 'AnalyticsIndiaMagCom'
    projects = (
        foss_news_project,
    )
    rss_url = 'https://analyticsindiamag.com/feed/'
    filtration_needed = True
    filters = (
        FiltrationType.SPECIFIC,
        FiltrationType.GENERIC,
    )
    language = Language.ENGLISH


class ArsTechnicaComParsingModule(SimpleRssBasicParsingModule):

    source_name = 'ArsTechnicaCom'
    projects = (
        foss_news_project,
    )
    rss_url = 'https://arstechnica.com/feed/'
    filtration_needed = True
    filters = (
        FiltrationType.SPECIFIC,
    )
    language = Language.ENGLISH


class HackadayComParsingModule(SimpleRssBasicParsingModule):

    source_name = 'HackadayCom'
    projects = (
        foss_news_project,
    )
    rss_url = 'https://hackaday.com/feed/'
    filtration_needed = True
    filters = (
        FiltrationType.SPECIFIC,
    )
    language = Language.ENGLISH


class JaxenterComParsingModule(SimpleRssBasicParsingModule):

    source_name = 'JaxenterCom'
    projects = (
        foss_news_project,
    )
    rss_url = 'https://jaxenter.com/rss'
    filtration_needed = True
    filters = (
        FiltrationType.SPECIFIC,
    )
    language = Language.ENGLISH


class LinuxInsiderComParsingModule(SimpleRssBasicParsingModule):

    source_name = 'LinuxInsiderCom'
    projects = (
        foss_news_project,
    )
    rss_url = 'https://linuxinsider.com/rss-feed'
    language = Language.ENGLISH


class MashableComParsingModule(SimpleRssBasicParsingModule):

    source_name = 'MashableCom'
    projects = (
        foss_news_project,
    )
    rss_url = 'https://mashable.com/rss/'
    filtration_needed = True
    filters = (
        FiltrationType.SPECIFIC,
    )
    language = Language.ENGLISH


class SdTimesComParsingModule(SimpleRssBasicParsingModule):

    source_name = 'SdTimesCom'
    projects = (
        foss_news_project,
    )
    rss_url = 'https://sdtimes.com/feed/'
    filtration_needed = True
    filters = (
        FiltrationType.SPECIFIC,
    )
    language = Language.ENGLISH


class SecurityBoulevardComParsingModule(SimpleRssBasicParsingModule):

    source_name = 'SecurityBoulevardCom'
    projects = (
        foss_news_project,
    )
    rss_url = 'https://securityboulevard.com/feed/'
    filtration_needed = True
    filters = (
        FiltrationType.SPECIFIC,
    )
    language = Language.ENGLISH


class SiliconAngleComParsingModule(SimpleRssBasicParsingModule):

    source_name = 'SiliconAngleCom'
    projects = (
        foss_news_project,
    )
    rss_url = 'https://siliconangle.com/feed/'
    filtration_needed = True
    filters = (
        FiltrationType.SPECIFIC,
    )
    language = Language.ENGLISH


class TechCrunchComParsingModule(SimpleRssBasicParsingModule):

    source_name = 'TechCrunchCom'
    projects = (
        foss_news_project,
    )
    rss_url = 'https://techcrunch.com/feed/'
    filtration_needed = True
    filters = (
        FiltrationType.SPECIFIC,
    )
    language = Language.ENGLISH


class TechNodeComParsingModule(SimpleRssBasicParsingModule):

    source_name = 'TechNodeCom'
    projects = (
        foss_news_project,
    )
    rss_url = 'https://technode.com/feed/'
    filtration_needed = True
    filters = (
        FiltrationType.SPECIFIC,
    )
    language = Language.ENGLISH


class TheNextWebComParsingModule(SimpleRssBasicParsingModule):

    source_name = 'TheNextWebCom'
    projects = (
        foss_news_project,
    )
    rss_url = 'https://thenextweb.com/feed/'
    filtration_needed = True
    filters = (
        FiltrationType.SPECIFIC,
    )
    language = Language.ENGLISH


class VentureBeatComParsingModule(SimpleRssBasicParsingModule):

    source_name = 'VentureBeatCom'
    projects = (
        foss_news_project,
    )
    rss_url = 'https://venturebeat.com/feed/'
    filtration_needed = True
    filters = (
        FiltrationType.SPECIFIC,
    )
    language = Language.ENGLISH


class ThreeDPrintingMediaNetworkParsingModule(SimpleRssBasicParsingModule):

    source_name = 'ThreeDPrintingMediaNetwork'
    projects = (
        foss_news_project,
    )
    rss_url = 'https://www.3dprintingmedia.network/feed/'
    filtration_needed = True
    filters = (
        FiltrationType.SPECIFIC,
    )
    language = Language.ENGLISH


class CbrOnlineComParsingModule(SimpleRssBasicParsingModule):

    source_name = 'CbrOnlineCom'
    projects = (
        foss_news_project,
    )
    # rss_url = 'https://www.cbronline.com/rss'
    rss_url = 'https://techmonitor.ai/rss'
    filtration_needed = True
    filters = (
        FiltrationType.SPECIFIC,
    )
    language = Language.ENGLISH


class HelpNetSecurityComParsingModule(SimpleRssBasicParsingModule):

    source_name = 'HelpNetSecurityCom'
    projects = (
        foss_news_project,
    )
    rss_url = 'https://www.helpnetsecurity.com/feed/'
    filtration_needed = True
    filters = (
        FiltrationType.SPECIFIC,
    )
    language = Language.ENGLISH


class SecuritySalesComParsingModule(SimpleRssBasicParsingModule):

    source_name = 'SecuritySalesCom'
    projects = (
        foss_news_project,
    )
    rss_url = 'https://www.securitysales.com/feed/'
    filtration_needed = True
    filters = (
        FiltrationType.SPECIFIC,
    )
    language = Language.ENGLISH


class TechRadarComParsingModule(SimpleRssBasicParsingModule):

    source_name = 'TechRadarCom'
    projects = (
        foss_news_project,
    )
    rss_url = 'https://www.techradar.com/rss'
    filtration_needed = True
    filters = (
        FiltrationType.SPECIFIC,
    )
    language = Language.ENGLISH


class TfirIoParsingModule(SimpleRssBasicParsingModule):

    source_name = 'TfirIo'
    projects = (
        foss_news_project,
    )
    rss_url = 'https://www.tfir.io/feed/'
    filtration_needed = True
    filters = (
        FiltrationType.SPECIFIC,
    )
    language = Language.ENGLISH


class ZdNetComLinuxParsingModule(SimpleRssBasicParsingModule):
    # TODO: Think about parsing other sections
    source_name = 'ZdNetComLinux'
    projects = (
        foss_news_project,
    )
    rss_url = 'https://www.zdnet.com/topic/linux/rss.xml'
    language = Language.ENGLISH


class LinuxFoundationOrgParsingModule(SimpleRssBasicParsingModule):

    source_name = 'LinuxFoundationOrg'
    projects = (
        foss_news_project,
    )
    rss_url = 'https://linuxfoundation.org/rss'
    language = Language.ENGLISH


class HabrComBasicParsingModule(SimpleRssBasicParsingModule):

    source_name = None
    hub_code = None

    @property
    def rss_url(self):
        return f'https://habr.com/ru/rss/hub/{self.hub_code}/all/?fl=ru'

    def process_url(self, url: str):
        return re.sub('/\?utm_campaign=.*&utm_source=habrahabr&utm_medium=rss',
                      '',
                      url)


class HabrComNewsParsingModule(HabrComBasicParsingModule):

    source_name = 'HabrComNews'
    projects = (
        foss_news_project,
    )
    filtration_needed = True
    filters = (
        FiltrationType.SPECIFIC,
    )
    language = Language.RUSSIAN

    @property
    def rss_url(self):
        return f'https://habr.com/ru/rss/news/'


class FilterFossNewsItselfMixin:

    def filter_foss_news_itself(self, posts_data: List[PostData]):
        for post_data in posts_data:
            if re.fullmatch(FOSS_NEWS_REGEXP, post_data.title):
                logger.warning(f'Filtered "{post_data.title}" as it is our digest itself')
                post_data.filtered = True
        return posts_data


class HabrComOpenSourceParsingModule(HabrComBasicParsingModule,
                                     FilterFossNewsItselfMixin):

    source_name = f'HabrComOpenSource'
    projects = (
        foss_news_project,
    )
    hub_code = 'open_source'
    language = Language.RUSSIAN

    def _parse(self):
        posts_data: List[PostData] = super()._parse()
        filtered_posts_data = self.filter_foss_news_itself(posts_data)
        return filtered_posts_data


class HabrComLinuxParsingModule(HabrComBasicParsingModule):

    source_name = f'HabrComLinux'
    projects = (
        foss_news_project,
    )
    hub_code = 'linux'
    language = Language.RUSSIAN


class HabrComLinuxDevParsingModule(HabrComBasicParsingModule):

    source_name = f'HabrComLinuxDev'
    projects = (
        foss_news_project,
    )
    hub_code = 'linux_dev'
    language = Language.RUSSIAN


class HabrComNixParsingModule(HabrComBasicParsingModule,
                              FilterFossNewsItselfMixin):

    source_name = f'HabrComNix'
    projects = (
        foss_news_project,
    )
    hub_code = 'nix'
    language = Language.RUSSIAN

    def _parse(self):
        posts_data: List[PostData] = super()._parse()
        filtered_posts_data = self.filter_foss_news_itself(posts_data)
        return filtered_posts_data


class HabrComDevOpsParsingModule(HabrComBasicParsingModule):

    source_name = f'HabrComDevOps'
    projects = (
        foss_news_project,
    )
    hub_code = 'devops'
    language = Language.RUSSIAN


class HabrComSysAdmParsingModule(HabrComBasicParsingModule):

    source_name = f'HabrComSysAdm'
    projects = (
        foss_news_project,
    )
    hub_code = 'sys_admin'
    language = Language.RUSSIAN


class HabrComGitParsingModule(HabrComBasicParsingModule):

    source_name = f'HabrComGit'
    projects = (
        foss_news_project,
    )
    hub_code = 'git'
    language = Language.RUSSIAN


class YouTubeComBasicParsingModule(RssBasicParsingModule):

    source_name = None
    channel_id = None
    item_tag_name = 'entry'
    title_tag_name = 'title'
    pubdate_tag_name = 'published'
    link_tag_name = 'link'
    description_tag_name = 'description'

    def rss_items_root(self):
        return self.rss_data_root

    @property
    def rss_url(self):
        return f'https://www.youtube.com/feeds/videos.xml?channel_id={self.channel_id}'


class YouTubePlaylistBasicParsingModule(YouTubeComBasicParsingModule):

    playlist_id = None

    @property
    def rss_url(self):
        return f'https://www.youtube.com/feeds/videos.xml?playlist_id={self.playlist_id}'


class YouTubeComAlekseySamoilovParsingModule(YouTubeComBasicParsingModule):

    source_name = f'YouTubeComAlekseySamoilov'
    projects = (
        foss_news_project,
    )
    channel_id = 'UC3kAbMcYr-JEMSb2xX4OdpA'
    language = Language.RUSSIAN


class PlafonAtYouTubeParsingModule(YouTubeComBasicParsingModule):
    source_name = f'PlafonAtYouTube'
    projects = (
        foss_news_project,
    )
    channel_id = 'UCf7pLsR7lko69y8ySTpoKxg'
    language = Language.RUSSIAN


class TheLinuxExperimentAtYouTubeParsingModule(YouTubeComBasicParsingModule):
    source_name = f'TheLinuxExperimentAtYouTube'
    projects = (
        foss_news_project,
    )
    channel_id = 'UC5UAwBUum7CPN5buc-_N1Fw'
    language = Language.ENGLISH


class NikolayIvanovichAtYouTubeParsingModule(YouTubeComBasicParsingModule):
    source_name = f'NikolayIvanovichAtYouTube'
    projects = (
        foss_news_project,
    )
    channel_id = 'UCevW4vL1SJKvKQYGBTf21mA'
    language = Language.RUSSIAN


class SwitchedToLinuxAtYouTubeParsingModule(YouTubeComBasicParsingModule):
    source_name = f'SwitchedToLinuxAtYouTube'
    projects = (
        foss_news_project,
    )
    channel_id = 'UCoryWpk4QVYKFCJul9KBdyw'
    language = Language.ENGLISH


class LearnLinuxTVAtYouTubeParsingModule(YouTubeComBasicParsingModule):
    source_name = f'LearnLinuxTVAtYouTube'
    projects = (
        foss_news_project,
    )
    channel_id = 'UCxQKHvKbmSzGMvUrVtJYnUA'
    language = Language.ENGLISH

class DmitryRobionekAtYouTubeParsingModule(YouTubeComBasicParsingModule):
    source_name = f'DmitryRobionekAtYouTube'
    projects = (
        foss_news_project,
    )
    channel_id = 'UCtQ4NntQMEHZLKQu52BSpwg'
    language = Language.RUSSIAN


class LosstRuParsingModule(SimpleRssBasicParsingModule):

    source_name = 'LosstRu'
    projects = (
        foss_news_project,
    )
    rss_url = 'https://losst.ru/rss'
    language = Language.RUSSIAN


class AstraLinuxRuParsingModule(SimpleRssBasicParsingModule):

    source_name = 'AstraLinuxRu'
    projects = (
        foss_news_project,
    )
    rss_url = 'https://astralinux.ru/rss'
    language = Language.RUSSIAN
    no_description = True


class BaseAltRuParsingModule(SimpleRssBasicParsingModule):

    source_name = 'BaseAltRu'
    projects = (
        foss_news_project,
    )
    rss_url = 'https://www.basealt.ru/feed.rss'
    language = Language.RUSSIAN


class PingvinusRuParsingModule(BasicParsingModule):

    source_name = 'PingvinusRu'
    projects = (
        foss_news_project,
    )
    site_url = 'https://pingvinus.ru'
    language = Language.RUSSIAN

    def __init__(self):
        super().__init__()
        self.news_page_url = f'{self.site_url}/news'

    def _parse(self):
        response = requests.get(self.news_page_url)
        if response.status_code != 200:
            raise DigestSourceException(f'"{self.source_name}" returned status code {response.status_code}')
        tree = html.fromstring(response.content)
        titles_blocks = tree.xpath('//div[@class="newsdateblock"]//h2/a[contains(@href, "/news/")]')
        dates_blocks = tree.xpath('//div[@class="newsdateblock"]//span[@class="time"]')
        if len(titles_blocks) != len(dates_blocks):
            raise Exception('News titles count does not match dates count')
        rel_urls = tree.xpath('//div[@class="newsdateblock"]//h2/a[contains(@href, "/news/")]/@href')
        titles_texts = [title_block.text for title_block in titles_blocks]
        dates_texts = [date_block.text for date_block in dates_blocks]
        urls = [f'{self.site_url}{rel_url}' for rel_url in rel_urls]
        posts = []
        for title, date_str, url in zip(titles_texts, dates_texts, urls):
            dt = datetime.datetime.strptime(date_str, '%d.%m.%Y')
            dt = dt.replace(tzinfo=dateutil.tz.gettz('Europe/Moscow'))
            if not title:
                logger.error(f'Empty title for URL {url}')
                continue
            post_data = PostData(dt, title, url, None)
            posts.append(post_data)
        return posts


class RedditRssBasicParsingModule(SimpleRssBasicParsingModule):

    item_tag_name = 'entry'
    pubdate_tag_name = 'published'
    description_tag_name = 'content'

    def rss_items_root(self):
        return self.rss_data_root


class OpenSourceOnRedditParsingModule(RedditRssBasicParsingModule):

    source_name = 'OpenSourceOnReddit'
    projects = (
        os_friday_project,
    )
    rss_url = 'http://www.reddit.com/r/opensource/.rss'
    language = Language.ENGLISH


class LinuxGnuLinuxFreeSoftwareParsingModule(RedditRssBasicParsingModule):

    source_name = 'LinuxGnuLinuxFreeSoftware'
    projects = (
        os_friday_project,
    )
    rss_url = 'http://www.reddit.com/r/linux/.rss'
    language = Language.ENGLISH


class ContainerJournalParsingModule(SimpleRssBasicParsingModule):

    source_name = 'ContainerJournal'
    projects = (
        os_friday_project,
    )
    rss_url = 'http://containerjournal.com/feed/'
    language = Language.ENGLISH
    filtration_needed = True
    filters = (
        FiltrationType.SPECIFIC,
    )


class BlogCloudNativeComputingFoundationParsingModule(SimpleRssBasicParsingModule):

    source_name = 'BlogCloudNativeComputingFoundation'
    projects = (
        os_friday_project,
    )
    rss_url = 'https://cncf.io/blog/feed'
    language = Language.ENGLISH


class KubedexComParsingModule(SimpleRssBasicParsingModule):

    source_name = 'KubedexCom'
    projects = (
        os_friday_project,
    )
    rss_url = 'https://kubedex.com/feed/'
    language = Language.ENGLISH
    filtration_needed = True
    filters = (
        FiltrationType.SPECIFIC,
    )


class CiliumBlogParsingModule(SimpleRssBasicParsingModule):

    source_name = 'CiliumBlog'
    projects = (
        os_friday_project,
    )
    rss_url = 'https://cilium.io/blog/rss.xml'
    language = Language.ENGLISH
    filtration_needed = True
    filters = (
        FiltrationType.SPECIFIC,
    )


class EngineeringDockerBlogParsingModule(SimpleRssBasicParsingModule):

    source_name = 'EngineeringDockerBlog'
    projects = (
        os_friday_project,
    )
    rss_url = 'https://blog.docker.com/category/engineering/feed/'
    language = Language.ENGLISH


class BlogSysdigParsingModule(SimpleRssBasicParsingModule):

    source_name = 'BlogSysdig'
    projects = (
        os_friday_project,
    )
    rss_url = 'https://sysdig.com/blog/feed/'
    language = Language.ENGLISH
    filtration_needed = True
    filters = (
        FiltrationType.SPECIFIC,
    )


class CodefreshParsingModule(SimpleRssBasicParsingModule):

    source_name = 'Codefresh'
    projects = (
        os_friday_project,
    )
    rss_url = 'http://blog.codefresh.io/rss/'
    language = Language.ENGLISH
    filtration_needed = True
    filters = (
        FiltrationType.SPECIFIC,
    )


class AquaBlogParsingModule(SimpleRssBasicParsingModule):

    source_name = 'AquaBlog'
    projects = (
        os_friday_project,
    )
    rss_url = 'http://blog.aquasec.com/rss.xml'
    language = Language.ENGLISH
    filtration_needed = True
    filters = (
        FiltrationType.SPECIFIC,
    )


class AmbassadorApiGatewayParsingModule(SimpleRssBasicParsingModule):

    source_name = 'AmbassadorApiGateway'
    projects = (
        os_friday_project,
    )
    description_tag_name = 'content'
    rss_url = 'https://blog.getambassador.io/feed'
    language = Language.ENGLISH
    filtration_needed = True
    filters = (
        FiltrationType.SPECIFIC,
    )


class WeaveworksParsingModule(SimpleRssBasicParsingModule):

    source_name = 'Weaveworks'
    projects = (
        os_friday_project,
    )
    rss_url = 'https://www.weave.works/feed.xml'
    language = Language.ENGLISH
    filtration_needed = True
    filters = (
        FiltrationType.SPECIFIC,
    )


class KubeweeklyArchiveFeedParsingModule(SimpleRssBasicParsingModule):

    source_name = 'KubeweeklyArchiveFeed'
    projects = (
        os_friday_project,
    )
    rss_url = 'https://us10.campaign-archive.com/feed?u=3885586f8f1175194017967d6&id=11c1b8bcb2'
    language = Language.ENGLISH
    filtration_needed = True
    filters = (
        FiltrationType.SPECIFIC,
    )


class LachlanEvensonParsingModule(YouTubeComBasicParsingModule):

    source_name = 'LachlanEvenson'
    projects = (
        os_friday_project,
    )
    channel_id = 'UCC5NsnXM2lE6kKfJKdQgsRQ'
    language = Language.ENGLISH
    filtration_needed = True
    filters = (
        FiltrationType.SPECIFIC,
    )


class SoftwareDefinedTalkParsingModule(SimpleRssBasicParsingModule):

    source_name = 'SoftwareDefinedTalk'
    projects = (
        os_friday_project,
    )
    rss_url = 'http://feeds.feedburner.com/DrunkAndRetiredcomPodcast'
    language = Language.ENGLISH
    filtration_needed = True
    filters = (
        FiltrationType.SPECIFIC,
    )


class PrometheusBlogParsingModule(SimpleRssBasicParsingModule):

    source_name = 'PrometheusBlog'
    projects = (
        os_friday_project,
    )
    rss_url = 'http://prometheus.io/blog/feed.xml'
    language = Language.ENGLISH
    item_tag_name = 'entry'
    pubdate_tag_name = 'published'
    description_tag_name = 'content'

    def rss_items_root(self):
        return self.rss_data_root


class SysdigParsingModule(SimpleRssBasicParsingModule):

    source_name = 'Sysdig'
    projects = (
        os_friday_project,
    )
    rss_url = 'https://sysdig.com/feed/'
    language = Language.ENGLISH
    filtration_needed = True
    filters = (
        FiltrationType.SPECIFIC,
    )


class InnovateEverywhereOnRancherLabsParsingModule(SimpleRssBasicParsingModule):

    source_name = 'InnovateEverywhereOnRancherLabs'
    projects = (
        os_friday_project,
    )
    rss_url = 'http://rancher.com/feed/'
    language = Language.ENGLISH
    filtration_needed = True
    filters = (
        FiltrationType.SPECIFIC,
    )


class TheNewStackPodcastParsingModule(SimpleRssBasicParsingModule):

    source_name = 'TheNewStackPodcast'
    projects = (
        os_friday_project,
    )
    rss_url = 'https://feeds.simplecast.com/IgzWks06'
    language = Language.ENGLISH
    filtration_needed = True
    filters = (
        FiltrationType.SPECIFIC,
    )


class KubernetesOnMediumParsingModule(SimpleRssBasicParsingModule):

    source_name = 'KubernetesOnMedium'
    projects = (
        os_friday_project,
    )
    rss_url = 'https://medium.com/feed/tag/kubernetes'
    language = Language.ENGLISH


class RamblingsFromJessieParsingModule(SimpleRssBasicParsingModule):

    source_name = 'RamblingsFromJessie'
    projects = (
        os_friday_project,
    )
    rss_url = 'https://blog.jessfraz.com/index.xml'
    language = Language.ENGLISH
    filtration_needed = True
    filters = (
        FiltrationType.SPECIFIC,
    )


class DiscussKubernetesLatestTopicsParsingModule(SimpleRssBasicParsingModule):

    source_name = 'DiscussKubernetesLatestTopics'
    projects = (
        os_friday_project,
    )
    rss_url = 'https://discuss.kubernetes.io/latest.rss'
    language = Language.ENGLISH


class ProjectCalicoParsingModule(SimpleRssBasicParsingModule):

    source_name = 'ProjectCalico'
    projects = (
        os_friday_project,
    )
    rss_url = 'http://www.projectcalico.org/feed/'
    language = Language.ENGLISH


class LastWeekInKubernetesDevelopmentParsingModule(SimpleRssBasicParsingModule):

    source_name = 'LastWeekInKubernetesDevelopment'
    projects = (
        os_friday_project,
    )
    rss_url = 'http://lwkd.info/feed.xml'
    language = Language.ENGLISH
    item_tag_name = 'entry'
    pubdate_tag_name = 'published'
    description_tag_name = 'content'

    def rss_items_root(self):
        return self.rss_data_root


class KubernetesParsingModule(RedditRssBasicParsingModule):

    source_name = 'Kubernetes'
    projects = (
        os_friday_project,
    )
    rss_url = 'https://www.reddit.com/r/kubernetes/.rss'
    language = Language.ENGLISH


class EnvoyProxyParsingModule(SimpleRssBasicParsingModule):

    source_name = 'EnvoyProxy'
    projects = (
        os_friday_project,
    )
    rss_url = 'https://blog.envoyproxy.io/feed'
    language = Language.ENGLISH
    filtration_needed = True
    filters = (
        FiltrationType.SPECIFIC,
    )
    description_tag_name = 'content'


class TheNewStackAnalystsParsingModule(SimpleRssBasicParsingModule):

    source_name = 'TheNewStackAnalysts'
    projects = (
        os_friday_project,
    )
    rss_url = 'http://feeds.soundcloud.com/users/soundcloud:users:94518611/sounds.rss'
    language = Language.ENGLISH
    filtration_needed = True
    filters = (
        FiltrationType.SPECIFIC,
    )


class TigeraParsingModule(SimpleRssBasicParsingModule):

    source_name = 'Tigera'
    projects = (
        os_friday_project,
    )
    rss_url = 'https://blog.tigera.io/feed'
    language = Language.ENGLISH
    filtration_needed = True
    filters = (
        FiltrationType.SPECIFIC,
    )


class TwistlockParsingModule(SimpleRssBasicParsingModule):

    source_name = 'Twistlock'
    projects = (
        os_friday_project,
    )
    rss_url = 'https://www.twistlock.com/feed/'
    language = Language.ENGLISH
    filtration_needed = True
    filters = (
        FiltrationType.SPECIFIC,
    )


class BlogOnRancherLabsParsingModule(SimpleRssBasicParsingModule):

    source_name = 'BlogOnRancherLabs'
    projects = (
        os_friday_project,
    )
    rss_url = 'https://rancher.com/blog/index.xml'
    language = Language.ENGLISH
    filtration_needed = True
    filters = (
        FiltrationType.SPECIFIC,
    )


class TheNewStackParsingModule(SimpleRssBasicParsingModule):

    source_name = 'TheNewStack'
    projects = (
        os_friday_project,
    )
    rss_url = 'http://thenewstack.io/feed/'
    language = Language.ENGLISH
    filtration_needed = True
    filters = (
        FiltrationType.SPECIFIC,
    )


class KonghqParsingModule(SimpleRssBasicParsingModule):

    source_name = 'Konghq'
    projects = (
        os_friday_project,
    )
    rss_url = 'https://konghq.com/feed/'
    language = Language.ENGLISH
    filtration_needed = True
    filters = (
        FiltrationType.SPECIFIC,
    )


class DockerOnMediumParsingModule(SimpleRssBasicParsingModule):

    source_name = 'DockerOnMedium'
    projects = (
        os_friday_project,
    )
    rss_url = 'https://medium.com/feed/tag/docker'
    language = Language.ENGLISH


class DockerBlogParsingModule(SimpleRssBasicParsingModule):

    source_name = 'DockerBlog'
    projects = (
        os_friday_project,
    )
    rss_url = 'http://blog.docker.io/feed/'
    language = Language.ENGLISH


class DiscussKubernetesLatestPostsParsingModule(SimpleRssBasicParsingModule):

    source_name = 'DiscussKubernetesLatestPosts'
    projects = (
        os_friday_project,
    )
    rss_url = 'https://discuss.kubernetes.io/posts.rss'
    language = Language.ENGLISH


class D2IqBlogParsingModule(SimpleRssBasicParsingModule):

    source_name = 'D2IqBlog'
    projects = (
        os_friday_project,
    )
    rss_url = 'http://mesosphere.io/blog/atom.xml'
    language = Language.ENGLISH
    filtration_needed = True
    filters = (
        FiltrationType.SPECIFIC,
    )


class PodctlEnterpriseKubernetesParsingModule(SimpleRssBasicParsingModule):

    source_name = 'PodctlEnterpriseKubernetes'
    projects = (
        os_friday_project,
    )
    rss_url = 'https://www.buzzsprout.com/110399.rss'
    language = Language.ENGLISH


class IstioBlogAndNewsParsingModule(SimpleRssBasicParsingModule):

    source_name = 'IstioBlogAndNews'
    projects = (
        os_friday_project,
    )
    rss_url = 'https://istio.io/feed.xml'
    language = Language.ENGLISH

    def _parse(self):
        posts_data: List[PostData] = super()._parse()
        posts_data_with_fixed_urls = []
        for p in posts_data:
            if not re.fullmatch(r'^https://.*', p.url):
                p.url = f'https://istio.io{p.url}'
            posts_data_with_fixed_urls.append(p)
        return posts_data_with_fixed_urls


class ProgrammingKubernetesParsingModule(SimpleRssBasicParsingModule):

    source_name = 'ProgrammingKubernetes'
    projects = (
        os_friday_project,
    )
    rss_url = 'https://medium.com/feed/programming-kubernetes'
    language = Language.ENGLISH
    description_tag_name = 'content'


class KubernetesPodcastFromGoogleParsingModule(SimpleRssBasicParsingModule):

    source_name = 'KubernetesPodcastFromGoogle'
    projects = (
        os_friday_project,
    )
    rss_url = 'https://kubernetespodcast.com/feeds/audio.xml'
    language = Language.ENGLISH


class CloudNativeComputingFoundationParsingModule(SimpleRssBasicParsingModule):

    source_name = 'CloudNativeComputingFoundation'
    projects = (
        os_friday_project,
    )
    rss_url = 'https://www.cncf.io/feed'
    language = Language.ENGLISH


class BlogOnStackroxSecurityBuiltInParsingModule(SimpleRssBasicParsingModule):

    source_name = 'BlogOnStackroxSecurityBuiltIn'
    projects = (
        os_friday_project,
    )
    rss_url = 'https://www.stackrox.com/post/index.xml'
    language = Language.ENGLISH
    filtration_needed = True
    filters = (
        FiltrationType.SPECIFIC,
    )


class RecentQuestionsOpenSourceStackExchangeParsingModule(SimpleRssBasicParsingModule):

    source_name = 'RecentQuestionsOpenSourceStackExchange'
    projects = (
        os_friday_project,
    )
    rss_url = 'https://opensource.stackexchange.com/feeds'
    language = Language.ENGLISH
    description_tag_name = 'summary'
    item_tag_name = 'entry'
    pubdate_tag_name = 'published'

    def rss_items_root(self):
        return self.rss_data_root


class LxerLinuxNewsParsingModule(SimpleRssBasicParsingModule):

    source_name = 'LxerLinuxNews'
    projects = (
        os_friday_project,
    )
    rss_url = 'http://lxer.com/module/newswire/headlines.rss'
    language = Language.ENGLISH
    pubdate_tag_name = 'date'

    def rss_items_root(self):
        return self.rss_data_root


class NativecloudDevParsingModule(SimpleRssBasicParsingModule):

    source_name = 'NativecloudDev'
    projects = (
        os_friday_project,
    )
    rss_url = 'https://blog.nativecloud.dev/rss/'
    language = Language.ENGLISH
    filtration_needed = True
    filters = (
        FiltrationType.SPECIFIC,
    )


class LinuxlinksParsingModule(SimpleRssBasicParsingModule):

    source_name = 'Linuxlinks'
    projects = (
        os_friday_project,
    )
    rss_url = 'https://www.linuxlinks.com/feed/'
    language = Language.ENGLISH
    filtration_needed = True
    filters = (
        FiltrationType.SPECIFIC,
    )


class LobstersJavaJavaProgrammingParsingModule(SimpleRssBasicParsingModule):

    source_name = 'LobstersJavaJavaProgramming'
    projects = (
        os_friday_project,
    )
    rss_url = 'https://lobste.rs/t/java.rss'
    language = Language.ENGLISH


class FlossWeeklyVideoParsingModule(SimpleRssBasicParsingModule):

    source_name = 'FlossWeeklyVideo'
    projects = (
        os_friday_project,
    )
    rss_url = 'http://feeds.twit.tv/floss_video_hd.xml'
    language = Language.ENGLISH
    filtration_needed = True
    filters = (
        FiltrationType.SPECIFIC,
    )

    def _preprocess_date_str(self, date_str: str):
        return super()._preprocess_date_str(date_str.replace('PDT', 'UTC-07'))


class LobstersNodejsNodeJsProgrammingParsingModule(SimpleRssBasicParsingModule):

    source_name = 'LobstersNodejsNodeJsProgramming'
    projects = (
        os_friday_project,
    )
    rss_url = 'https://lobste.rs/t/nodejs.rss'
    language = Language.ENGLISH


class OpenSourceOnMediumParsingModule(SimpleRssBasicParsingModule):

    source_name = 'OpenSourceOnMedium'
    projects = (
        os_friday_project,
    )
    rss_url = 'https://medium.com/feed/tag/open-source'
    language = Language.ENGLISH


class BlogOnSmallstepParsingModule(SimpleRssBasicParsingModule):

    source_name = 'BlogOnSmallstep'
    projects = (
        os_friday_project,
    )
    rss_url = 'https://smallstep.com/blog/index.xml'
    language = Language.ENGLISH
    filtration_needed = True
    filters = (
        FiltrationType.SPECIFIC,
    )


class LinuxNotesFromDarkduckParsingModule(SimpleRssBasicParsingModule):

    source_name = 'LinuxNotesFromDarkduck'
    projects = (
        os_friday_project,
    )
    rss_url = 'http://feeds.feedburner.com/LinuxNotesFromDarkduck'
    language = Language.ENGLISH


class MicrosoftOpenSourceStoriesParsingModule(SimpleRssBasicParsingModule):

    source_name = 'MicrosoftOpenSourceStories'
    projects = (
        os_friday_project,
    )
    rss_url = 'https://medium.com/feed/microsoft-open-source-stories'
    language = Language.ENGLISH
    description_tag_name = 'content'


class LobstersUnixNixParsingModule(SimpleRssBasicParsingModule):

    source_name = 'LobstersUnixNix'
    projects = (
        os_friday_project,
    )
    rss_url = 'https://lobste.rs/t/unix.rss'
    language = Language.ENGLISH


class AmericanExpressTechnologyParsingModule(SimpleRssBasicParsingModule):

    source_name = 'AmericanExpressTechnology'
    projects = (
        os_friday_project,
    )
    rss_url = 'http://americanexpress.io/feed.xml'
    language = Language.ENGLISH
    item_tag_name = 'entry'
    filtration_needed = True
    filters = (
        FiltrationType.SPECIFIC,
    )
    description_tag_name = 'content'

    def rss_items_root(self):
        return self.rss_data_root


class NewestOpenSourceQuestionsFeedParsingModule(SimpleRssBasicParsingModule):

    source_name = 'NewestOpenSourceQuestionsFeed'
    projects = (
        os_friday_project,
    )
    rss_url = 'https://stackoverflow.com/feeds/tag?tagnames=open-source&sort=newest'
    language = Language.ENGLISH
    item_tag_name = 'entry'
    pubdate_tag_name = 'published'
    description_tag_name = 'summary'

    def rss_items_root(self):
        return self.rss_data_root


class TeejeetechParsingModule(SimpleRssBasicParsingModule):

    source_name = 'Teejeetech'
    projects = (
        os_friday_project,
    )
    rss_url = 'http://teejeetech.blogspot.com/feeds/posts/default'
    language = Language.ENGLISH
    filtration_needed = True
    filters = (
        FiltrationType.SPECIFIC,
    )


class FreedomPenguinParsingModule(SimpleRssBasicParsingModule):

    source_name = 'FreedomPenguin'
    projects = (
        os_friday_project,
    )
    rss_url = 'http://feeds.feedburner.com/FreedomPenguin'
    language = Language.ENGLISH


class LobstersLinuxLinuxParsingModule(SimpleRssBasicParsingModule):

    source_name = 'LobstersLinuxLinux'
    projects = (
        os_friday_project,
    )
    rss_url = 'https://lobste.rs/t/linux.rss'
    language = Language.ENGLISH


class CrunchToolsParsingModule(SimpleRssBasicParsingModule):

    source_name = 'CrunchTools'
    projects = (
        os_friday_project,
    )
    rss_url = 'http://crunchtools.com/feed/'
    language = Language.ENGLISH
    filtration_needed = True
    filters = (
        FiltrationType.SPECIFIC,
    )


class LinuxUprisingBlogParsingModule(SimpleRssBasicParsingModule):

    source_name = 'LinuxUprisingBlog'
    projects = (
        os_friday_project,
    )
    rss_url = 'https://feeds.feedburner.com/LinuxUprising'
    language = Language.ENGLISH
    item_tag_name = 'entry'
    pubdate_tag_name = 'published'
    description_tag_name = 'content'

    def rss_items_root(self):
        return self.rss_data_root


class EaglemanBlogParsingModule(SimpleRssBasicParsingModule):

    source_name = 'EaglemanBlog'
    projects = (
        os_friday_project,
    )
    rss_url = 'http://www.eagleman.com/blog?format=feed&type=rss'
    language = Language.ENGLISH
    filtration_needed = True
    filters = (
        FiltrationType.SPECIFIC,
    )


class DbakevlarParsingModule(SimpleRssBasicParsingModule):

    source_name = 'Dbakevlar'
    projects = (
        os_friday_project,
    )
    rss_url = 'https://dbakevlar.com/feed/'
    language = Language.ENGLISH
    filtration_needed = True
    filters = (
        FiltrationType.SPECIFIC,
    )


class EngblogRuParsingModule(SimpleRssBasicParsingModule):

    source_name = 'EngblogRu'
    projects = (
        os_friday_project,
    )
    rss_url = 'http://feeds.feedburner.com/engblogru'
    language = Language.RUSSIAN
    filtration_needed = True
    filters = (
        FiltrationType.SPECIFIC,
    )


class LobstersDotnetCFNetProgrammingParsingModule(SimpleRssBasicParsingModule):

    source_name = 'LobstersDotnetCFNetProgramming'
    projects = (
        os_friday_project,
    )
    rss_url = 'https://lobste.rs/t/dotnet.rss'
    language = Language.ENGLISH
    filtration_needed = True
    filters = (
        FiltrationType.SPECIFIC,
    )


class LobstersWebWebDevelopmentAndNewsParsingModule(SimpleRssBasicParsingModule):

    source_name = 'LobstersWebWebDevelopmentAndNews'
    projects = (
        os_friday_project,
    )
    rss_url = 'https://lobste.rs/t/web.rss'
    language = Language.ENGLISH
    filtration_needed = True
    filters = (
        FiltrationType.SPECIFIC,
    )


class MorningDewByAlvinAshcraftParsingModule(SimpleRssBasicParsingModule):

    source_name = 'MorningDewByAlvinAshcraft'
    projects = (
        os_friday_project,
    )
    rss_url = 'http://feeds2.feedburner.com/alvinashcraft'
    language = Language.ENGLISH
    filtration_needed = True
    filters = (
        FiltrationType.SPECIFIC,
    )


class LobstersSecurityNetsecAppsecAndInfosecParsingModule(SimpleRssBasicParsingModule):

    source_name = 'LobstersSecurityNetsecAppsecAndInfosec'
    projects = (
        os_friday_project,
    )
    rss_url = 'https://lobste.rs/t/security.rss'
    language = Language.ENGLISH
    filtration_needed = True
    filters = (
        FiltrationType.SPECIFIC,
    )


class SamJarManParsingModule(SimpleRssBasicParsingModule):

    source_name = 'SamJarMan'
    projects = (
        os_friday_project,
    )
    rss_url = 'https://www.samjarman.co.nz/blog?format=RSS'
    language = Language.ENGLISH
    filtration_needed = True
    filters = (
        FiltrationType.SPECIFIC,
    )


class LobstersDistributedDistributedSystemsParsingModule(SimpleRssBasicParsingModule):

    source_name = 'LobstersDistributedDistributedSystems'
    projects = (
        os_friday_project,
    )
    rss_url = 'https://lobste.rs/t/distributed.rss'
    language = Language.ENGLISH
    filtration_needed = True
    filters = (
        FiltrationType.SPECIFIC,
    )


class LobstersDevopsDevopsParsingModule(SimpleRssBasicParsingModule):

    source_name = 'LobstersDevopsDevops'
    projects = (
        os_friday_project,
    )
    rss_url = 'https://lobste.rs/t/devops.rss'
    language = Language.ENGLISH
    filtration_needed = True
    filters = (
        FiltrationType.SPECIFIC,
    )


class DevRelWeeklyParsingModule(SimpleRssBasicParsingModule):

    source_name = 'DevRelWeekly'
    projects = (
        os_friday_project,
    )
    rss_url = 'http://devrelweekly.com/issues.rss'
    language = Language.ENGLISH
    filtration_needed = True
    filters = (
        FiltrationType.SPECIFIC,
    )


class AzureAdvocatesContentWrapUpParsingModule(SimpleRssBasicParsingModule):

    source_name = 'AzureAdvocatesContentWrapUp'
    projects = (
        os_friday_project,
    )
    rss_url = 'https://www.onazure.today/feed.xml'
    language = Language.ENGLISH
    filtration_needed = True
    filters = (
        FiltrationType.SPECIFIC,
    )


class FlantBlogParsingModule(SimpleRssBasicParsingModule):

    source_name = 'FlantBlog'
    projects = (
        os_friday_project,
    )
    rss_url = 'https://blog.flant.com/feed/'
    language = Language.ENGLISH
    filtration_needed = True
    filters = (
        FiltrationType.SPECIFIC,
    )


class ThoughtworksInsightsParsingModule(SimpleRssBasicParsingModule):

    source_name = 'ThoughtworksInsights'
    projects = (
        os_friday_project,
    )
    rss_url = 'http://www.thoughtworks.com/rss/insights.xml'
    language = Language.ENGLISH
    filtration_needed = True
    filters = (
        FiltrationType.SPECIFIC,
    )
    description_tag_name = 'summary'

    item_tag_name = 'entry'

    def rss_items_root(self):
        return self.rss_data_root


class LobstersOsdevOperatingSystemDesignAndDevelopmentWhenNoSpecificOsTagExistsParsingModule(SimpleRssBasicParsingModule):

    source_name = 'LobstersOsdevOperatingSystemDesignAndDevelopmentWhenNoSpecificOsTagExists'
    projects = (
        os_friday_project,
    )
    rss_url = 'https://lobste.rs/t/osdev.rss'
    language = Language.ENGLISH


class MicrosoftDevradioParsingModule(YouTubeComBasicParsingModule):

    source_name = 'MicrosoftDevradio'
    projects = (
        os_friday_project,
    )
    channel_id = 'UCYjPVPCNwQyfbQEKlJ4ChHg'
    language = Language.ENGLISH
    filtration_needed = True
    filters = (
        FiltrationType.SPECIFIC,
    )


class NewBlogArticlesInMicrosoftTechCommunityParsingModule(SimpleRssBasicParsingModule):

    source_name = 'NewBlogArticlesInMicrosoftTechCommunity'
    projects = (
        os_friday_project,
    )
    rss_url = 'https://techcommunity.microsoft.com/gxcuf89792/rss/Community?interaction.style=blog'
    language = Language.ENGLISH
    filtration_needed = True
    filters = (
        FiltrationType.SPECIFIC,
    )


class FosslifeParsingModule(SimpleRssBasicParsingModule):

    source_name = 'Fosslife'
    projects = (
        os_friday_project,
    )
    rss_url = 'https://www.fosslife.org/rss.xml'
    language = Language.ENGLISH


class AzureInfohubRssAzureParsingModule(SimpleRssBasicParsingModule):

    source_name = 'AzureInfohubRssAzure'
    projects = (
        os_friday_project,
    )
    rss_url = 'https://azureinfohub.azurewebsites.net/Feed?serviceTitle=Azure'
    language = Language.ENGLISH
    filtration_needed = True
    filters = (
        FiltrationType.SPECIFIC,
    )


class PerformanceIsAFeatureParsingModule(SimpleRssBasicParsingModule):

    source_name = 'PerformanceIsAFeature'
    projects = (
        os_friday_project,
    )
    rss_url = 'http://mattwarren.org/atom.xml'
    language = Language.ENGLISH
    filtration_needed = True
    filters = (
        FiltrationType.SPECIFIC,
    )

    item_tag_name = 'entry'
    pubdate_tag_name = 'updated'
    description_tag_name = 'content'

    def rss_items_root(self):
        return self.rss_data_root


class LobstersWasmWebassemblyParsingModule(SimpleRssBasicParsingModule):

    source_name = 'LobstersWasmWebassembly'
    projects = (
        os_friday_project,
    )
    rss_url = 'https://lobste.rs/t/wasm.rss'
    language = Language.ENGLISH
    filtration_needed = True
    filters = (
        FiltrationType.SPECIFIC,
    )


class TheCommunityRoundtableParsingModule(SimpleRssBasicParsingModule):

    source_name = 'TheCommunityRoundtable'
    projects = (
        os_friday_project,
    )
    rss_url = 'https://communityroundtable.com/feed/'
    language = Language.ENGLISH
    filtration_needed = True
    filters = (
        FiltrationType.SPECIFIC,
    )


class Rss20TaggedMobileMobileAppWebDevelopmentParsingModule(SimpleRssBasicParsingModule):

    source_name = 'Rss20TaggedMobileMobileAppWebDevelopment'
    projects = (
        os_friday_project,
    )
    rss_url = 'https://lobste.rs/t/mobile.rss'
    language = Language.ENGLISH
    filtration_needed = True
    filters = (
        FiltrationType.SPECIFIC,
    )


class AwsArchitectureBlogParsingModule(SimpleRssBasicParsingModule):

    source_name = 'AwsArchitectureBlog'
    projects = (
        os_friday_project,
    )
    rss_url = 'http://www.awsarchitectureblog.com/atom.xml'
    language = Language.ENGLISH
    filtration_needed = True
    filters = (
        FiltrationType.SPECIFIC,
    )


class HeptioUploadsOnYoutubeParsingModule(YouTubePlaylistBasicParsingModule):

    source_name = 'HeptioUploadsOnYoutube'
    projects = (
        os_friday_project,
    )
    playlist_id = 'UUjQU5ZI2mHswy7OOsii_URg'
    language = Language.ENGLISH
    filtration_needed = True
    filters = (
        FiltrationType.SPECIFIC,
    )


class AlexEllisOpenfaasCommunityAwesomenessOnYoutubeParsingModule(YouTubePlaylistBasicParsingModule):

    source_name = 'AlexEllisOpenfaasCommunityAwesomenessOnYoutube'
    projects = (
        os_friday_project,
    )
    playlist_id = 'PLlIapFDp305Cw4Mu13Oq--AEk0G0WXPO-'
    language = Language.ENGLISH
    filtration_needed = True
    filters = (
        FiltrationType.SPECIFIC,
    )


class VmwareCloudNativeAppsUploadsOnYoutubeParsingModule(YouTubePlaylistBasicParsingModule):

    source_name = 'VmwareCloudNativeAppsUploadsOnYoutube'
    projects = (
        os_friday_project,
    )
    playlist_id = 'UUdkGV51Nu0unDNT58bHt9bg'
    language = Language.ENGLISH
    filtration_needed = True
    filters = (
        FiltrationType.SPECIFIC,
    )


class D2IqParsingModule(SimpleRssBasicParsingModule):

    source_name = 'D2Iq'
    projects = (
        os_friday_project,
    )
    # TODO: Fix
    rss_url = 'https://www.youtube.com/feeds/videos.xml?channel_id=UCxwCmgwyM7xtHaRULN6-dxg'
    language = Language.ENGLISH
    filtration_needed = True
    filters = (
        FiltrationType.SPECIFIC,
    )


class TigeraUploadsOnYoutubeParsingModule(YouTubePlaylistBasicParsingModule):

    source_name = 'TigeraUploadsOnYoutube'
    projects = (
        os_friday_project,
    )
    playlist_id = 'UU8uN3yhpeBeerGNwDiQbcgw'
    language = Language.ENGLISH
    filtration_needed = True
    filters = (
        FiltrationType.SPECIFIC,
    )


class CncfCloudNativeComputingFoundationUploadsOnYoutubeParsingModule(YouTubePlaylistBasicParsingModule):

    source_name = 'CncfCloudNativeComputingFoundationUploadsOnYoutube'
    projects = (
        os_friday_project,
    )
    playlist_id = 'UUvqbFHwN-nwalWPjPUKpvTA'
    language = Language.ENGLISH


class CephUploadsOnYoutubeParsingModule(YouTubePlaylistBasicParsingModule):

    source_name = 'CephUploadsOnYoutube'
    projects = (
        os_friday_project,
    )
    playlist_id = 'UUno-Fry25FJ7B4RycCxOtfw'
    language = Language.ENGLISH


class RookRookPresentationsOnYoutubeParsingModule(YouTubePlaylistBasicParsingModule):

    source_name = 'RookRookPresentationsOnYoutube'
    projects = (
        os_friday_project,
    )
    playlist_id = 'PLP0uDo-ZFnQOCpYx1_uVCrx_bmyq7tdKr'
    language = Language.ENGLISH
    filtration_needed = True
    filters = (
        FiltrationType.SPECIFIC,
    )


class DockerParsingModule(SimpleRssBasicParsingModule):

    source_name = 'Docker'
    projects = (
        os_friday_project,
    )
    # TODO: Fix
    rss_url = 'https://www.youtube.com/feeds/videos.xml?channel_id=UC76AVf2JkrwjxNKMuPpscHQ'
    language = Language.ENGLISH


class RookUploadsOnYoutubeParsingModule(YouTubePlaylistBasicParsingModule):

    source_name = 'RookUploadsOnYoutube'
    projects = (
        os_friday_project,
    )
    playlist_id = 'UUa7kFUSGO4NNSJV8MJVlJAA'
    language = Language.ENGLISH
    filtration_needed = True
    filters = (
        FiltrationType.SPECIFIC,
    )


class CncfCloudNativeComputingFoundationParsingModule(YouTubeComBasicParsingModule):

    source_name = 'CncfCloudNativeComputingFoundation'
    projects = (
        os_friday_project,
    )
    channel_id = 'UCvqbFHwN-nwalWPjPUKpvTA'
    language = Language.ENGLISH


class WeaveworksIncWeaveOnlineUserGroupsOnYoutubeParsingModule(YouTubePlaylistBasicParsingModule):

    source_name = 'WeaveworksIncWeaveOnlineUserGroupsOnYoutube'
    projects = (
        os_friday_project,
    )
    playlist_id = 'PL9lTuCFNLaD0wEsbqf6IrGCWvZIAIo9cW'
    language = Language.ENGLISH
    filtration_needed = True
    filters = (
        FiltrationType.SPECIFIC,
    )


class KubernautsIoUploadsOnYoutubeParsingModule(YouTubePlaylistBasicParsingModule):

    source_name = 'KubernautsIoUploadsOnYoutube'
    projects = (
        os_friday_project,
    )
    playlist_id = 'UU5NDQ4F0JPQozyqnh1mghHQ'
    language = Language.ENGLISH


class AlexEllisUploadsOnYoutubeParsingModule(YouTubePlaylistBasicParsingModule):

    source_name = 'AlexEllisUploadsOnYoutube'
    projects = (
        os_friday_project,
    )
    playlist_id = 'UUJsK5Zbq0dyFZUBtMTHzxjQ'
    language = Language.ENGLISH
    filtration_needed = True
    filters = (
        FiltrationType.SPECIFIC,
    )


class CephCephTestingWeeklyOnYoutubeParsingModule(YouTubePlaylistBasicParsingModule):

    source_name = 'CephCephTestingWeeklyOnYoutube'
    projects = (
        os_friday_project,
    )
    playlist_id = 'PLrBUGiINAakMV7gKMQjFvcWL3PeY0y0lq'
    language = Language.ENGLISH


class NetCurryRecentArticlesParsingModule(SimpleRssBasicParsingModule):

    source_name = 'NetCurryRecentArticles'
    projects = (
        os_friday_project,
    )
    rss_url = 'http://feeds.feedburner.com/netCurryRecentArticles'
    language = Language.ENGLISH
    filtration_needed = True
    filters = (
        FiltrationType.SPECIFIC,
    )


class ThreeHundredSixtyDegreeDbProgrammingParsingModule(SimpleRssBasicParsingModule):

    source_name = 'ThreeHundredSixtyDegreeDbProgramming'
    projects = (
        os_friday_project,
    )
    rss_url = 'http://db360.blogspot.com/feeds/posts/default'
    language = Language.ENGLISH
    filtration_needed = True
    filters = (
        FiltrationType.SPECIFIC,
    )
    description_tag_name = 'content'

    item_tag_name = 'entry'

    def rss_items_root(self):
        return self.rss_data_root


class FourSysopsParsingModule(SimpleRssBasicParsingModule):

    source_name = 'FourSysops'
    projects = (
        os_friday_project,
    )
    rss_url = 'http://4sysops.com/feed/'
    language = Language.ENGLISH
    filtration_needed = True
    filters = (
        FiltrationType.SPECIFIC,
    )


class AProgrammerWithMicrosoftToolsParsingModule(SimpleRssBasicParsingModule):

    source_name = 'AProgrammerWithMicrosoftTools'
    projects = (
        os_friday_project,
    )
    rss_url = 'http://msprogrammer.serviciipeweb.ro/feed/'
    language = Language.ENGLISH
    filtration_needed = True
    filters = (
        FiltrationType.SPECIFIC,
    )


class AarononthewebParsingModule(SimpleRssBasicParsingModule):

    source_name = 'Aaronontheweb'
    projects = (
        os_friday_project,
    )
    rss_url = 'http://www.aaronstannard.com/syndication.axd'
    language = Language.ENGLISH
    filtration_needed = True
    filters = (
        FiltrationType.SPECIFIC,
    )


class AllanSBlogParsingModule(SimpleRssBasicParsingModule):

    source_name = 'AllanSBlog'
    projects = (
        os_friday_project,
    )
    rss_url = 'http://sqlha.com/blog/feed/'
    language = Language.ENGLISH
    filtration_needed = True
    filters = (
        FiltrationType.SPECIFIC,
    )


class AndyGibsonParsingModule(SimpleRssBasicParsingModule):

    source_name = 'AndyGibson'
    projects = (
        os_friday_project,
    )
    rss_url = 'http://www.andygibson.net/blog/feed/'
    language = Language.ENGLISH
    filtration_needed = True
    filters = (
        FiltrationType.SPECIFIC,
    )


class AntonioSBlogParsingModule(SimpleRssBasicParsingModule):

    source_name = 'AntonioSBlog'
    projects = (
        os_friday_project,
    )
    rss_url = 'http://agoncal.wordpress.com/feed/'
    language = Language.ENGLISH
    filtration_needed = True
    filters = (
        FiltrationType.SPECIFIC,
    )


class ArcaneCodeParsingModule(SimpleRssBasicParsingModule):

    source_name = 'ArcaneCode'
    projects = (
        os_friday_project,
    )
    rss_url = 'http://feeds.feedburner.com/ArcaneCode'
    language = Language.ENGLISH
    filtration_needed = True
    filters = (
        FiltrationType.SPECIFIC,
    )


class AugustoAlvarezParsingModule(SimpleRssBasicParsingModule):

    source_name = 'AugustoAlvarez'
    projects = (
        os_friday_project,
    )
    rss_url = 'http://feeds.feedburner.com/AugustoAlvarez'
    language = Language.ENGLISH
    filtration_needed = True
    filters = (
        FiltrationType.SPECIFIC,
    )


class Channel9ParsingModule(SimpleRssBasicParsingModule):

    source_name = 'Channel9'
    projects = (
        os_friday_project,
    )
    rss_url = 'http://channel9.msdn.com/Feeds/RSS'
    language = Language.ENGLISH
    filtration_needed = True
    filters = (
        FiltrationType.SPECIFIC,
    )


class CloudComputingBigDataHpcCodeinstinctParsingModule(SimpleRssBasicParsingModule):

    source_name = 'CloudComputingBigDataHpcCodeinstinct'
    projects = (
        os_friday_project,
    )
    rss_url = 'http://www.codeinstinct.pro/feeds/posts/default'
    language = Language.ENGLISH
    filtration_needed = True
    filters = (
        FiltrationType.SPECIFIC,
    )
    item_tag_name = 'entry'
    pubdate_tag_name = 'published'
    description_tag_name = 'content'

    def rss_items_root(self):
        return self.rss_data_root


class ClusteringForMereMortalsParsingModule(SimpleRssBasicParsingModule):

    source_name = 'ClusteringForMereMortals'
    projects = (
        os_friday_project,
    )
    rss_url = 'http://clusteringformeremortals.com/feed/'
    language = Language.ENGLISH
    filtration_needed = True
    filters = (
        FiltrationType.SPECIFIC,
    )


class CommandLineFanaticParsingModule(SimpleRssBasicParsingModule):

    source_name = 'CommandLineFanatic'
    projects = (
        os_friday_project,
    )
    rss_url = 'http://commandlinefanatic.com/rss.xml'
    language = Language.ENGLISH
    filtration_needed = True
    filters = (
        FiltrationType.SPECIFIC,
    )

    def _preprocess_date_str(self, date_str: str):
        return super()._preprocess_date_str(date_str.replace('- 0700', 'UTC-07'));


class DevcurryParsingModule(SimpleRssBasicParsingModule):

    source_name = 'Devcurry'
    projects = (
        os_friday_project,
    )
    rss_url = 'http://www.devcurry.com/feeds/posts/default/'
    language = Language.ENGLISH
    filtration_needed = True
    filters = (
        FiltrationType.SPECIFIC,
    )


class DonTBeIffyParsingModule(SimpleRssBasicParsingModule):

    source_name = 'DonTBeIffy'
    projects = (
        os_friday_project,
    )
    rss_url = 'http://thedatafarm.com/blog/feed/'
    language = Language.ENGLISH
    filtration_needed = True
    filters = (
        FiltrationType.SPECIFIC,
    )
    description_tag_name = 'content'


class ElegantCodeParsingModule(SimpleRssBasicParsingModule):

    source_name = 'ElegantCode'
    projects = (
        os_friday_project,
    )
    rss_url = 'http://feeds.feedburner.com/ElegantCode'
    language = Language.ENGLISH
    filtration_needed = True
    filters = (
        FiltrationType.SPECIFIC,
    )


class FelipeOliveiraParsingModule(SimpleRssBasicParsingModule):

    source_name = 'FelipeOliveira'
    projects = (
        os_friday_project,
    )
    rss_url = 'http://feeds.feedburner.com/GeeksAreTotallyIn'
    language = Language.ENGLISH
    filtration_needed = True
    filters = (
        FiltrationType.SPECIFIC,
    )


class FromRavikanthSBlogParsingModule(SimpleRssBasicParsingModule):

    source_name = 'FromRavikanthSBlog'
    projects = (
        os_friday_project,
    )
    rss_url = 'http://feeds.feedburner.com/RavikanthChaganti'
    language = Language.ENGLISH
    filtration_needed = True
    filters = (
        FiltrationType.SPECIFIC,
    )


class FullFeedParsingModule(SimpleRssBasicParsingModule):

    source_name = 'FullFeed'
    projects = (
        os_friday_project,
    )
    rss_url = 'http://feeds.addedbytes.com/added_bytes_full'
    language = Language.ENGLISH
    filtration_needed = True
    filters = (
        FiltrationType.SPECIFIC,
    )


class GauravmantriComParsingModule(SimpleRssBasicParsingModule):

    source_name = 'GauravmantriCom'
    projects = (
        os_friday_project,
    )
    rss_url = 'http://gauravmantri.com/feed/'
    language = Language.ENGLISH
    filtration_needed = True
    filters = (
        FiltrationType.SPECIFIC,
    )


class GeekSucksParsingModule(SimpleRssBasicParsingModule):

    source_name = 'GeekSucks'
    projects = (
        os_friday_project,
    )
    rss_url = 'http://feeds.feedburner.com/GeekSucks'
    language = Language.ENGLISH
    filtration_needed = True
    filters = (
        FiltrationType.SPECIFIC,
    )


class GoodCodersCodeGreatReuseParsingModule(SimpleRssBasicParsingModule):

    source_name = 'GoodCodersCodeGreatReuse'
    projects = (
        os_friday_project,
    )
    rss_url = 'http://www.catonmat.net/feed/'
    language = Language.ENGLISH
    filtration_needed = True
    filters = (
        FiltrationType.SPECIFIC,
    )


class GunnarPeipmanSAspNetBlogParsingModule(SimpleRssBasicParsingModule):

    source_name = 'GunnarPeipmanSAspNetBlog'
    projects = (
        os_friday_project,
    )
    rss_url = 'http://feeds.feedburner.com/gunnarpeipman'
    language = Language.ENGLISH
    filtration_needed = True
    filters = (
        FiltrationType.SPECIFIC,
    )
    description_tag_name = 'content'


class HanselminutesParsingModule(SimpleRssBasicParsingModule):

    source_name = 'Hanselminutes'
    projects = (
        os_friday_project,
    )
    rss_url = 'http://feeds.feedburner.com/HanselminutesCompleteMP3'
    language = Language.ENGLISH
    filtration_needed = True
    filters = (
        FiltrationType.SPECIFIC,
    )


class HelpDeskGeekHelpDeskTipsForItProsParsingModule(SimpleRssBasicParsingModule):

    source_name = 'HelpDeskGeekHelpDeskTipsForItPros'
    projects = (
        os_friday_project,
    )
    rss_url = 'http://feedproxy.google.com/ITHelpDeskGeek'
    language = Language.ENGLISH
    filtration_needed = True
    filters = (
        FiltrationType.SPECIFIC,
    )


class HenrikOlssonSComputerSoftwareNotesParsingModule(SimpleRssBasicParsingModule):

    source_name = 'HenrikOlssonSComputerSoftwareNotes'
    projects = (
        os_friday_project,
    )
    rss_url = 'http://holsson.wordpress.com/feed/'
    language = Language.ENGLISH
    filtration_needed = True
    filters = (
        FiltrationType.SPECIFIC,
    )


class HongkiatComParsingModule(SimpleRssBasicParsingModule):

    source_name = 'HongkiatCom'
    projects = (
        os_friday_project,
    )
    rss_url = 'http://www.hongkiat.com/blog/feed/'
    language = Language.ENGLISH
    filtration_needed = True
    filters = (
        FiltrationType.SPECIFIC,
    )


class IcosmogeekParsingModule(SimpleRssBasicParsingModule):

    source_name = 'Icosmogeek'
    projects = (
        os_friday_project,
    )
    rss_url = 'http://feeds.feedburner.com/cosmogeekinfo'
    language = Language.ENGLISH
    filtration_needed = True
    filters = (
        FiltrationType.SPECIFIC,
    )
    description_tag_name = 'content'


class InDepthFeaturesParsingModule(SimpleRssBasicParsingModule):

    source_name = 'InDepthFeatures'
    projects = (
        os_friday_project,
    )
    rss_url = 'http://redmondmag.com/rss-feeds/in-depth.aspx'
    language = Language.ENGLISH
    filtration_needed = True
    filters = (
        FiltrationType.SPECIFIC,
    )


class JenkovComNewsParsingModule(SimpleRssBasicParsingModule):

    source_name = 'JenkovComNews'
    projects = (
        os_friday_project,
    )
    rss_url = 'http://feeds2.feedburner.com/jenkov-com?format=xml'
    language = Language.ENGLISH
    filtration_needed = True
    filters = (
        FiltrationType.SPECIFIC,
    )


class JonathanGKoomeyPhDParsingModule(SimpleRssBasicParsingModule):

    source_name = 'JonathanGKoomeyPhD'
    projects = (
        os_friday_project,
    )
    rss_url = 'http://www.koomey.com/rss'
    language = Language.ENGLISH
    filtration_needed = True
    filters = (
        FiltrationType.SPECIFIC,
    )


class KScottAllenParsingModule(SimpleRssBasicParsingModule):

    source_name = 'KScottAllen'
    projects = (
        os_friday_project,
    )
    rss_url = 'http://feeds.feedburner.com/OdeToCode'
    language = Language.ENGLISH
    filtration_needed = True
    filters = (
        FiltrationType.SPECIFIC,
    )


class MaartenBalliauwBlogParsingModule(SimpleRssBasicParsingModule):

    source_name = 'MaartenBalliauwBlog'
    projects = (
        os_friday_project,
    )
    rss_url = 'http://feeds2.feedburner.com/maartenballiauw'
    language = Language.ENGLISH
    filtration_needed = True
    filters = (
        FiltrationType.SPECIFIC,
    )


class MarceloSincicMvpParsingModule(SimpleRssBasicParsingModule):

    source_name = 'MarceloSincicMvp'
    projects = (
        os_friday_project,
    )
    rss_url = 'http://msincic.wordpress.com/feed/'
    language = Language.ENGLISH
    filtration_needed = True
    filters = (
        FiltrationType.SPECIFIC,
    )


class MartinFowlerParsingModule(SimpleRssBasicParsingModule):

    source_name = 'MartinFowler'
    projects = (
        os_friday_project,
    )
    rss_url = 'http://martinfowler.com/feed.atom'
    language = Language.ENGLISH
    filtration_needed = True
    filters = (
        FiltrationType.SPECIFIC,
    )
    item_tag_name = 'entry'
    pubdate_tag_name = 'updated'
    description_tag_name = 'content'

    def rss_items_root(self):
        return self.rss_data_root


class MaxTrinidadThePowershellFrontParsingModule(SimpleRssBasicParsingModule):

    source_name = 'MaxTrinidadThePowershellFront'
    projects = (
        os_friday_project,
    )
    rss_url = 'http://www.maxtblog.com/rss'
    language = Language.ENGLISH
    filtration_needed = True
    filters = (
        FiltrationType.SPECIFIC,
    )


class MethodOfFailedByTimHeuerParsingModule(SimpleRssBasicParsingModule):

    source_name = 'MethodOfFailedByTimHeuer'
    projects = (
        os_friday_project,
    )
    rss_url = 'http://feeds.timheuer.com/timheuer'
    language = Language.ENGLISH
    filtration_needed = True
    filters = (
        FiltrationType.SPECIFIC,
    )


class MichaelCrumpParsingModule(SimpleRssBasicParsingModule):

    source_name = 'MichaelCrump'
    projects = (
        os_friday_project,
    )
    rss_url = 'http://feeds.feedburner.com/MichaelCrump'
    language = Language.ENGLISH
    filtration_needed = True
    filters = (
        FiltrationType.SPECIFIC,
    )
    item_tag_name = 'entry'
    pubdate_tag_name = 'published'
    description_tag_name = 'content'

    def rss_items_root(self):
        return self.rss_data_root


class NewsParsingModule(SimpleRssBasicParsingModule):

    source_name = 'News'
    projects = (
        os_friday_project,
    )
    rss_url = 'http://mcpmag.com/rss-feeds/news.aspx'
    language = Language.ENGLISH
    filtration_needed = True
    filters = (
        FiltrationType.SPECIFIC,
    )


class PetriItKnowledgebaseParsingModule(SimpleRssBasicParsingModule):

    source_name = 'PetriItKnowledgebase'
    projects = (
        os_friday_project,
    )
    rss_url = 'http://feeds2.feedburner.com/Petri'
    language = Language.ENGLISH
    filtration_needed = True
    filters = (
        FiltrationType.SPECIFIC,
    )


class PrecisionComputingParsingModule(SimpleRssBasicParsingModule):

    source_name = 'PrecisionComputing'
    projects = (
        os_friday_project,
    )
    rss_url = 'http://www.leeholmes.com/blog/feed/atom/'
    language = Language.ENGLISH
    filtration_needed = True
    filters = (
        FiltrationType.SPECIFIC,
    )


class PublisherSRoundUpParsingModule(SimpleRssBasicParsingModule):

    source_name = 'PublisherSRoundUp'
    projects = (
        os_friday_project,
    )
    rss_url = 'http://wmjasco.blogspot.com/feeds/posts/default'
    language = Language.ENGLISH
    filtration_needed = True
    filters = (
        FiltrationType.SPECIFIC,
    )
    item_tag_name = 'entry'
    pubdate_tag_name = 'published'
    description_tag_name = 'content'

    def rss_items_root(self):
        return self.rss_data_root


class RandsInReposeParsingModule(SimpleRssBasicParsingModule):

    source_name = 'RandsInRepose'
    projects = (
        os_friday_project,
    )
    rss_url = 'http://www.randsinrepose.com/index.xml'
    language = Language.ENGLISH
    filtration_needed = True
    filters = (
        FiltrationType.SPECIFIC,
    )


class RedmondReportParsingModule(SimpleRssBasicParsingModule):

    source_name = 'RedmondReport'
    projects = (
        os_friday_project,
    )
    rss_url = 'http://redmondmag.com/rss-feeds/redmond-report.aspx'
    language = Language.ENGLISH
    filtration_needed = True
    filters = (
        FiltrationType.SPECIFIC,
    )


class RhyousParsingModule(SimpleRssBasicParsingModule):

    source_name = 'Rhyous'
    projects = (
        os_friday_project,
    )
    rss_url = 'http://www.rhyous.com/feed/'
    language = Language.ENGLISH
    filtration_needed = True
    filters = (
        FiltrationType.SPECIFIC,
    )


class RichardSeroterSArchitectureMusingsParsingModule(SimpleRssBasicParsingModule):

    source_name = 'RichardSeroterSArchitectureMusings'
    projects = (
        os_friday_project,
    )
    rss_url = 'http://seroter.wordpress.com/feed/'
    language = Language.ENGLISH
    filtration_needed = True
    filters = (
        FiltrationType.SPECIFIC,
    )


class RickStrahlSWebLogParsingModule(SimpleRssBasicParsingModule):

    source_name = 'RickStrahlSWebLog'
    projects = (
        os_friday_project,
    )
    rss_url = 'http://feedproxy.google.com/rickstrahl'
    language = Language.ENGLISH
    filtration_needed = True
    filters = (
        FiltrationType.SPECIFIC,
    )


class SdmSoftwareParsingModule(SimpleRssBasicParsingModule):

    source_name = 'SdmSoftware'
    projects = (
        os_friday_project,
    )
    rss_url = 'http://www.sdmsoftware.com/feed/'
    language = Language.ENGLISH
    filtration_needed = True
    filters = (
        FiltrationType.SPECIFIC,
    )


class SecretgeekParsingModule(SimpleRssBasicParsingModule):

    source_name = 'Secretgeek'
    projects = (
        os_friday_project,
    )
    rss_url = 'http://secretgeek.net/rss.asp'
    language = Language.ENGLISH
    filtration_needed = True
    filters = (
        FiltrationType.SPECIFIC,
    )

    def _preprocess_xml(self, text: str):
        return super()._preprocess_xml(text.replace('ï»¿', ''))


class ShawnWildermuthSBlogParsingModule(SimpleRssBasicParsingModule):

    source_name = 'ShawnWildermuthSBlog'
    projects = (
        os_friday_project,
    )
    rss_url = 'http://feeds.feedburner.com/ShawnWildermuth'
    language = Language.ENGLISH
    filtration_needed = True
    filters = (
        FiltrationType.SPECIFIC,
    )
    item_tag_name = 'entry'
    pubdate_tag_name = 'updated'
    description_tag_name = 'content'

    def rss_items_root(self):
        return self.rss_data_root


class SimpleTalkRssFeedParsingModule(SimpleRssBasicParsingModule):

    source_name = 'SimpleTalkRssFeed'
    projects = (
        os_friday_project,
    )
    rss_url = 'http://www.simple-talk.com/feed/'
    language = Language.ENGLISH
    filtration_needed = True
    filters = (
        FiltrationType.SPECIFIC,
    )


class SmashingMagazineFeedParsingModule(SimpleRssBasicParsingModule):

    source_name = 'SmashingMagazineFeed'
    projects = (
        os_friday_project,
    )
    rss_url = 'http://rss1.smashingmagazine.com/feed/'
    language = Language.ENGLISH
    filtration_needed = True
    filters = (
        FiltrationType.SPECIFIC,
    )


class SteveSmithSBlogParsingModule(SimpleRssBasicParsingModule):

    source_name = 'SteveSmithSBlog'
    projects = (
        os_friday_project,
    )
    rss_url = 'http://feeds.feedburner.com/StevenSmith'
    language = Language.ENGLISH
    filtration_needed = True
    filters = (
        FiltrationType.SPECIFIC,
    )


class TechgenixNewsParsingModule(SimpleRssBasicParsingModule):

    source_name = 'TechgenixNews'
    projects = (
        os_friday_project,
    )
    rss_url = 'https://techgenix.com/feed/'
    language = Language.ENGLISH
    filtration_needed = True
    filters = (
        FiltrationType.SPECIFIC,
    )


class TecosystemsParsingModule(SimpleRssBasicParsingModule):

    source_name = 'Tecosystems'
    projects = (
        os_friday_project,
    )
    rss_url = 'http://redmonk.com/sogrady/feed/rss/'
    language = Language.ENGLISH
    filtration_needed = True
    filters = (
        FiltrationType.SPECIFIC,
    )


class TheArtOfSimplicityParsingModule(SimpleRssBasicParsingModule):

    source_name = 'TheArtOfSimplicity'
    projects = (
        os_friday_project,
    )
    rss_url = 'http://bartwullems.blogspot.com/feeds/posts/default'
    language = Language.ENGLISH
    filtration_needed = True
    filters = (
        FiltrationType.SPECIFIC,
    )
    item_tag_name = 'entry'
    pubdate_tag_name = 'published'
    description_tag_name = 'content'

    def rss_items_root(self):
        return self.rss_data_root


class TheExptaBlogParsingModule(SimpleRssBasicParsingModule):

    source_name = 'TheExptaBlog'
    projects = (
        os_friday_project,
    )
    rss_url = 'http://www.expta.com/feeds/posts/default'
    language = Language.ENGLISH
    filtration_needed = True
    filters = (
        FiltrationType.SPECIFIC,
    )


class TheMicrosoftPlatformParsingModule(SimpleRssBasicParsingModule):

    source_name = 'TheMicrosoftPlatform'
    projects = (
        os_friday_project,
    )
    rss_url = 'http://microsoftplatform.blogspot.com/feeds/posts/default'
    language = Language.ENGLISH
    filtration_needed = True
    filters = (
        FiltrationType.SPECIFIC,
    )
    item_tag_name = 'entry'
    pubdate_tag_name = 'published'
    description_tag_name = 'content'

    def rss_items_root(self):
        return self.rss_data_root


class ThinkingInSoftwareParsingModule(SimpleRssBasicParsingModule):

    source_name = 'ThinkingInSoftware'
    projects = (
        os_friday_project,
    )
    rss_url = 'http://thinkinginsoftware.blogspot.com/feeds/posts/default'
    language = Language.ENGLISH
    filtration_needed = True
    filters = (
        FiltrationType.SPECIFIC,
    )
    item_tag_name = 'entry'
    pubdate_tag_name = 'published'
    description_tag_name = 'content'

    def rss_items_root(self):
        return self.rss_data_root


class VirtualisationManagementBlogParsingModule(SimpleRssBasicParsingModule):

    source_name = 'VirtualisationManagementBlog'
    projects = (
        os_friday_project,
    )
    rss_url = 'http://virtualisationandmanagement.wordpress.com/feed/'
    language = Language.ENGLISH
    filtration_needed = True
    filters = (
        FiltrationType.SPECIFIC,
    )


class VisioGuyParsingModule(SimpleRssBasicParsingModule):

    source_name = 'VisioGuy'
    projects = (
        os_friday_project,
    )
    rss_url = 'http://www.visguy.com/feed/'
    language = Language.ENGLISH
    filtration_needed = True
    filters = (
        FiltrationType.SPECIFIC,
    )


class WebcastsParsingModule(SimpleRssBasicParsingModule):

    source_name = 'Webcasts'
    projects = (
        os_friday_project,
    )
    rss_url = 'http://redmondmag.com/rss-feeds/webcasts.aspx'
    language = Language.ENGLISH
    filtration_needed = True
    filters = (
        FiltrationType.SPECIFIC,
    )


class WindowsPowershellBlogParsingModule(SimpleRssBasicParsingModule):

    source_name = 'WindowsPowershellBlog'
    projects = (
        os_friday_project,
    )
    rss_url = 'http://blogs.msdn.com/b/powershell/atom.aspx'
    language = Language.ENGLISH


class WindowsServerDivisionWeblogParsingModule(SimpleRssBasicParsingModule):

    source_name = 'WindowsServerDivisionWeblog'
    projects = (
        os_friday_project,
    )
    rss_url = 'http://blogs.technet.com/b/windowsserver/rss.aspx'
    language = Language.ENGLISH
    filtration_needed = True
    filters = (
        FiltrationType.SPECIFIC,
    )


class YouAreNotSoSmartParsingModule(SimpleRssBasicParsingModule):

    source_name = 'YouAreNotSoSmart'
    projects = (
        os_friday_project,
    )
    rss_url = 'http://youarenotsosmart.com/feed/'
    language = Language.ENGLISH
    filtration_needed = True
    filters = (
        FiltrationType.SPECIFIC,
    )


class YouVeBeenHaackedParsingModule(SimpleRssBasicParsingModule):

    source_name = 'YouVeBeenHaacked'
    projects = (
        os_friday_project,
    )
    rss_url = 'http://feeds.haacked.com/haacked'
    language = Language.ENGLISH
    filtration_needed = True
    filters = (
        FiltrationType.SPECIFIC,
    )
    item_tag_name = 'entry'
    pubdate_tag_name = 'published'
    description_tag_name = 'content'

    def rss_items_root(self):
        return self.rss_data_root


class AlexanderBindyuBlogParsingModule(SimpleRssBasicParsingModule):

    source_name = 'AlexanderBindyuBlog'
    projects = (
        os_friday_project,
    )
    rss_url = 'http://blog.byndyu.ru/feeds/posts/default?alt=rss'
    language = Language.RUSSIAN
    filtration_needed = True
    filters = (
        FiltrationType.SPECIFIC,
    )

    def _preprocess_date_str(self, date_str: str):
        return super()._preprocess_date_str(date_str.replace('PST', 'UTC-08'))


class ScottHanselmanSBlogParsingModule(SimpleRssBasicParsingModule):

    source_name = 'ScottHanselmanSBlog'
    projects = (
        os_friday_project,
    )
    rss_url = 'http://feeds.hanselman.com/ScottHanselman'
    language = Language.ENGLISH
    filtration_needed = True
    filters = (
        FiltrationType.SPECIFIC,
    )


class AndreyOnNetParsingModule(SimpleRssBasicParsingModule):

    source_name = 'AndreyOnNet'
    projects = (
        os_friday_project,
    )
    rss_url = 'http://feeds.moveax.ru/devdotnet'
    language = Language.RUSSIAN
    filtration_needed = True
    filters = (
        FiltrationType.SPECIFIC,
    )


class MyInformationResourceBlogMirNetParsingModule(SimpleRssBasicParsingModule):

    source_name = 'MyInformationResourceBlogMirNet'
    projects = (
        os_friday_project,
    )
    rss_url = 'http://blog.mir.net/feeds/posts/default'
    language = Language.ENGLISH
    filtration_needed = True
    filters = (
        FiltrationType.SPECIFIC,
    )
    item_tag_name = 'entry'
    pubdate_tag_name = 'published'
    description_tag_name = 'content'

    def rss_items_root(self):
        return self.rss_data_root


class EternalArrivalParsingModule(SimpleRssBasicParsingModule):

    source_name = 'EternalArrival'
    projects = (
        os_friday_project,
    )
    rss_url = 'https://eternalarrival.com/feed/'
    language = Language.ENGLISH
    filtration_needed = True
    filters = (
        FiltrationType.SPECIFIC,
    )


class Rss20TaggedMerkleTreesAndRelatedSimilarDataStructuresNotBusinessScamNewsParsingModule(SimpleRssBasicParsingModule):

    source_name = 'Rss20TaggedMerkleTreesAndRelatedSimilarDataStructuresNotBusinessScamNews'
    projects = (
        os_friday_project,
    )
    rss_url = 'https://lobste.rs/t/merkle-trees.rss'
    language = Language.ENGLISH
    filtration_needed = True
    filters = (
        FiltrationType.SPECIFIC,
    )


class WeeklyOsmParsingModule(SimpleRssBasicParsingModule):

    source_name = 'WeeklyOsm'
    projects = (
        foss_news_project,
    )
    rss_url = 'https://weeklyosm.eu/ru/feed'
    language = Language.RUSSIAN
    filtration_needed = False
