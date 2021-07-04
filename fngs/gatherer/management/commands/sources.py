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

from gatherer.models import *
from .logger import logger
from .keywords import keywords


foss_news_project = Project.objects.get(name='FOSS News')


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
                 projects: Tuple[Project],
                 url: str,
                 brief: str):
        self.dt = dt
        self.title = title
        self.projects = projects
        self.url = url
        self.brief = brief
        self.keywords = []

    def __str__(self):
        return f'{self.dt} -- {self.url} -- {self.title} -- {shorten_text(self.brief)}'


class PostsData:

    def __init__(self,
                 source_name: str,
                 posts_data_list: List[PostData],
                 warning: str = None):
        self.source_name = source_name
        self.posts_data_list = posts_data_list
        self.warning = warning


class FiltrationType(Enum):
    GENERIC = 'generic'
    SPECIFIC = 'specific'


class BasicParsingModule(metaclass=ABCMeta):

    source_name = None
    projects: Tuple[Project] = ()
    warning = None
    filtration_needed = False
    filters = []

    def parse(self, days_count: int) -> List[PostData]:
        try:
            posts_data: List[PostData] = self._parse()
            for pd in posts_data:
                pd.projects = self.projects
        except Exception as e:
            logger.error(f'Failed to parse "{self.source_name}" source: {str(e)}')
            logger.error(traceback.format_exc())
            return []
        try:
            filtered_posts_data: List[PostData] = self._filter_out(posts_data, days_count)
            self._fill_keywords(filtered_posts_data)
            return filtered_posts_data
        except Exception as e:
            logger.error(f'Failed to filter data parsed from "{self.source_name}" source: {str(e)}')
            logger.error(traceback.format_exc())
            return []

    @abstractmethod
    def _parse(self) -> List[PostData]:
        pass

    def _fill_keywords(self, posts_data: List[PostData]):
        keywords_to_check = []
        keywords_to_check += keywords['generic']
        keywords_to_check += keywords['specific']
        for post_data in posts_data:
            for keyword in keywords_to_check:
                if keyword in post_data.keywords:
                    continue
                if self._find_keyword_in_title(keyword, post_data.title):
                    post_data.keywords.append(keyword)

    def _find_keyword_in_title(self, keyword, title):
        return re.search(rf'\b{re.escape(keyword)}\b', title, re.IGNORECASE)

    def _filter_out(self, posts_data: List[PostData], days_count: int):
        filtered_posts_data: List[PostData] = posts_data
        filtered_posts_data = self._filter_out_old(filtered_posts_data, days_count)
        filtered_posts_data = self._filter_out_by_keywords(filtered_posts_data)
        return filtered_posts_data

    def _filter_out_by_keywords(self, posts_data: List[PostData]):
        if not self.filtration_needed:
            return posts_data
        filtered_posts_data: List[PostData] = []
        keywords_to_check = []
        if FiltrationType.GENERIC in self.filters:
            keywords_to_check += keywords['generic']
        if FiltrationType.SPECIFIC in self.filters:
            keywords_to_check += keywords['specific']
        for post_data in posts_data:
            matched = False
            for keyword in keywords_to_check:
                if self._find_keyword_in_title(keyword, post_data.title):
                    matched = True
                    break
            if matched:
                logger.debug(f'"{post_data.title}" from "{self.source_name}" added because it contains keywords {post_data.keywords}')
                filtered_posts_data.append(post_data)
            else:
                logger.warning(f'"{post_data.title}" ({post_data.url}) from "{self.source_name}" filtered out cause not contains none of expected keywords')
        return filtered_posts_data

    def _filter_out_old(self, posts_data: List[PostData], days_count: int) -> List[PostData]:
        filtered_posts_data: List[PostData] = []
        dt_now = datetime.datetime.now(tz=dateutil.tz.tzlocal())
        for post_data in posts_data:
            if post_data.dt is not None and (dt_now - post_data.dt).days > days_count:
                logger.debug(f'"{post_data.title}" from "{self.source_name}" filtered as too old ({post_data.dt})')
            else:
                filtered_posts_data.append(post_data)
        return filtered_posts_data


