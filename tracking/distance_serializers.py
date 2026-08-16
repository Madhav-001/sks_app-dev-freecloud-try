"""
distance_serializers.py
-----------------------
Provider-swappable distance calculation classes.

Concrete serializer classes:
  • OlaMapsDistanceSerializer   — primary, uses Ola Maps API (+ OSRM fallback)
  • OSRMDistanceSerializer      — dev, uses local OSRM + OSM fallback
  • ProductionDistanceSerializer — production wrapper (uses Ola Maps API)

Use `get_active_distance_serializer()` to obtain the correct instance based on
the DISTANCE_PROVIDER environment variable (default: "ola").

To switch providers:
  Set DISTANCE_PROVIDER=ola (or osrm, or production) in .env.
  No code modification is required.
"""

import logging
import os

from .distance_service import calculate_travel_distance

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Base class
# ---------------------------------------------------------------------------

class BaseDistanceSerializer:
    """
    Abstract-like base for all distance provider serializers.

    Subclasses must implement `get_distance`.
    """

    provider_name = "base"

    def get_distance(
        self,
        start_lat: float,
        start_lon: float,
        end_lat: float,
        end_lon: float,
    ) -> float:
        """
        Return road-travel distance in kilometres between two GPS points.

        Args:
            start_lat: Origin latitude.
            start_lon: Origin longitude.
            end_lat:   Destination latitude.
            end_lon:   Destination longitude.

        Returns:
            Distance in km (float). Must never raise; return 0.0 on failure.
        """
        raise NotImplementedError("Subclasses must implement get_distance()")


# ---------------------------------------------------------------------------
# Provider 1 — Ola Maps API (Primary)
# ---------------------------------------------------------------------------

class OlaMapsDistanceSerializer(BaseDistanceSerializer):
    """
    Primary distance provider using Ola Maps Routing API.
    Falls back automatically to local OSRM / public OSRM if Ola Maps is unreachable.
    """

    provider_name = "ola"

    def get_distance(
        self,
        start_lat: float,
        start_lon: float,
        end_lat: float,
        end_lon: float,
    ) -> float:
        """Calculate distance using Ola Maps API primary provider."""
        return calculate_travel_distance(start_lat, start_lon, end_lat, end_lon, preferred_provider="ola")


# ---------------------------------------------------------------------------
# Provider 2 — OSRM (Local / Dev)
# ---------------------------------------------------------------------------

class OSRMDistanceSerializer(BaseDistanceSerializer):
    """
    Development distance provider using local OSRM server with public OSRM fallback.
    """

    provider_name = "osrm"

    def get_distance(
        self,
        start_lat: float,
        start_lon: float,
        end_lat: float,
        end_lon: float,
    ) -> float:
        """Calculate distance using OSRM local provider."""
        return calculate_travel_distance(start_lat, start_lon, end_lat, end_lon, preferred_provider="osrm")


# ---------------------------------------------------------------------------
# Provider 3 — Production Wrapper
# ---------------------------------------------------------------------------

class ProductionDistanceSerializer(BaseDistanceSerializer):
    """
    Production distance provider wrapper (defaults to Ola Maps API).
    """

    provider_name = "production"

    def get_distance(
        self,
        start_lat: float,
        start_lon: float,
        end_lat: float,
        end_lon: float,
    ) -> float:
        """Calculate distance for production mode."""
        return calculate_travel_distance(start_lat, start_lon, end_lat, end_lon, preferred_provider="ola")


# ---------------------------------------------------------------------------
# Factory — returns the active provider
# ---------------------------------------------------------------------------

_PROVIDER_MAP: dict[str, type[BaseDistanceSerializer]] = {
    "ola": OlaMapsDistanceSerializer,
    "olamaps": OlaMapsDistanceSerializer,
    "osrm": OSRMDistanceSerializer,
    "production": ProductionDistanceSerializer,
}


def get_active_distance_serializer() -> BaseDistanceSerializer:
    """
    Return an instance of the currently configured distance provider.

    Reads DISTANCE_PROVIDER from the environment (default: "ola").

    Usage:
        from tracking.distance_serializers import get_active_distance_serializer
        ds = get_active_distance_serializer()
        km = ds.get_distance(start_lat, start_lon, end_lat, end_lon)
    """
    provider_key = os.environ.get("DISTANCE_PROVIDER", "ola").lower()
    serializer_class = _PROVIDER_MAP.get(provider_key)

    if serializer_class is None:
        logger.warning(
            "[distance_serializers] Unknown DISTANCE_PROVIDER='%s'. "
            "Falling back to OlaMapsDistanceSerializer.",
            provider_key,
        )
        serializer_class = OlaMapsDistanceSerializer

    return serializer_class()
