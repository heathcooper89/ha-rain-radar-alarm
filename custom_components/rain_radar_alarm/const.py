"""Constants for Rain Radar Alarm."""
from datetime import timedelta

DOMAIN = "rain_radar_alarm"
EVENT = f"{DOMAIN}_event"

CONF_INCLUDE_HOME = "include_home"
CONF_PERSONS = "persons"
CONF_SOON_MINUTES = "soon_minutes"
CONF_RADAR_RANGE = "radar_range"
CONF_FALLBACK = "fallback"
CONF_ALERT_PROBABILITY = "alert_probability"
CONF_RAIN_THRESHOLD = "rain_threshold"
CONF_ACCEPT_TERMS = "accept_terms"

DEFAULTS = {
    CONF_INCLUDE_HOME: True,
    CONF_PERSONS: [],              # empty = everyone
    CONF_SOON_MINUTES: 30,
    CONF_RADAR_RANGE: "3",         # 3 = 128 km images, 2 = 256 km
    CONF_FALLBACK: True,
    CONF_ALERT_PROBABILITY: 50,    # percent
    CONF_RAIN_THRESHOLD: 0.2,      # mm/h
}

HOME_KEY = "home"

# Radar polling. BoM publishes a new frame every 5-10 minutes; asking more often gains nothing.
RADAR_POLL = timedelta(minutes=5)
RADAR_IDLE_AFTER = timedelta(hours=6)        # stop refreshing a radar nobody needs any more
RADAR_STALE_AFTER = timedelta(minutes=20)    # older than this is not used for a forecast
RADAR_MIN_RETRY = timedelta(minutes=2)       # never re-fetch one radar more often than this
SITES_REFRESH = timedelta(days=7)
ISSUE_AFTER_FAILURES = 3                     # consecutive failed polls before a repair issue
MAP_LAYERS_REFRESH = timedelta(days=7)       # BoM's map layers for a radar rarely change
MAP_LAYERS_RETRY = timedelta(hours=1)
MAP_LOOPS_KEPT = 12                          # rendered loops kept in memory

# Per-location recompute (cheap: no network unless a new radar or the fallback is needed).
LOCATION_INTERVAL = timedelta(minutes=2)
MOVE_THRESHOLD_M = 750
COORD_DECIMALS = 3

FALLBACK_CACHE = timedelta(minutes=15)
FALLBACK_CELL_DEG = 0.05

STATUSES = ["dry", "rain_expected", "raining", "clearing", "cleared"]
CATEGORIES = ["none", "light", "moderate", "heavy", "intense"]
SOURCES = ["radar", "model"]

ATTRIBUTION_RADAR = "Radar data © Bureau of Meteorology, for personal non-commercial use"
ATTRIBUTION_MODEL = "Weather data by Open-Meteo.com (CC BY 4.0)"
