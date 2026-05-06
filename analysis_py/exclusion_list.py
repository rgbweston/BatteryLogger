# exclusion_list.py
# Participants / devices to exclude from all plots and cycle analysis.
# Add participant_code strings or device_id hashes to the relevant list.

EXCLUDED_PARTICIPANT_CODES = [
   # 'warm-fox-8',
   # 'wise-fox-66',
   # 'merry-moose-23',
   # 'noble-numbat-5',
   # 'clever-gecko-71',
]

EXCLUDED_DEVICE_IDS = [
    '4013ffdec83138e6888a0828450df3308d9fb485',
    # any with prefix strings: 5be3da43** using regex
    r'5be3da43*']

# ── Per-participant SDK connectivity windows ───────────────────────────────────
# Only data within [from_ts, to_ts] is used for analysis.
# Use None to mean "no bound" (i.e. from the beginning or up to now).
# Keyed by participant_code or device_id prefix (first 8 chars).

import pandas as pd

SDK_WINDOWS = {
    # fierce-newt-7: SDK disconnected from 14 Apr 15:00 onwards
    'fierce-newt-7': {
        'from_ts': None,
        'to_ts': pd.Timestamp('2026-04-14 15:00:00')
    },

    # 0457c34a: SDK only connected from 14 Apr 15:00 onwards
    '0457c34ac33a3bc3ee0196003561d39b6b9a4080': {
        'from_ts': pd.Timestamp('2026-04-14 15:00:00'),
        'to_ts': None
    },
}

# ── Cycle filtering rules ──────────────────────────────────────────────────────
# These thresholds are used to exclude unreliable / noisy discharge cycles.

# Minimum duration for a cycle to be considered valid (in hours)
MIN_CYCLE_DURATION_HOURS = 0.5  # 30 minutes

# Maximum allowed drain rate (to filter extreme outliers)
MAX_DRAIN_PERCENT_PER_DAY = 200

# Optional: minimum battery drop required for a valid cycle
# (helps remove tiny fluctuations like 1% noise)
MIN_CYCLE_DROP_PERCENT = 1  # set to 3 if you want stricter filtering