import json
from pathlib import Path
from cerberus import Validator
import idealista
import pytest
import pprint
import os
from scrapfly import ScrapeConfig, ScrapflyClient

SCRAPFLY = ScrapflyClient(key=os.environ["SCRAPFLY_KEY"])

BASE_CONFIG = {
    # bypass web scraping blocking
    "asp": True,
    # set the proxy country to Spain
    "country": "ES",
    "cache": True
}
pp = pprint.PrettyPrinter(indent=4)


class Validator(Validator):
    def _validate_min_presence(self, min_presence, field, value):
        pass  # required for adding non-standard keys to schema


def require_min_presence(items, key, min_perc=0.1):
    """check whether dataset contains items with some amount of non-null values for a given key"""
    count = sum(1 for item in items if item.get(key))
    if count < len(items) * min_perc:
        pytest.fail(
            f'inadequate presence of "{key}" field in dataset, only {count} out of {len(items)} items have it (expected {min_perc*100}%)'
        )


def validate_or_fail(item, validator):
    if not validator.validate(item):
        pp.pformat(item)
        pytest.fail(f"Validation failed for item: {pp.pformat(item)}\nErrors: {validator.errors}")


property_schema = {
    "schema": {
        "type": "dict",
        "schema": {
            "url": {"type": "string"},
            "title": {"type": "string"},
            "location": {"type": "string"},
            "currency": {"type": "string"},
            "price": {"type": "integer"},
            "description": {"type": "string"},
            "updated": {"type": "string"},
            "features": {
                "type": "dict",
                "schema": {
                    "Basic features": {"type": "list", "schema": {"type": "string"}},
                    "Amenities": {"type": "list", "schema": {"type": "string"}},
                    "Energy performance certificate": {
                        "type": "list",
                        "schema": {"type": "string"},
                    },
                },
            },
            "images": {
                "type": "dict",
                "schema": {
                    "Living room": {"type": "list", "schema": {"type": "string"}},
                    "Kitchen": {"type": "list", "schema": {"type": "string"}},
                    "Bathroom": {"type": "list", "schema": {"type": "string"}},
                    "Bedroom": {"type": "list", "schema": {"type": "string"}},
                },
            },
            "plans": {"type": "list", "schema": {"type": "string"}},
        },
    }
}

search_schema = {
    "title": {"type": "string"},
    "link": {"type": "string"},
    "picture": {"type": "string"},
    "price": {"type": "integer"},
    "currency": {"type": "string"},
    "parking_included": {"type": "boolean"},
    "details": {"type": "list", "schema": {"type": "string"}},
    "description": {"type": "string"},
    "tags": {"type": "list", "schema": {"type": "string"}},
    "listing_company": {"type": "string", "nullable": True},
    "listing_company_url": {"type": "string", "nullable": True}
}


@pytest.mark.asyncio
@pytest.mark.flaky(reruns=3, reruns_delay=30)
async def test_idealista_scraping():
    first_page = await SCRAPFLY.async_scrape(
        ScrapeConfig(
            url="https://www.idealista.com/en/venta-viviendas/marbella-malaga/con-chalets/",
            asp=True,
            country="ES",
        )
    )
    property_urls = idealista.parse_search(first_page)
    to_scrape = [
        ScrapeConfig(first_page.context["url"] + f"pagina-{page}.htm", asp=True, country="ES") for page in range(2, 3)
    ]
    async for response in SCRAPFLY.concurrent_scrape(to_scrape):
        property_urls.extend(idealista.parse_search(response))
    result = await idealista.scrape_properties(urls=property_urls[:3])
    validator = Validator(property_schema, allow_unknown=True)
    for item in result:
        validate_or_fail(item, validator)
    assert len(result) >= 2
    assert len(property_urls) >= 30
    if os.getenv("SAVE_TEST_RESULTS") == "true":
        result.sort(key=lambda x: x["url"])
        (Path(__file__).parent / 'results/properties.json').write_text(
            json.dumps(result, indent=2, ensure_ascii=False, default=str)
        )


@pytest.mark.asyncio
@pytest.mark.flaky(reruns=3, reruns_delay=30)
async def test_provinces_scraping():
    result = await idealista.scrape_provinces(
        urls=["https://www.idealista.com/venta-viviendas/almeria-provincia/municipios"]
    )
    assert len(result) >= 2
    if os.getenv("SAVE_TEST_RESULTS") == "true":
        result.sort()
        (Path(__file__).parent / 'results/search_URLs.json').write_text(
            json.dumps(result, indent=2, ensure_ascii=False, default=str)
        )


@pytest.mark.asyncio
@pytest.mark.flaky(reruns=3, reruns_delay=30)
async def test_search_scraping():
    result = await idealista.scrape_search(
        url="https://www.idealista.com/en/venta-viviendas/marbella-malaga/con-chalets/",
        # remove the max_scrape_pages paremeter to scrape all pages
        max_scrape_pages=3,
    )
    validator = Validator(search_schema, allow_unknown=True)
    for item in result:
        validate_or_fail(item, validator)
    for k in search_schema:
        require_min_presence(result, k, min_perc=search_schema[k].get("min_presence", 0.1))
    assert len(result) > 60
    if os.getenv("SAVE_TEST_RESULTS") == "true":
        result.sort(key=lambda x: x["link"])
        (Path(__file__).parent / 'results/search_data.json').write_text(
            json.dumps(result, indent=2, ensure_ascii=False, default=str)
        )
