# Copyright 2025 Lincoln Institute of Land Policy
# SPDX-License-Identifier: MIT

import logging
from rise.lib.covjson.template import COVJSON_TEMPLATE
from rise.lib.covjson.types.covjson import (
    CoverageCollection,
    Coverage,
    CoverageRange,
    Parameter,
)
from rise.lib.cache import RISECache
from rise.lib.location_with_results import TransformedLocationWithResults

LOGGER = logging.getLogger(__name__)


def _generate_coverage_item(
    location_type: str,
    coords: list[float],
    times: list[str],
    paramToCoverage: dict[str, CoverageRange],
) -> Coverage:
    # if it is a point it will have different geometry

    if location_type == "Point":
        # z = location_feature["attributes"]["elevation"]
        x, y = coords[0], coords[1]

        coverage_item: Coverage = {
            "type": "Coverage",
            "domainType": "PointSeries",
            "domain": {
                "type": "Domain",
                "axes": {
                    "x": {"values": [x]},
                    "y": {"values": [y]},
                    "t": {"values": times},
                },
            },
            "ranges": paramToCoverage,
        }

    else:
        coverage_item: Coverage = {
            "type": "Coverage",
            "domainType": "PolygonSeries",
            "domain": {
                "type": "Domain",
                "axes": {
                    "composite": {
                        "dataType": location_type,
                        "coordinates": ["x", "y"],
                        "values": [
                            coords
                        ],
                    },
                    "t": {"values": times},
                },
            },
            "ranges": paramToCoverage,
        }

    return coverage_item


class CovJSONBuilder:
    """A helper class for building CovJSON from a Rise JSON Response"""

    def __init__(self, cache: RISECache):
        self._cache = cache


    def _get_parameter_metadata(self, location_response: list[TransformedLocationWithResults]):
        relevant_parameters = []
        for location in location_response:
            for p in location.parameters:
                relevant_parameters.append(p.catalogItemId)

        paramNameToMetadata: dict[str, Parameter] = {}

        paramsToGeoJsonOutput = self._cache.get_or_fetch_parameters()
        for param_id in paramsToGeoJsonOutput:
            if relevant_parameters and param_id not in relevant_parameters:
                continue

            associatedData = paramsToGeoJsonOutput[param_id]

            _param: Parameter = {
                "type": "Parameter",
                "description": {"en": associatedData["description"]},
                "unit": {"symbol": associatedData["x-ogc-unit"]},
                "observedProperty": {
                    "id": param_id,
                    "label": {"en": associatedData["title"]},
                },
            }
            natural_language_name = associatedData["title"]
            paramNameToMetadata[natural_language_name] = _param

        return paramNameToMetadata

    def _get_coverages(self, locationsWithResults: list[TransformedLocationWithResults]) -> list[Coverage]:
        """Return the data needed for the 'coverage' key in the covjson response"""

        coverages = []
        for location_feature in locationsWithResults:
            # CoverageJSON needs a us to associated every parameter with data
            # This data is grouped independently for each location
            paramToCoverage: dict[str, CoverageRange] = {}

            for param in location_feature.parameters:
                if not (  # ensure param contains data so it can be used for covjson
                    param.timeseriesResults
                ):
                    # Since coveragejson does not allow a parameter without results,
                    # we can skip adding the parameter/location combination all together
                    continue

                paramToCoverage[param.catalogItemId] = {
                    "axisNames": ["t"],
                    "dataType": "float",
                    "shape": [len(param.timeseriesResults)],
                    "values": param.timeseriesResults,
                    "type": "NdArray",
                }

                coverage_item = _generate_coverage_item(
                    "type", [0, 0], param.timeseriesDates, paramToCoverage
                )

                coverages.append(coverage_item)
        return coverages

    def fill_template(self, location_response: list[TransformedLocationWithResults]) -> CoverageCollection:
        templated_covjson: CoverageCollection = COVJSON_TEMPLATE
        templated_covjson["coverages"] = self._get_coverages(location_response)
        templated_covjson["parameters"] = self._get_parameter_metadata(
            location_response=location_response
        )

        return templated_covjson
