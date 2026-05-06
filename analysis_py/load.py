import glob
import os
import time
import requests
import pandas as pd

from metadata import BY_DEVICE_ID, BY_PARTICIPANT_CODE, PART_NUMBER_MODELS

API_URL = "https://batterylogger.onrender.com/api/battery-readings"

# Project root = one level above this file (i.e. BatteryLogger/)
_PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

UNIFIED_COLS = [
    'participant_code', 'device_id', 'bat', 'timestamp',
    'charging', 'watch_model', 'mst', 'data_source', 'firmware_version',
]


def load_csv():
    """Load latest smartwatch-logs CSV from project root or ~/Downloads, normalise to unified schema."""
    files = (
        glob.glob(os.path.join(_PROJECT_ROOT, 'smartwatch-logs*.csv')) +
        glob.glob(os.path.join(_PROJECT_ROOT, 'smartwatch-logs*.xlsx')) +
        glob.glob(os.path.expanduser("~/Downloads/smartwatch-logs*.csv")) +
        glob.glob(os.path.expanduser("~/Downloads/smartwatch-logs*.xlsx"))
    )
    if not files:
        print("No smartwatch-logs CSV found in project root or ~/Downloads — skipping CSV source.")
        return pd.DataFrame(columns=UNIFIED_COLS)

    latest = max(files, key=os.path.getmtime)
    print(f"CSV: {latest}")

    df = pd.read_csv(latest)
    df['timestamp'] = pd.to_datetime(df['timestamp'], format='ISO8601', errors='coerce')
    df['timestamp'] = df['timestamp'].dt.tz_localize(None)

    df = df.rename(columns={
        'battery_percentage': 'bat',
        'mst_group':          'mst',
        'device_model':       'watch_model',
    })

    # Enrich device_id from metadata where available
    def _enrich_device_id(row):
        if 'device_id' in df.columns and pd.notna(row.get('device_id')):
            return row['device_id']
        meta = BY_PARTICIPANT_CODE.get(row.get('participant_code'))
        return meta['device_id'] if meta else None

    df['device_id'] = df.apply(_enrich_device_id, axis=1)
    df['charging']         = float('nan')
    df['data_source']      = 'csv'
    df['firmware_version'] = None

    return df[UNIFIED_COLS].dropna(subset=['timestamp']).reset_index(drop=True)


def load_api(limit=500000):
    """Fetch readings from the BatteryLogger API and normalise to unified schema."""
    from_ts = int(time.time()) - 90 * 86400
    resp = requests.get(API_URL, params={'limit': limit, 'from': from_ts})
    resp.raise_for_status()
    rows = resp.json()

    if not rows:
        print("API returned no data.")
        return pd.DataFrame(columns=UNIFIED_COLS)

    df = pd.DataFrame(rows)
    df['timestamp'] = pd.to_datetime(df['ts'], unit='s', utc=True).dt.tz_localize(None)
    if 'firmware_version' not in df.columns:
        df['firmware_version'] = None

    # Enrich participant metadata from device_id
    def _enrich(row):
        meta = BY_DEVICE_ID.get(row['device_id'], {})
        # Fall back to part_number lookup if metadata has no watch_model
        watch_model = (meta.get('watch_model')
                       or PART_NUMBER_MODELS.get(row.get('part_number', ''), None))
        return pd.Series({
            'participant_code': meta.get('participant_code'),
            'watch_model':      watch_model,
            'mst':              meta.get('mst'),
        })

    enriched = df.apply(_enrich, axis=1)
    df['participant_code'] = enriched['participant_code']
    df['watch_model']      = enriched['watch_model']
    df['mst']              = enriched['mst']
    df['data_source']      = 'api'

    return df[UNIFIED_COLS].dropna(subset=['timestamp']).reset_index(drop=True)


def load_all():
    """Load CSV + API, merge, deduplicate, and return unified DataFrame."""
    csv_df = load_csv()
    api_df = load_api()

    data = pd.concat([csv_df, api_df], ignore_index=True)
    data = data.sort_values('timestamp').reset_index(drop=True)

    # Drop participants/devices with only a single reading across combined data
    key = data['participant_code'].where(data['participant_code'].notna(), data['device_id'])
    counts = key.value_counts()
    valid  = counts[counts > 1].index
    removed = counts[counts == 1].index.tolist()
    if removed:
        print(f"Removed single-log participants: {removed}")
    data = data[key.isin(valid)].reset_index(drop=True)

    n_participants = data['participant_code'].nunique() + data.loc[
        data['participant_code'].isna(), 'device_id'
    ].nunique()
    print(f"{n_participants} participant(s) | {len(data)} readings "
          f"({len(csv_df)} CSV + {len(api_df)} API)")
    print(f"Date range: {data['timestamp'].min():%d %b %H:%M} → "
          f"{data['timestamp'].max():%d %b %H:%M}")
    return data
