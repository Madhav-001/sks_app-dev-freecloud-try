"""
distance_service.py
-------------------
Provides travel-distance calculation between two GPS coordinates.

Supported providers:
  1. Ola Maps API   (Primary, OLA_MAPS_API_KEY env)
  2. Local OSRM     (Fallback 1, OSRM_URL env, default http://localhost:5000)
  3. Public OSRM    (Fallback 2, router.project-osrm.org)

To avoid unnecessary API calls:
  - Identical or near-identical coordinates (< 5 meters) skip API calls immediately.
  - Zero / invalid coordinates skip API calls immediately.
  - Calculation results are cached in Django's cache framework for 24 hours.

Returns distance in **kilometres** rounded to 3 decimal places.
On total failure (all providers unavailable), returns 0.0 and logs an error
— it NEVER raises an exception to the caller.
"""

import logging
import os
import requests
from django.core.cache import cache

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------

# Ola Maps API key & URL
OLA_MAPS_API_KEY: str = os.environ.get("OLA_MAPS_API_KEY", "").strip()
OLA_MAPS_BASE_URL: str = os.environ.get("OLA_MAPS_BASE_URL", "https://api.olamaps.io").rstrip("/")

# Local OSRM server (dev / docker-compose)
OSRM_BASE_URL: str = os.environ.get("OSRM_URL", "http://localhost:5000").rstrip("/")

# Public OSRM demo — used as automatic fallback when local server & Ola Maps are unreachable
OSRM_FALLBACK_BASE_URL: str = "http://router.project-osrm.org"

# Timeout in seconds for each HTTP call
REQUEST_TIMEOUT: int = 8


# ---------------------------------------------------------------------------
# Cache Helper
# ---------------------------------------------------------------------------

def _get_cache_key(start_lat: float, start_lon: float, end_lat: float, end_lon: float, provider: str) -> str:
    """Generate a cache key for a route coordinate pair (~1.1 meter resolution)."""
    return (
        f"dist_cache:{provider}:"
        f"{round(start_lat, 5)}:{round(start_lon, 5)}:"
        f"{round(end_lat, 5)}:{round(end_lon, 5)}"
    )


# ---------------------------------------------------------------------------
# Provider 1 — Ola Maps API (Primary)
# ---------------------------------------------------------------------------

def get_distance_ola_maps(
    start_lat: float,
    start_lon: float,
    end_lat: float,
    end_lon: float,
) -> float | None:
    """
    Call the **Ola Maps Routing / Directions API** to calculate road distance.

    Endpoint: POST/GET https://api.olamaps.io/routing/v1/directions
              ?origin={start_lat},{start_lon}&destination={end_lat},{end_lon}&api_key={OLA_MAPS_API_KEY}

    Returns distance in kilometres, or None if the request fails.
    """
    api_key = os.environ.get("OLA_MAPS_API_KEY", OLA_MAPS_API_KEY).strip()
    if not api_key or api_key in ("your_actual_api_key_here", "your_ola_maps_api_key_here", ""):
        logger.warning("[OlaMaps] OLA_MAPS_API_KEY is not configured or uses placeholder value.")
        return None

    url = f"{OLA_MAPS_BASE_URL}/routing/v1/directions"
    params = {
        "origin": f"{start_lat},{start_lon}",
        "destination": f"{end_lat},{end_lon}",
        "api_key": api_key,
    }
    headers = {
        "X-Request-Id": f"sks-{int(abs(start_lat)*1000)}-{int(abs(end_lat)*1000)}",
    }

    try:
        # Ola Maps API supports POST or GET; try POST first
        resp = requests.post(url, params=params, headers=headers, timeout=REQUEST_TIMEOUT)
        if resp.status_code in (404, 405):
            resp = requests.get(url, params=params, headers=headers, timeout=REQUEST_TIMEOUT)

        resp.raise_for_status()
        data = resp.json()

        # Parse meters from response structure
        distance_metres = None

        # 1. Directions format: routes -> legs -> distance
        if "routes" in data and isinstance(data["routes"], list) and len(data["routes"]) > 0:
            route = data["routes"][0]
            if "legs" in route and isinstance(route["legs"], list) and len(route["legs"]) > 0:
                leg_dist = route["legs"][0].get("distance")
                if isinstance(leg_dist, (int, float)):
                    distance_metres = leg_dist
                elif isinstance(leg_dist, dict):
                    distance_metres = leg_dist.get("value") or leg_dist.get("raw")

            if distance_metres is None and "distance" in route:
                route_dist = route.get("distance")
                if isinstance(route_dist, (int, float)):
                    distance_metres = route_dist
                elif isinstance(route_dist, dict):
                    distance_metres = route_dist.get("value")

        # 2. DistanceMatrix format: rows -> elements -> distance
        if distance_metres is None and "rows" in data and isinstance(data["rows"], list) and len(data["rows"]) > 0:
            row = data["rows"][0]
            if "elements" in row and isinstance(row["elements"], list) and len(row["elements"]) > 0:
                elem_dist = row["elements"][0].get("distance")
                if isinstance(elem_dist, (int, float)):
                    distance_metres = elem_dist
                elif isinstance(elem_dist, dict):
                    distance_metres = elem_dist.get("value")

        if distance_metres is not None:
            km = round(float(distance_metres) / 1000.0, 3)
            logger.info("[OlaMaps] Successfully calculated distance: %.3f km (%s meters)", km, distance_metres)
            return km

        logger.warning("[OlaMaps] Could not parse distance from response: %s", data)
        return None

    except requests.exceptions.HTTPError as http_err:
        logger.warning("[OlaMaps] HTTP error %s: %s", resp.status_code if 'resp' in locals() else 'N/A', http_err)
        return None
    except requests.exceptions.ConnectionError:
        logger.warning("[OlaMaps] Connection error connecting to %s", url)
        return None
    except requests.exceptions.Timeout:
        logger.warning("[OlaMaps] Request timed out after %ss", REQUEST_TIMEOUT)
        return None
    except Exception as exc:  # noqa: BLE001
        logger.warning("[OlaMaps] Unexpected error: %s", exc)
        return None


