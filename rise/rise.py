# Copyright 2025 Lincoln Institute of Land Policy
# SPDX-License-Identifier: MIT

import logging
from typing import Optional


from pygeoapi.provider.base import BaseProvider, ProviderQueryError
from rise.lib.cache import RISECache
from rise.lib.location import LocationResponse
from rise.rise_edr import RiseEDRProvider
from rise.lib.helpers import merge_pages, safe_run_async

LOGGER = logging.getLogger(__name__)


class RiseProvider(BaseProvider):
    """Rise Provider for OGC API Features"""

    def __init__(self, provider_def):
        """
        Initialize object
        :param provider_def: provider definition
        """

        try:
            self.cache = RISECache(provider_def["cache"])
        except KeyError:
            raise Exception(
                "You must specify a cache implementation in the config.yml for RISE"
            )

        super().__init__(provider_def)

    def items(
        self,
        bbox: list = [],
        datetime_: Optional[str] = None,
        limit: Optional[int] = None,
        itemId: Optional[str] = None,
        offset: Optional[int] = 0,
        **kwargs,
    ):
        response: LocationResponse
        if itemId:
            # Instead of merging all location pages, just
            # fetch the location associated with the ID
            url: str = f"https://data.usbr.gov/rise/api/location/{itemId}"
            raw_resp = safe_run_async(self.cache.get_or_fetch(url))
            response = LocationResponse(**raw_resp)
        else:
            all_location_responses = self.cache.get_or_fetch_all_pages(
                RiseEDRProvider.LOCATION_API
            )
            merged_response = merge_pages(all_location_responses)
            response = LocationResponse(**merged_response)

        if datetime_:
            response = response.filter_by_date(datetime_)

        if offset:
            response = response.remove_before_offset(offset)

        if limit:
            response = response.filter_by_limit(limit)

        # Even though bbox is required, it can be an empty list. If it is empty just skip filtering
        if bbox:
            response = response.filter_by_bbox(bbox)

        return response.to_geojson(single_feature=itemId is not None)

    def query(self, **kwargs):
        return self.items(**kwargs)

    def get(self, identifier, **kwargs):
        """
        query CSV id

        :param identifier: feature id

        :returns: dict of single GeoJSON feature
        """
        return self.items(itemId=identifier, bbox=[], **kwargs)

    def get_fields(self, **kwargs):
        return self.cache.get_or_fetch_parameters()