class RssBasicParsingModule(BasicParsingModule):

    rss_url = None
    item_tag_name = None
    title_tag_name = None
    pubdate_tag_name = None
    link_tag_name = None
    description_tag_name = None

    def __init__(self):
        self.rss_data_root = None

    def _parse(self):
        posts_data: List[PostData] = []
        response = requests.get(self.rss_url)
        if response.status_code != 200:
            logger.error(f'"{self.source_name}" returned status code {response.status_code}')
            return posts_data
        self.rss_data_root = ET.fromstring(response.text)
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
                        title = text.strip()
                    elif self.pubdate_tag_name in tag:
                        dt = dateutil.parser.parse(self._date_from_russian_to_english(text))
                    elif self.link_tag_name in tag:
                        if text:
                            url = text
                        elif 'href' in rss_data_subelem.attrib:
                            url = rss_data_subelem.attrib['href']
                        else:
                            logger.error(f'Could not find URL for "{title}" feed record')
                    elif self.description_tag_name in tag:
                        brief = text
                post_data = PostData(dt, title, self.projects, self.process_url(url), brief)
                posts_data.append(post_data)
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


class LinuxComParsingModule(SimpleRssBasicParsingModule):

    source_name = "LinuxCom"
    projects = (
        foss_news_project,
    )
    rss_url = 'https://www.linux.com/topic/feed/'


class OpenSourceComParsingModule(SimpleRssBasicParsingModule):
    # NOTE: Provider provides RSS feed for less than week, more regular check is needed

    source_name = 'OpenSourceCom'
    projects = (
        foss_news_project,
    )
    rss_url = 'https://opensource.com/feed'


class ItsFossComParsingModule(SimpleRssBasicParsingModule):

    source_name = 'ItsFossCom'
    projects = (
        foss_news_project,
    )
    rss_url = 'https://itsfoss.com/all-blog-posts/feed/'


class LinuxOrgRuParsingModule(SimpleRssBasicParsingModule):

    source_name = 'LinuxOrgRu'
    projects = (
        foss_news_project,
    )
    rss_url = 'https://www.linux.org.ru/section-rss.jsp?section=1'


class AnalyticsIndiaMagComParsingModule(SimpleRssBasicParsingModule):

    source_name = 'AnalyticsIndiaMagCom'
    projects = (
        foss_news_project,
    )
    rss_url = 'https://analyticsindiamag.com/feed/'
    filtration_needed = True
    filters = [
        FiltrationType.SPECIFIC,
        FiltrationType.GENERIC,
    ]


class ArsTechnicaComParsingModule(SimpleRssBasicParsingModule):

    source_name = 'ArsTechnicaCom'
    projects = (
        foss_news_project,
    )
    rss_url = 'https://arstechnica.com/feed/'
    filtration_needed = True
    filters = [
        FiltrationType.SPECIFIC,
    ]


class HackadayComParsingModule(SimpleRssBasicParsingModule):

    source_name = 'HackadayCom'
    projects = (
        foss_news_project,
    )
    rss_url = 'https://hackaday.com/feed/'
    filtration_needed = True
    filters = [
        FiltrationType.SPECIFIC,
    ]


class JaxenterComParsingModule(SimpleRssBasicParsingModule):

    source_name = 'JaxenterCom'
    projects = (
        foss_news_project,
    )
    rss_url = 'https://jaxenter.com/rss'
    filtration_needed = True
    filters = [
        FiltrationType.SPECIFIC,
    ]


class LinuxInsiderComParsingModule(SimpleRssBasicParsingModule):

    source_name = 'LinuxInsiderCom'
    projects = (
        foss_news_project,
    )
    rss_url = 'https://linuxinsider.com/rss-feed'


