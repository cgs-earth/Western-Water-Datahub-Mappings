# Copyright 2025 Lincoln Institute of Land Policy
# SPDX-License-Identifier: MIT

from copy import deepcopy
from datetime import datetime
import logging
from typing import Literal, Optional, assert_never
import geojson_pydantic
from pydantic import BaseModel, field_validator
import shapely
import shapely.wkt
from rise.lib.helpers import (
    merge_pages,
    parse_bbox,
    parse_date,
    parse_z,
)
from rise.lib.types.helpers import ZType
from rise.lib.types.includes import LocationIncluded
from rise.lib.types.location import LocationData, PageLinks
from geojson_pydantic import Feature, FeatureCollection

LOGGER = logging.getLogger()


class LocationResponse(BaseModel):
    """
    This class represents the top level location/ response that is returned from the API
    It is validated with pydantic on initialization and multiple methods are added to it to make it easier to manipulate data
    """

    # links and pagination may not be present if there is only one location
    links: Optional[PageLinks] = None
    meta: Optional[
        dict[
            Literal["totalItems", "itemsPerPage", "currentPage"],
            int,
        ]
    ] = None
    # data represents the list of locations returned
    data: list[LocationData]

    @classmethod
    def from_api_pages(cls, pages: dict[str, dict]):
        """Create a location response from multiple paged API responses by first merging them together"""
        return cls(**merge_pages(pages))

    @field_validator("data", check_fields=True, mode="before")
    @classmethod
    def ensure_list(cls, data: LocationData | list[LocationData]) -> list[LocationData]:
        """
        Data can be a list of dicts or just a dict if there is only one location;
        make sure it is always a list for consistency
        """
        if not isinstance(data, list):
            return [data]
        return data

    def drop_outside_of_date_range(self, datetime_: str):
        """
        Filter a list of locations by date
        """
        if not self.data[0].attributes:
            raise RuntimeError("Can't filter by date")

        filteredResp = self.copy(deep=True)

        parsed_date: list[datetime] = parse_date(datetime_)

        if len(parsed_date) == 2:
            start, end = parsed_date

            for i, location in enumerate(filteredResp.data):
                updateDate = datetime.fromisoformat(location.attributes.updateDate)
                if updateDate < start or updateDate > end:
                    filteredResp.data.pop(i)

        elif len(parsed_date) == 1:
            parsed_date_str = str(parsed_date[0])
            filteredResp.data = [
                location
                for location in filteredResp.data
                if location.attributes.updateDate.startswith(parsed_date_str)
            ]

        else:
            raise RuntimeError(
                "datetime_ must be a date or date range with two dates separated by '/' but got {}".format(
                    datetime_
                )
            )

        return filteredResp

    def _filter_by_geometry(
        self,
        geometry: Optional[shapely.geometry.base.BaseGeometry],
        # Vertical level
        z: Optional[str] = None,
    ):
        """
        Filter a list of locations by any arbitrary geometry; if they are not inside of it, drop their data
        """
        # need to deep copy so we don't change the dict object
        copy_to_return = deepcopy(self)
        indices_to_pop = set()
        parsed_z = parse_z(str(z)) if z else None

        for i, v in enumerate(self.data):
            elevation = v.attributes.elevation

            if elevation is None:
                indices_to_pop.add(i)
                continue

            if parsed_z:
                match parsed_z:
                    case [ZType.RANGE, x]:
                        if elevation < x[0] or elevation > x[1]:
                            indices_to_pop.add(i)
                    case [ZType.SINGLE, x]:
                        if elevation != x[0]:
                            indices_to_pop.add(i)
                    case [ZType.ENUMERATED_LIST, x]:
                        if elevation not in x:
                            indices_to_pop.add(i)
                    case _:
                        assert_never(parsed_z)

            if geometry:
                result_geo = shapely.geometry.shape(
                    # need to convert the pydantic model to a simple
                    # dict to use shapely with it
                    v.attributes.locationCoordinates.model_dump()
                )

                if not geometry.contains(result_geo):
                    indices_to_pop.add(i)

        # by reversing the list we pop from the end so the
        # indices will be in the correct even after removing items
        for i in sorted(indices_to_pop, reverse=True):
            copy_to_return.data.pop(i)

        return copy_to_return

    def drop_outside_of_wkt(
        self,
        wkt: Optional[str] = None,
        z: Optional[str] = None,
    ):
        """Filter a location by the well-known-text geometry representation"""
        parsed_geo = shapely.wkt.loads(str(wkt)) if wkt else None
        return self._filter_by_geometry(parsed_geo, z)

    def drop_specific_location(self, location_id: int):
        """Given a location id, drop all all data that is associated with that location"""
        new = self.model_copy()

        filtered_locations = [
            loc for loc in new.data if loc.attributes.id != location_id
        ]

        new.data = filtered_locations

        return new

    def drop_outside_of_bbox(
        self,
        bbox: Optional[list] = None,
        z: Optional[str] = None,
    ):
        """
        Given a bounding box filter out location data for locations that are not in the box.
        If the bbox is 4 items long it will just filter by x,y coords; if it is
        6 items long it will filter by x,y,z; If they supply a z value it will filter by z
        even if the bbox does not contain z
        """
        if bbox:
            parse_result = parse_bbox(bbox)
            shapely_box = parse_result[0] if parse_result else None
            z = parse_result[1] if parse_result else z

        shapely_box = parse_bbox(bbox)[0] if bbox else None
        # TODO what happens if they specify both a bbox with z and a z value?
        z = parse_bbox(bbox)[1] if bbox else z

        return self._filter_by_geometry(shapely_box, z)

    def drop_after_limit(self, limit: int):
        """
        Return only the location data for the locations in the list up to the limit
        """
        self.data = self.data[:limit]
        return self

    def drop_before_offset(self, offset: int):
        """
        Return only the location data for the locations in the list after the offset
        """
        self.data = self.data[offset:]
        return self

    def drop_all_but_id(
        self,
        identifier: Optional[str] = None,
    ):
        """
        Return only the location data for the location with the given identifier
        """
        self.data = [
            location
            for location in self.data
            if str(location.attributes.id) == identifier
        ]
        return self

    def to_geojson(self) -> dict:
        """
        Convert a list of locations to geojson
        """
        geojson_features: list[geojson_pydantic.Feature] = []

        single_feature = len(self.data) == 1

        for location_feature in self.data:
            feature_as_geojson = {
                "type": "Feature",
                "id": location_feature.attributes.id,
                # dump with alias to preserve any aliased properties
                "properties": location_feature.attributes.model_dump(
                    by_alias=True, exclude={"locationCoordinates", "locationGeometry"}
                ),
                "geometry": location_feature.attributes.locationCoordinates.model_dump(),
            }
            feature_as_geojson["properties"]["name"] = (
                location_feature.attributes.locationName
            )

            z = location_feature.attributes.elevation
            if z is not None:
                feature_as_geojson["properties"]["elevation"] = z

            geojson_features.append(Feature(**feature_as_geojson))
            if single_feature:
                return feature_as_geojson

        validated_geojson = FeatureCollection(
            type="FeatureCollection", features=geojson_features
        )
        return validated_geojson.model_dump(by_alias=True)


