"""
This interfaces with MasterOverwatch to download stats.
"""
import functools

import asyncio
import json
import logging
import typing

from lxml import etree

from kyokai.context import HTTPRequestContext
import aiohttp

# Constants.
from owapi import util

B_BASE_URL = "https://playoverwatch.com/en-gb/"
B_PAGE_URL = B_BASE_URL + "career/pc/{region}/{btag}"

MO_BASE_URL = "https://masteroverwatch.com/"
MO_PROFILE_URL = MO_BASE_URL + "profile/pc/"
MO_PAGE_URL = MO_PROFILE_URL + "{region}/{btag}"
MO_UPDATE_URL = MO_PAGE_URL + "/update"

logger = logging.getLogger("OWAPI")

async def get_page_body(ctx: HTTPRequestContext, url: str, cache_time=300) -> str:
    """
    Downloads page body from MasterOverwatch and caches it.
    """
    session = aiohttp.ClientSession(headers={"User-Agent": "OWAPI Scraper/1.0.0"})

    async def _real_get_body(_, url: str):
        # Real function.
        logger.info("GET => {}".format(url))
        async with session.get(url) as req:
            assert isinstance(req, aiohttp.ClientResponse)
            if req.status != 200:
                return None
            return (await req.read()).decode()

    result = await util.with_cache(ctx, _real_get_body, url, expires=cache_time)
    session.close()
    return result


def _parse_page(content: str) -> etree._Element:
    """
    Internal function to parse a page and return the data.
    """
    data = etree.HTML(content)
    return data


async def get_user_page(ctx: HTTPRequestContext, battletag: str, region: str="eu", extra="",
                        cache_time=300) -> etree._Element:
    """
    Downloads the MO page for a user, and parses it.
    """
    built_url = MO_PAGE_URL.format(region=region, btag=battletag.replace("#", "-")) + "{}".format(extra)
    page_body = await get_page_body(ctx, built_url, cache_time=cache_time)

    # parse the page
    parse_partial = functools.partial(_parse_page, page_body)
    loop = asyncio.get_event_loop()
    parsed = await loop.run_in_executor(None, parse_partial)

    return parsed

async def get_blizzard_page(ctx: HTTPRequestContext, battletag: str, region: str="eu"):
    """
    Gets the blizzard page for the player,
    """
    # These pages should be cached infinitely as we don't use them for anything other than checking the status.
    built_url = B_PAGE_URL.format(region=region, btag=battletag.replace("#", "-"), cache_time=0)
    page_body = await get_page_body(ctx, built_url)

    if page_body is not None:
        parse_partial = functools.partial(_parse_page, page_body)
        loop = asyncio.get_event_loop()
        parsed = await loop.run_in_executor(None, parse_partial)

        return parsed
    return None

async def update_user(ctx, battletag, reg) -> bool:
    """
    Attempt to update a user on the MasterOverwatch side.
    """
    body = await get_page_body(ctx, MO_UPDATE_URL.format(btag=battletag, region=reg))
    data = json.loads(body)
    if data["status"] == "error":
        if data["message"] == "We couldn't find a player with that name.":
            return False

    logger.info("Updated user `{}` => `{}`".format(battletag, data))

    return True


async def region_helper(ctx: HTTPRequestContext, battletag: str, region=None, extra=""):
    """
    Downloads the correct page for a user in the right region.

    This will return either (etree._Element, region) or (None, None).
    """
    result = (None, None)
    if region is None:
        reg_l = ["eu", "us", "kr"]
    else:
        reg_l = [region]

    for reg in reg_l:
        # Force the blizzard page to download, if possible.
        # This allows MO to fetch the new data.
        blizz = await get_blizzard_page(ctx, battletag, reg)
        if blizz is None:
            # The blizzard page doesn't exist.
            # This means MO won't have the data.
            # Therefore, we can skip it.
            continue
        # Try and update the user.
        updated = await update_user(ctx, battletag, reg)
        if not updated:
            # Skip it, because it returned "User does not exist."
            # Therefore, the user page will return with an error.
            continue
        page = await get_user_page(ctx, battletag, reg, extra)
        # At this point, if we haven't gotten the double 404, we can continue.
        # Return the parsed page, and the region.
        return page, reg
    else:
        # Since we continued without returning, give back the None, None.
        return result