class MashableComParsingModule(SimpleRssBasicParsingModule):

    source_name = 'MashableCom'
    projects = (
        foss_news_project,
    )
    rss_url = 'https://mashable.com/rss/'
    filtration_needed = True
    filters = [
        FiltrationType.SPECIFIC,
    ]


class SdTimesComParsingModule(SimpleRssBasicParsingModule):

    source_name = 'SdTimesCom'
    projects = (
        foss_news_project,
    )
    rss_url = 'https://sdtimes.com/feed/'
    filtration_needed = True
    filters = [
        FiltrationType.SPECIFIC,
    ]


class SecurityBoulevardComParsingModule(SimpleRssBasicParsingModule):

    source_name = 'SecurityBoulevardCom'
    projects = (
        foss_news_project,
    )
    rss_url = 'https://securityboulevard.com/feed/'
    filtration_needed = True
    filters = [
        FiltrationType.SPECIFIC,
    ]


class SiliconAngleComParsingModule(SimpleRssBasicParsingModule):

    source_name = 'SiliconAngleCom'
    projects = (
        foss_news_project,
    )
    rss_url = 'https://siliconangle.com/feed/'
    filtration_needed = True
    filters = [
        FiltrationType.SPECIFIC,
    ]


class TechCrunchComParsingModule(SimpleRssBasicParsingModule):

    source_name = 'TechCrunchCom'
    projects = (
        foss_news_project,
    )
    rss_url = 'https://techcrunch.com/feed/'
    filtration_needed = True
    filters = [
        FiltrationType.SPECIFIC,
    ]


class TechNodeComParsingModule(SimpleRssBasicParsingModule):

    source_name = 'TechNodeCom'
    projects = (
        foss_news_project,
    )
    rss_url = 'https://technode.com/feed/'
    filtration_needed = True
    filters = [
        FiltrationType.SPECIFIC,
    ]


class TheNextWebComParsingModule(SimpleRssBasicParsingModule):

    source_name = 'TheNextWebCom'
    projects = (
        foss_news_project,
    )
    rss_url = 'https://thenextweb.com/feed/'
    filtration_needed = True
    filters = [
        FiltrationType.SPECIFIC,
    ]


class VentureBeatComParsingModule(SimpleRssBasicParsingModule):

    source_name = 'VentureBeatCom'
    projects = (
        foss_news_project,
    )
    rss_url = 'https://venturebeat.com/feed/'
    filtration_needed = True
    filters = [
        FiltrationType.SPECIFIC,
    ]


class ThreeDPrintingMediaNetworkParsingModule(SimpleRssBasicParsingModule):

    source_name = 'ThreeDPrintingMediaNetwork'
    projects = (
        foss_news_project,
    )
    rss_url = 'https://www.3dprintingmedia.network/feed/'
    filtration_needed = True
    filters = [
        FiltrationType.SPECIFIC,
    ]


class CbrOnlineComParsingModule(SimpleRssBasicParsingModule):

    source_name = 'CbrOnlineCom'
    projects = (
        foss_news_project,
    )
    rss_url = 'https://www.cbronline.com/rss'
    filtration_needed = True
    filters = [
        FiltrationType.SPECIFIC,
    ]


class HelpNetSecurityComParsingModule(SimpleRssBasicParsingModule):

    source_name = 'HelpNetSecurityCom'
    projects = (
        foss_news_project,
    )
    rss_url = 'https://www.helpnetsecurity.com/feed/'
    filtration_needed = True
    filters = [
        FiltrationType.SPECIFIC,
    ]


class SecuritySalesComParsingModule(SimpleRssBasicParsingModule):

    source_name = 'SecuritySalesCom'
    projects = (
        foss_news_project,
    )
    rss_url = 'https://www.securitysales.com/feed/'
    filtration_needed = True
    filters = [
        FiltrationType.SPECIFIC,
    ]