# ---------------------------------------------------------------------------
# Provider 2 — Local OSRM
# ---------------------------------------------------------------------------

def get_distance_osrm(
    start_lat: float,
    start_lon: float,
    end_lat: float,
    end_lon: float,
) -> float | None:
    """
    Call the **locally hosted OSRM** routing server.

    Endpoint: GET /route/v1/driving/{lon1},{lat1};{lon2},{lat2}
              ?overview=false&steps=false

    Returns distance in kilometres, or None if the request fails.
    """
    url = (
        f"{OSRM_BASE_URL}/route/v1/driving/"
        f"{start_lon},{start_lat};{end_lon},{end_lat}"
        f"?overview=false&steps=false"
    )
    try:
        resp = requests.get(url, timeout=REQUEST_TIMEOUT)
        resp.raise_for_status()
        data = resp.json()

        if data.get("code") == "Ok":
            distance_metres = data["routes"][0]["distance"]
            return round(distance_metres / 1000, 3)

        logger.warning("[OSRM-local] Unexpected response code: %s", data.get("code"))
        return None

    except requests.exceptions.ConnectionError:
        logger.warning("[OSRM-local] Connection refused — server may not be running at %s", OSRM_BASE_URL)
        return None
    except requests.exceptions.Timeout:
        logger.warning("[OSRM-local] Request timed out after %ss", REQUEST_TIMEOUT)
        return None
    except Exception as exc:  # noqa: BLE001
        logger.warning("[OSRM-local] Unexpected error: %s", exc)
        return None


# ---------------------------------------------------------------------------
# Provider 3 — OpenStreetMap public OSRM demo (fallback)
# ---------------------------------------------------------------------------

