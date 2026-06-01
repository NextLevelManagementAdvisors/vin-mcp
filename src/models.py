"""Shared response model for vin-mcp tools."""

from typing import Any, Optional

from pydantic import BaseModel


class VpicResponse(BaseModel):
    """Uniform tool response wrapper.

    `data` holds the relevant slice of the vPIC payload (usually the `Results`
    list, or the single `Results[0]` object for single-VIN decodes).
    """

    status_code: int
    status_message: str
    data: Optional[Any] = None
