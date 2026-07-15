"""Generated from contracts/firmware-behavior.json. Do not edit by hand."""

from __future__ import annotations

SCHEMA_VERSION = '1.0'
FUSION_THRESHOLDS = {'temperature_c': {'watch_above': 28.0, 'alert_above': 32.0},
 'humidity_percent': {'watch_below': 30.0, 'watch_above': 75.0},
 'tvoc_ppb': {'watch_above': 300, 'alert_above': 600},
 'hcho_ug_m3': {'watch_above': 60, 'alert_above': 100},
 'eco2_ppm': {'watch_above': 1000, 'alert_above': 1500}}
COMMAND_QUEUE_LENGTH = 4
TERMINAL_ACK_CACHE_SIZE = 16
SMOKE_SILENCE_MIN_SECONDS = 10
SMOKE_SILENCE_MAX_SECONDS = 600
SMOKE_REANNOUNCE_SECONDS = 30
SMOKE_CLEAR_STABLE_MS = 1000
VOICE_LOCAL_RETRY_ATTEMPTS = 3
VOICE_RETRY_BACKOFF_MS = 250
VOICE_TX_TIMEOUT_MS = 1000
COMMAND_EXECUTION_PERIOD_MS = 500