class LocationResponseWithIncluded(LocationResponse):
    """
    This class represents the model of the data returned by location/ in RISE, specifically called
    with the query param, "include" This will make it so we have access to an extra "included:" key
    with links to catalogitems/catalogrecords
    """

    # included represents the additional data that is explicitly requested in the fetch request
    included: list[LocationIncluded]

    def get_catalogItemURLs(self) -> dict[str, list[str]]:
        """Get all catalog items associated with a particular location"""
        locationIdToCatalogRecord: dict[str, str] = {}

        # it is possible for the `included` section of the response to have both a catalogitem, as well as
        # a catalogrecord which has the same associated catalogitem. However, it is also possible to only
        # have the catalog item. In this case, we need to keep a set so we don't add the catalogItem twice
        # for the same location
        foundCatalogItems = set()

        catalogRecordToCatalogItems: dict[str, list[str]] = {}

        # iterate through the `included` section and associate the catalogrecords with the catalogitem
        for included_item in self.included:
            # if the included item is a catalog record
            # iterate through all its associated catalogitems
            if included_item.type == "CatalogRecord":
                catalogRecord = included_item.id
                locationId = included_item.relationships.location
                assert locationId is not None
                locationId = locationId.data[0].id
                locationIdToCatalogRecord[locationId] = catalogRecord

                # if the catalogrecord doesn't have associated catalogitems, skip it
                if not included_item.relationships.catalogItems:
                    continue

                for catalogItem in included_item.relationships.catalogItems.data:
                    if catalogItem.id in foundCatalogItems:
                        continue

                    if catalogRecord not in catalogRecordToCatalogItems:
                        catalogRecordToCatalogItems[catalogRecord] = []
                    catalogRecordToCatalogItems[catalogRecord].append(catalogItem.id)
                    foundCatalogItems.add(catalogItem.id)

            # if it is a catalogitem, just get the catalogitem url directly
            elif included_item.type == "CatalogItem":
                catalogItem = included_item.id
                if catalogItem in foundCatalogItems:
                    continue

                catalogRecord = included_item.relationships.catalogRecord
                assert catalogRecord is not None, (
                    "A catalogitem should be associated with a catalogrecord in the include section"
                )
                # we use the first index since there should only be one catalog record for each catalog item
                catalogRecord = catalogRecord.data[0].id
                if catalogRecord not in catalogRecordToCatalogItems:
                    catalogRecordToCatalogItems[catalogRecord] = []
                catalogRecordToCatalogItems[catalogRecord].append(catalogItem)
                foundCatalogItems.add(catalogItem)

        # once we have the mapping of catalogrecords to catalogitems, we then need
        # to iterate over locations and join the locationId -> catalogrecord and catalogrecord -> catalogitems
        # we have to do this second iteration since locations and catalogitems are in different sections of the json
        # and we do not have guarantees that they will follow a particular order
        locationIDToCatalogItemsUrls: dict[str, list[str]] = {}
        for locationId, catalogRecord in locationIdToCatalogRecord.items():
            if catalogRecord in catalogRecordToCatalogItems:
                for catalogItem in catalogRecordToCatalogItems[catalogRecord]:
                    catalogItemURL = f"https://data.usbr.gov{catalogItem}"
                    if locationId not in locationIDToCatalogItemsUrls:
                        locationIDToCatalogItemsUrls[str(locationId)] = [catalogItemURL]
                    else:
                        locationIDToCatalogItemsUrls[locationId].append(catalogItemURL)

        return locationIDToCatalogItemsUrls

    def drop_locations_without_catalogitems(self):
        """
        Filter out any locations which do not have catalogitems and thus do not have data
        """
        locationIdToCatalogItems = self.get_catalogItemURLs()
        data = []
        for location in self.data:
            if location.id not in locationIdToCatalogItems:
                continue
            data.append(location)

        self.data = data

        return self
