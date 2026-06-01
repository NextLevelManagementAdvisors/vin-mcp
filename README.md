# vin-mcp

MCP server for the **NHTSA vPIC** vehicle data API. Decode VINs and look up
makes, models, vehicle types, and WMIs. US-market vehicles, model year 1981+.
Specifications only — no title/accident/odometer/theft history.

Deployed at **https://vin.nlma.io/mcp** (streamable-HTTP + OAuth 2.1 gate).

## Tools

| Tool | Purpose |
| --- | --- |
| `decode_vin` | Single VIN → flat specs (~130 fields) |
| `decode_vin_extended` | Single VIN → extended/regulatory fields |
| `decode_vin_batch` | Up to 50 VINs in one call |
| `get_all_makes` | Every make in vPIC |
| `get_models_for_make` | Models for a make |
| `get_models_for_make_year` | Models filtered by year and/or vehicle type |
| `get_makes_for_vehicle_type` | Makes building a given vehicle type |
| `get_vehicle_types_for_make` | Vehicle types for a make |
| `decode_wmi` | Decode a World Manufacturer Identifier |

## Run locally (stdio, no auth)

```bash
uv pip install --system .
python -m src.server --transport stdio
```

## Run hosted (http + OAuth)

```bash
cp .env.example .env   # set MCP_OWNER_PASSWORD + MCP_BASE_URL
docker compose up -d --build
```

vPIC requires no API key. The OAuth gate exists so the server is not used as
an open relay against NHTSA's rate limiter on the host IP.

## Source

NHTSA vPIC — https://vpic.nhtsa.dot.gov/api/ (public-domain US government data).
OAuth scaffold adapted from `crumrine/fastmcp-personal-auth` (MIT), via the
attom-mcp deployment pattern.