class TechRadarComParsingModule(SimpleRssBasicParsingModule):

    source_name = 'TechRadarCom'
    projects = (
        foss_news_project,
    )
    rss_url = 'https://www.techradar.com/rss'
    filtration_needed = True
    filters = [
        FiltrationType.SPECIFIC,
    ]


class TfirIoParsingModule(SimpleRssBasicParsingModule):

    source_name = 'TfirIo'
    projects = (
        foss_news_project,
    )
    rss_url = 'https://www.tfir.io/feed/'
    filtration_needed = True
    filters = [
        FiltrationType.SPECIFIC,
    ]


class ZdNetComLinuxParsingModule(SimpleRssBasicParsingModule):
    # TODO: Think about parsing other sections
    source_name = 'ZdNetComLinux'
    projects = (
        foss_news_project,
    )
    rss_url = 'https://www.zdnet.com/topic/linux/rss.xml'


class LinuxFoundationOrgParsingModule(SimpleRssBasicParsingModule):

    source_name = 'LinuxFoundationOrg'
    projects = (
        foss_news_project,
    )
    rss_url = 'https://linuxfoundation.org/rss'


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
    filters = [
        FiltrationType.SPECIFIC,
    ]

    @property
    def rss_url(self):
        return f'https://habr.com/ru/rss/news/'


class HabrComOpenSourceParsingModule(HabrComBasicParsingModule):

    source_name = f'HabrComOpenSource'
    projects = (
        foss_news_project,
    )
    hub_code = 'open_source'


class HabrComLinuxParsingModule(HabrComBasicParsingModule):

    source_name = f'HabrComLinux'
    projects = (
        foss_news_project,
    )
    hub_code = 'linux'


class HabrComLinuxDevParsingModule(HabrComBasicParsingModule):

    source_name = f'HabrComLinuxDev'
    projects = (
        foss_news_project,
    )
    hub_code = 'linux_dev'


class HabrComNixParsingModule(HabrComBasicParsingModule):

    source_name = f'HabrComNix'
    projects = (
        foss_news_project,
    )
    hub_code = 'nix'


class HabrComDevOpsParsingModule(HabrComBasicParsingModule):

    source_name = f'HabrComDevOps'
    projects = (
        foss_news_project,
    )
    hub_code = 'devops'


class HabrComSysAdmParsingModule(HabrComBasicParsingModule):

    source_name = f'HabrComSysAdm'
    projects = (
        foss_news_project,
    )
    hub_code = 'sys_admin'


class HabrComGitParsingModule(HabrComBasicParsingModule):

    source_name = f'HabrComGit'
    projects = (
        foss_news_project,
    )
    hub_code = 'git'


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


class YouTubeComAlekseySamoilovParsingModule(YouTubeComBasicParsingModule):

    source_name = f'YouTubeComAlekseySamoilov'
    projects = (
        foss_news_project,
    )
    channel_id = 'UC3kAbMcYr-JEMSb2xX4OdpA'


class LosstRuParsingModule(SimpleRssBasicParsingModule):

    source_name = 'LosstRu'
    projects = (
        foss_news_project,
    )
    rss_url = 'https://losst.ru/rss'


class AstraLinuxRuParsingModule(SimpleRssBasicParsingModule):

    source_name = 'AstraLinuxRu'
    projects = (
        foss_news_project,
    )
    rss_url = 'https://astralinux.ru/rss'


class BaseAltRuParsingModule(SimpleRssBasicParsingModule):

    source_name = 'BaseAltRu'
    projects = (
        foss_news_project,
    )
    rss_url = 'https://www.basealt.ru/feed.rss'


class PingvinusRuParsingModule(BasicParsingModule):

    source_name = 'PingvinusRu'
    projects = (
        foss_news_project,
    )
    site_url = 'https://pingvinus.ru'

    def __init__(self):
        super().__init__()
        self.news_page_url = f'{self.site_url}/news'

    def _parse(self):
        response = requests.get(self.news_page_url)
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
            post_data = PostData(dt, title, self.projects, url, None)
            posts.append(post_data)
        return posts