def get_distance_osrm_fallback(
    start_lat: float,
    start_lon: float,
    end_lat: float,
    end_lon: float,
) -> float | None:
    """
    Call the **public OSRM demo server** (router.project-osrm.org) as a
    fallback when primary providers are unreachable.

    Returns distance in kilometres, or None if the request fails.
    """
    url = (
        f"{OSRM_FALLBACK_BASE_URL}/route/v1/driving/"
        f"{start_lon},{start_lat};{end_lon},{end_lat}"
        f"?overview=false&steps=false"
    )
    try:
        resp = requests.get(url, timeout=REQUEST_TIMEOUT)
        resp.raise_for_status()
        data = resp.json()

        if data.get("code") == "Ok":
            distance_metres = data["routes"][0]["distance"]
            return round(distance_metres / 1000, 3)

        logger.warning("[OSRM-fallback] Unexpected response code: %s", data.get("code"))
        return None

    except requests.exceptions.ConnectionError:
        logger.warning("[OSRM-fallback] Cannot reach public OSRM demo server.")
        return None
    except requests.exceptions.Timeout:
        logger.warning("[OSRM-fallback] Request timed out after %ss", REQUEST_TIMEOUT)
        return None
    except Exception as exc:  # noqa: BLE001
        logger.warning("[OSRM-fallback] Unexpected error: %s", exc)
        return None


# ---------------------------------------------------------------------------
# Orchestrator — called by all serializers / views
# ---------------------------------------------------------------------------

def calculate_travel_distance(
    start_lat: float,
    start_lon: float,
    end_lat: float,
    end_lon: float,
    preferred_provider: str | None = None,
) -> float:
    """
    Calculate road-travel distance (in km) between two GPS coordinates.

    Strategy:
      1. Validate coordinates (skip 0/empty/out of bounds).
      2. Check identical/near-identical coordinates (< 5m difference) -> return 0.0 immediately.
      3. Check Django cache for stored result -> return cached km if present (prevents duplicate API calls).
      4. Try preferred provider (Ola Maps / OSRM local) -> fallback chain -> return 0.0 on total failure.

    Args:
        start_lat: Starting point latitude.
        start_lon: Starting point longitude.
        end_lat:   Ending point latitude.
        end_lon:   Ending point longitude.
        preferred_provider: "ola" | "osrm" | "production" | None (defaults to env DISTANCE_PROVIDER).

    Returns:
        Distance in kilometres (float, >= 0.0).
    """
    # Guard 1: Missing or zero coordinates
    if not all([start_lat, start_lon, end_lat, end_lon]):
        return 0.0

    # Guard 2: Out of bounds coordinates check
    if not (-90 <= start_lat <= 90 and -180 <= start_lon <= 180 and
            -90 <= end_lat <= 90 and -180 <= end_lon <= 180):
        logger.warning("[distance] Coordinates out of valid range: start=(%s,%s) end=(%s,%s)", start_lat, start_lon, end_lat, end_lon)
        return 0.0

    # Guard 3: Virtually identical coordinates (< 5 meters threshold ~ 0.00005 deg)
    if abs(start_lat - end_lat) < 0.00005 and abs(start_lon - end_lon) < 0.00005:
        return 0.0

    # Determine active provider order
    active_setting = (preferred_provider or os.environ.get("DISTANCE_PROVIDER", "ola")).lower()

    if active_setting in ("ola", "olamaps", "production"):
        provider_order = ["ola", "osrm_local", "osrm_fallback"]
    else:
        provider_order = ["osrm_local", "osrm_fallback", "ola"]

    # Guard 4: Check Cache to avoid unnecessary external API calls
    cache_key = _get_cache_key(start_lat, start_lon, end_lat, end_lon, active_setting)
    try:
        cached_dist = cache.get(cache_key)
        if cached_dist is not None:
            logger.debug("[distance] Cache hit for %s -> %.3f km", cache_key, cached_dist)
            return float(cached_dist)
    except Exception:
        pass  # If Django cache is not ready, continue without breaking

    # Execute provider fallback chain
    for prov in provider_order:
        dist = None
        if prov == "ola":
            dist = get_distance_ola_maps(start_lat, start_lon, end_lat, end_lon)
        elif prov == "osrm_local":
            dist = get_distance_osrm(start_lat, start_lon, end_lat, end_lon)
        elif prov == "osrm_fallback":
            dist = get_distance_osrm_fallback(start_lat, start_lon, end_lat, end_lon)

        if dist is not None:
            # Store in cache for 24 hours (86400 seconds)
            try:
                cache.set(cache_key, dist, 86400)
            except Exception:
                pass
            return dist

    logger.error(
        "[distance] All distance providers failed for (%s,%s) -> (%s,%s). Saving 0.0 km.",
        start_lat, start_lon, end_lat, end_lon,
    )
    return 0.0
