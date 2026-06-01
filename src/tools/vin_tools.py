"""MCP tools wrapping the NHTSA vPIC vehicle data API.

All tools are read-only. Coverage is US-market vehicles, model year 1981 and
forward. vPIC returns specifications only — there is no title, accident,
odometer, or theft history here (that requires a commercial / NMVTIS source).
"""

from typing import List, Optional

import structlog
from pydantic import BaseModel, Field

from src.client import client
from src.mcp_server import mcp
from src.models import VpicResponse

logger = structlog.get_logger(__name__)


# --------------------------------------------------------------------------- #
# Parameter models
# --------------------------------------------------------------------------- #
class DecodeVinParams(BaseModel):
    vin: str = Field(
        ...,
        description=(
            "Vehicle Identification Number. Full 17-char VIN for a clean "
            "decode, or a partial VIN with '*' wildcards for pattern decoding "
            "(e.g. '5UXWX7C5*BA'). Case-insensitive."
        ),
    )
    model_year: Optional[int] = Field(
        None,
        description=(
            "Optional model year. Improves accuracy for partial VINs and for "
            "years where the VIN pattern is ambiguous. Ignored if omitted."
        ),
    )


class BatchDecodeParams(BaseModel):
    entries: List[str] = Field(
        ...,
        description=(
            "Up to 50 entries. Each entry is a VIN, optionally with a model "
            "year appended after a comma, e.g. ['5UXWX7C5*BA,2011', "
            "'1FA6P8TD5M5100001']. Max 50 per call."
        ),
    )


class MakeParam(BaseModel):
    make: str = Field(
        ...,
        description="Make name (e.g. 'honda') or numeric Make ID. Case-insensitive.",
    )


class ModelsForMakeYearParams(BaseModel):
    make: str = Field(..., description="Make name or numeric Make ID.")
    model_year: Optional[int] = Field(
        None,
        description="Model year (1981+). Provide this OR vehicle_type (at least one).",
    )
    vehicle_type: Optional[str] = Field(
        None,
        description=(
            "Vehicle type filter (e.g. 'truck', 'car', 'motorcycle'). Provide "
            "this OR model_year (at least one is required by vPIC)."
        ),
    )


class VehicleTypeParam(BaseModel):
    vehicle_type: str = Field(
        ...,
        description="Vehicle type name or partial (e.g. 'truck', 'car', 'mot').",
    )


class WmiParam(BaseModel):
    wmi: str = Field(
        ...,
        description=(
            "World Manufacturer Identifier. 3 chars (VIN positions 1-3, e.g. "
            "'JTD') or 6 chars (positions 1-3 + 12-14, e.g. '1T9131')."
        ),
    )


# --------------------------------------------------------------------------- #
# Helpers
# --------------------------------------------------------------------------- #
def _ok(data, message: str = "Success") -> VpicResponse:
    return VpicResponse(status_code=200, status_message=message, data=data)


def _err(e: Exception) -> VpicResponse:
    return VpicResponse(status_code=500, status_message=f"Error: {e}")


def _results(payload: dict):
    return payload.get("Results")


# --------------------------------------------------------------------------- #
# Tools
# --------------------------------------------------------------------------- #
@mcp.tool()
async def decode_vin(params: DecodeVinParams) -> VpicResponse:
    """Decode a single VIN to a flat set of vehicle specifications.

    Returns the most useful ~130 fields (make, model, model year, trim/series,
    body class, engine cylinders/displacement, fuel type, drive type, GVWR,
    plant city/country, manufacturer, plus an ErrorCode/ErrorText indicating
    decode confidence). Use decode_vin_extended for the additional
    NCSA/regulatory variables.
    """
    log = logger.bind(tool="decode_vin", vin=params.vin)
    try:
        payload = await client.get(
            f"DecodeVinValues/{params.vin}",
            {"modelyear": params.model_year},
        )
        results = _results(payload)
        data = results[0] if isinstance(results, list) and results else results
        return _ok(data, payload.get("Message", "Success"))
    except Exception as e:  # noqa: BLE001
        log.error("decode_vin failed", error=str(e))
        return _err(e)


@mcp.tool()
async def decode_vin_extended(params: DecodeVinParams) -> VpicResponse:
    """Decode a single VIN (extended) with additional regulatory variables.

    Same flat output as decode_vin plus extra fields tied to other NHTSA
    programs (e.g. NCSA). Use when you need attributes not present in the
    standard decode.
    """
    log = logger.bind(tool="decode_vin_extended", vin=params.vin)
    try:
        payload = await client.get(
            f"DecodeVinValuesExtended/{params.vin}",
            {"modelyear": params.model_year},
        )
        results = _results(payload)
        data = results[0] if isinstance(results, list) and results else results
        return _ok(data, payload.get("Message", "Success"))
    except Exception as e:  # noqa: BLE001
        log.error("decode_vin_extended failed", error=str(e))
        return _err(e)


