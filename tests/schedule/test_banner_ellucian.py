from __future__ import annotations

from src.schedule.banner_ellucian import BannerEllucianProvider
from src.schedule.models import CollegeScheduleSource

_BANNER_SOURCE = CollegeScheduleSource(
    cc_id=2,
    cc_name="Evergreen Valley College",
    system="banner",
    base_url="https://colss-prod.ec.sjeccd.edu/Student/Courses/SearchResult",
    locations=("EVC",),
)

_NON_BANNER_SOURCE = CollegeScheduleSource(
    cc_id=4,
    cc_name="College of Marin",
    system="marin_colleague",
    base_url="https://netapps.marin.edu/Apps/Directory/ScheduleSearch.aspx",
    locations=("0000",),
)


def test_supports_banner_source():
    provider = BannerEllucianProvider()
    assert provider.supports_source(_BANNER_SOURCE)


def test_rejects_non_banner_source():
    provider = BannerEllucianProvider()
    assert not provider.supports_source(_NON_BANNER_SOURCE)