@mcp.tool()
async def decode_vin_batch(params: BatchDecodeParams) -> VpicResponse:
    """Decode up to 50 VINs in a single call.

    Each entry may be 'VIN' or 'VIN,modelyear'. Returns one flat result object
    per VIN. Use for inventory/fleet processing instead of looping decode_vin.
    """
    log = logger.bind(tool="decode_vin_batch", n=len(params.entries))
    if not params.entries:
        return VpicResponse(status_code=400, status_message="No entries provided.")
    if len(params.entries) > 50:
        return VpicResponse(
            status_code=400,
            status_message="Too many entries: vPIC batch is capped at 50 VINs.",
        )
    data_str = ";".join(e.strip() for e in params.entries if e.strip())
    try:
        payload = await client.post_form("DecodeVINValuesBatch", {"data": data_str})
        return _ok(_results(payload), payload.get("Message", "Success"))
    except Exception as e:  # noqa: BLE001
        log.error("decode_vin_batch failed", error=str(e))
        return _err(e)


@mcp.tool()
async def get_all_makes() -> VpicResponse:
    """List every vehicle make registered in vPIC (Make_ID + Make_Name).

    Large list (thousands of makes). Useful for validating/normalizing a make
    name before calling get_models_for_make.
    """
    try:
        payload = await client.get("GetAllMakes")
        return _ok(_results(payload), payload.get("Message", "Success"))
    except Exception as e:  # noqa: BLE001
        logger.bind(tool="get_all_makes").error("failed", error=str(e))
        return _err(e)


@mcp.tool()
async def get_models_for_make(params: MakeParam) -> VpicResponse:
    """List all models for a given make (across all years)."""
    log = logger.bind(tool="get_models_for_make", make=params.make)
    try:
        payload = await client.get(f"GetModelsForMake/{params.make}")
        return _ok(_results(payload), payload.get("Message", "Success"))
    except Exception as e:  # noqa: BLE001
        log.error("failed", error=str(e))
        return _err(e)


@mcp.tool()
async def get_models_for_make_year(params: ModelsForMakeYearParams) -> VpicResponse:
    """List models for a make filtered by model year and/or vehicle type.

    At least one of model_year or vehicle_type is required by vPIC. Both may
    be combined to narrow results (e.g. Honda + 2015 + truck).
    """
    log = logger.bind(tool="get_models_for_make_year", make=params.make)
    if params.model_year is None and not params.vehicle_type:
        return VpicResponse(
            status_code=400,
            status_message="Provide model_year and/or vehicle_type.",
        )
    path = f"GetModelsForMakeYear/make/{params.make}"
    if params.model_year is not None:
        path += f"/modelyear/{params.model_year}"
    if params.vehicle_type:
        path += f"/vehicletype/{params.vehicle_type}"
    try:
        payload = await client.get(path)
        return _ok(_results(payload), payload.get("Message", "Success"))
    except Exception as e:  # noqa: BLE001
        log.error("failed", error=str(e))
        return _err(e)


@mcp.tool()
async def get_makes_for_vehicle_type(params: VehicleTypeParam) -> VpicResponse:
    """List makes that build a given vehicle type (e.g. all 'truck' makes)."""
    log = logger.bind(tool="get_makes_for_vehicle_type", vt=params.vehicle_type)
    try:
        payload = await client.get(
            f"GetMakesForVehicleType/{params.vehicle_type}"
        )
        return _ok(_results(payload), payload.get("Message", "Success"))
    except Exception as e:  # noqa: BLE001
        log.error("failed", error=str(e))
        return _err(e)


@mcp.tool()
async def get_vehicle_types_for_make(params: MakeParam) -> VpicResponse:
    """List the vehicle types a given make produces."""
    log = logger.bind(tool="get_vehicle_types_for_make", make=params.make)
    try:
        payload = await client.get(f"GetVehicleTypesForMake/{params.make}")
        return _ok(_results(payload), payload.get("Message", "Success"))
    except Exception as e:  # noqa: BLE001
        log.error("failed", error=str(e))
        return _err(e)


@mcp.tool()
async def decode_wmi(params: WmiParam) -> VpicResponse:
    """Decode a World Manufacturer Identifier (WMI).

    Returns the manufacturer, country, vehicle type, and make associated with
    a 3- or 6-character WMI code (VIN positions 1-3, optionally + 12-14).
    """
    log = logger.bind(tool="decode_wmi", wmi=params.wmi)
    try:
        payload = await client.get(f"DecodeWMI/{params.wmi}")
        return _ok(_results(payload), payload.get("Message", "Success"))
    except Exception as e:  # noqa: BLE001
        log.error("failed", error=str(e))
        return _err(e)
