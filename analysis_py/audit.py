#!/usr/bin/env python3
"""
audit.py — Exhaustive data audit for BatteryLogger study data.

Run from the analysis_py directory:
    python audit.py

Prints structured plain-text report. No plots, no modelling.
"""

import os, sys, time, requests
import pandas as pd
import numpy as np

SCRIPT_DIR   = os.path.dirname(os.path.abspath(__file__))

# ── tee stdout to file ────────────────────────────────────────────────────────
_OUT_PATH = os.path.join(SCRIPT_DIR, 'audit_output.txt')
_out_file = open(_OUT_PATH, 'w', encoding='utf-8')

class _Tee:
    def __init__(self, *files): self.files = files
    def write(self, obj):
        for f in self.files: f.write(obj); f.flush()
    def flush(self):
        for f in self.files: f.flush()

sys.stdout = _Tee(sys.__stdout__, _out_file)
PROJECT_ROOT = os.path.dirname(SCRIPT_DIR)
CSV_PATH     = os.path.join(PROJECT_ROOT, 'smartwatch-logs.csv')
API_URL      = "https://batterylogger.onrender.com/api/battery-readings"
TODAY        = pd.Timestamp.now().normalize()
STUDY_START  = pd.Timestamp('2024-01-01')

sys.path.insert(0, SCRIPT_DIR)
from metadata import BY_DEVICE_ID, BY_PARTICIPANT_CODE, PART_NUMBER_MODELS, PARTICIPANTS
from config   import CONFIG_SORTED

# ── formatting helpers ────────────────────────────────────────────────────────

SEP    = "=" * 80
SUBSEP = "-" * 60

def hdr(title):
    print(f"\n{SEP}\n  {title}\n{SEP}")

def sub(title):
    print(f"\n{SUBSEP}\n  {title}\n{SUBSEP}")

def pct(n, total):
    return f"{100*n/total:.1f}%" if total else "—"

def fmt(ts):
    return pd.Timestamp(ts).strftime('%Y-%m-%d %H:%M') if pd.notna(ts) else "NaT"

def qdesc(series, unit=""):
    s = series.dropna()
    if s.empty:
        return "  (no data)"
    qs = {p: s.quantile(p/100) for p in [0, 5, 25, 50, 75, 95, 100]}
    return (f"  min={qs[0]:.2f}{unit}  p5={qs[5]:.2f}{unit}  p25={qs[25]:.2f}{unit}  "
            f"med={qs[50]:.2f}{unit}  p75={qs[75]:.2f}{unit}  p95={qs[95]:.2f}{unit}  "
            f"max={qs[100]:.2f}{unit}  mean={s.mean():.2f}{unit}  std={s.std():.2f}{unit}")

def get_era(timestamp):
    era = 'Pre SpO2'
    for name, ts in CONFIG_SORTED:
        if timestamp >= ts:
            era = f'Post {name}'
    return era


# ── load ──────────────────────────────────────────────────────────────────────

print("Loading CSV …")
csv = pd.read_csv(CSV_PATH)
csv['timestamp'] = pd.to_datetime(csv['timestamp'], format='ISO8601', errors='coerce')
csv['timestamp'] = csv['timestamp'].dt.tz_localize(None)

BOOL_COLS = [
    'heart_rate', 'respiration_rate', 'stress', 'steps', 'bbi', 'enhanced_bbi',
    'gyroscope', 'skin_temperature', 'wrist_status', 'accelerometer',
    'zero_crossing', 'actigraphy_1', 'actigraphy_2', 'actigraphy_3', 'always_on_display',
]
for col in BOOL_COLS:
    if col in csv.columns:
        csv[col] = csv[col].map({'true': True, 'false': False, True: True, False: False})

print("Fetching API (all records, limit=500000) …")
resp = requests.get(API_URL, params={'limit': 500000, 'from': 0}, timeout=120)
resp.raise_for_status()
api = pd.DataFrame(resp.json())

if not api.empty:
    api['timestamp'] = pd.to_datetime(api['ts'], unit='s', utc=True).dt.tz_localize(None)
    api['charging']  = api['charging'].astype(int)
    def _enrich(row):
        meta = BY_DEVICE_ID.get(row['device_id'], {})
        wm   = meta.get('watch_model') or PART_NUMBER_MODELS.get(row.get('part_number', ''), None)
        return pd.Series({
            'participant_code': meta.get('participant_code'),
            'watch_model':      wm,
            'mst':              meta.get('mst'),
        })
    enriched = api.apply(_enrich, axis=1)
    api = pd.concat([api, enriched], axis=1)
    api['era'] = api['timestamp'].apply(get_era)


# ══════════════════════════════════════════════════════════════════════════════
# SECTION 1: RAW STRUCTURE
# ══════════════════════════════════════════════════════════════════════════════

hdr("SECTION 1: RAW STRUCTURE")

sub("1a — CSV")
print(f"  File:        {CSV_PATH}")
print(f"  Shape:       {csv.shape[0]} rows × {csv.shape[1]} columns")
print(f"  Memory:      {csv.memory_usage(deep=True).sum() / 1024:.1f} KB")
print()
print("  Columns and dtypes:")
for col in csv.columns:
    nulls = csv[col].isna().sum()
    print(f"    {col:<30} {str(csv[col].dtype):<12} nulls={nulls}")

print("\n  ── First 5 rows ──")
with pd.option_context('display.max_columns', None, 'display.width', 200, 'display.max_colwidth', 40):
    print(csv.head().to_string(index=True))

print("\n  ── Last 5 rows ──")
with pd.option_context('display.max_columns', None, 'display.width', 200, 'display.max_colwidth', 40):
    print(csv.tail().to_string(index=True))

sub("1b — API")
print(f"  URL:         {API_URL}")
print(f"  Records:     {len(api)}")
if not api.empty:
    print()
    print("  Fields and inferred types (including enriched):")
    for col in api.columns:
        nulls = api[col].isna().sum()
        print(f"    {col:<30} {str(api[col].dtype):<12} nulls={nulls}")

    print("\n  ── First 5 records ──")
    with pd.option_context('display.max_columns', None, 'display.width', 200, 'display.max_colwidth', 40):
        print(api.head().to_string(index=True))

    print("\n  ── Last 5 records ──")
    with pd.option_context('display.max_columns', None, 'display.width', 200, 'display.max_colwidth', 40):
        print(api.tail().to_string(index=True))


# ══════════════════════════════════════════════════════════════════════════════
# SECTION 2: PARTICIPANT / DEVICE INVENTORY
# ══════════════════════════════════════════════════════════════════════════════

hdr("SECTION 2: PARTICIPANT / DEVICE INVENTORY")

sub("2a — CSV: participant_codes")
csv_codes = csv['participant_code'].value_counts().sort_index()
print(f"  Unique participant_codes: {len(csv_codes)}")
print(f"  {'participant_code':<30} {'readings':>8}")
print(f"  {'-'*30} {'-'*8}")
for code, cnt in csv_codes.items():
    print(f"  {str(code):<30} {cnt:>8}")

sub("2b — CSV: device_models")
for model, cnt in csv['device_model'].value_counts().items():
    print(f"  {str(model):<25} {cnt:>4}")

sub("2c — CSV: mst_group values")
for mst, cnt in csv['mst_group'].value_counts().sort_index().items():
    print(f"  MST {mst}: {cnt}")

sub("2d — CSV: config_names (sorted by first appearance)")
first_seen = csv.groupby('config_name')['timestamp'].min().sort_values()
counts = csv['config_name'].value_counts()
print(f"  {'config_name':<30} {'first seen':<22} {'readings':>8}")
print(f"  {'-'*30} {'-'*22} {'-'*8}")
for cfg, ts in first_seen.items():
    print(f"  {str(cfg):<30} {fmt(ts):<22} {counts.get(cfg, 0):>8}")

sub("2e — CSV: cross-tab participant_code × config_name")
xt = pd.crosstab(csv['participant_code'], csv['config_name'])
print(xt.to_string())

sub("2f — CSV: participant_code × device_model (flag multi-model)")
xt2 = pd.crosstab(csv['participant_code'], csv['device_model'])
print(xt2.to_string())
multi_model = (xt2 > 0).sum(axis=1)
flagged = multi_model[multi_model > 1]
if not flagged.empty:
    print(f"\n  ⚠  Participants appearing under >1 device model: {list(flagged.index)}")
else:
    print("\n  ✓  No participant appears under more than one device model.")

if not api.empty:
    sub("2g — API: device_ids with reading counts")
    dev_counts = api['device_id'].value_counts()
    print(f"  Unique device_ids: {len(dev_counts)}")
    print(f"  {'device_id':<45} {'readings':>8}  {'participant_code'}")
    print(f"  {'-'*45} {'-'*8}  {'-'*20}")
    for did, cnt in dev_counts.items():
        pc = BY_DEVICE_ID.get(did, {}).get('participant_code', '—')
        print(f"  {did:<45} {cnt:>8}  {pc}")

    sub("2h — API: part_numbers with counts")
    for pn, cnt in api['part_number'].value_counts().items():
        model = PART_NUMBER_MODELS.get(pn, '(unknown)')
        print(f"  {str(pn):<20} {cnt:>5}  → {model}")

    sub("2i — API: watch_models post-enrichment")
    for wm, cnt in api['watch_model'].value_counts().items():
        print(f"  {str(wm):<25} {cnt:>5}")

    sub("2j — API: participant_codes post-enrichment")
    pc_counts = api['participant_code'].value_counts(dropna=False)
    print(f"  {'participant_code':<30} {'readings':>8}")
    print(f"  {'-'*30} {'-'*8}")
    for pc, cnt in pc_counts.items():
        print(f"  {str(pc):<30} {cnt:>8}")

    sub("2k — API: device_ids with >1 part_number (potential swap)")
    pn_per_dev = api.groupby('device_id')['part_number'].nunique()
    swaps = pn_per_dev[pn_per_dev > 1]
    if swaps.empty:
        print("  ✓  No device appears with more than one part_number.")
    else:
        for did, n in swaps.items():
            pns = api[api['device_id'] == did]['part_number'].unique()
            print(f"  ⚠  {did}  →  {list(pns)}")


# ══════════════════════════════════════════════════════════════════════════════
# SECTION 2L: ACTIVE DEVICES STATUS TABLE
# ══════════════════════════════════════════════════════════════════════════════

hdr("SECTION 2L: ACTIVE DEVICES STATUS TABLE")

if not api.empty:
    now = pd.Timestamp.now()

    # Build name lookup: device_id → participant_name
    name_by_did = {p['device_id']: p.get('participant_name', '—')
                   for p in PARTICIPANTS if p.get('device_id')}

    rows_status = []
    for did, grp in api.groupby('device_id'):
        g = grp.sort_values('timestamp')
        last = g.iloc[-1]

        last_seen_td  = now - last['timestamp']
        last_seen_h   = last_seen_td.total_seconds() / 3600
        if last_seen_h < 1:
            last_seen_str = f"{int(last_seen_td.total_seconds()/60)}m ago"
        elif last_seen_h < 24:
            last_seen_str = f"{last_seen_h:.0f}h ago"
        else:
            last_seen_str = f"{last_seen_h/24:.0f}d ago"

        status = '●' if last_seen_h < 6 else ('○' if last_seen_h < 48 else '·')

        meta         = BY_DEVICE_ID.get(did, {})
        part_code    = meta.get('participant_code') or '—'
        part_name    = name_by_did.get(did) or '—'
        mst          = meta.get('mst') or '—'
        model        = last.get('watch_model') or PART_NUMBER_MODELS.get(last.get('part_number', ''), last.get('part_number', '—'))
        firmware     = last.get('firmware_version', '—')
        app_ver      = last.get('version', '—')
        bat          = f"{last['bat']:.0f}%"
        total_n      = len(grp)

        rows_status.append({
            'device_id':   did[:8] + '…',
            'code':        part_code,
            'name':        part_name,
            'MST':         mst,
            'model':       str(model),
            'firmware':    firmware,
            'app':         app_ver,
            'battery':     bat,
            'last_seen':   last_seen_str,
            'status':      status,
            'n_readings':  total_n,
            '_last_ts':    last['timestamp'],
        })

    df_status = (pd.DataFrame(rows_status)
                   .sort_values('_last_ts', ascending=False)
                   .drop(columns='_last_ts'))

    # print as aligned table
    cols = ['device_id', 'code', 'name', 'MST', 'model', 'firmware', 'app',
            'battery', 'last_seen', 'status', 'n_readings']
    widths = {c: max(len(c), df_status[c].astype(str).str.len().max()) for c in cols}

    header = '  ' + '  '.join(c.ljust(widths[c]) for c in cols)
    divider = '  ' + '  '.join('-' * widths[c] for c in cols)
    print(header)
    print(divider)
    for _, row in df_status.iterrows():
        print('  ' + '  '.join(str(row[c]).ljust(widths[c]) for c in cols))

    print(f"\n  ● = seen <6h    ○ = seen <48h    · = seen >48h")
    print(f"  Total active devices: {len(df_status)}")
else:
    print("  No API data available.")


# ══════════════════════════════════════════════════════════════════════════════
# SECTION 3: TEMPORAL COVERAGE
# ══════════════════════════════════════════════════════════════════════════════

hdr("SECTION 3: TEMPORAL COVERAGE")

sub("3a — CSV: global range")
print(f"  Min timestamp: {fmt(csv['timestamp'].min())}")
print(f"  Max timestamp: {fmt(csv['timestamp'].max())}")

sub("3b — CSV: per-participant coverage")
print(f"  {'code':<25} {'first':<18} {'last':<18} {'span(d)':>7} {'n':>5} {'med_gap(h)':>11} {'max_gap(h)':>11}")
print(f"  {'-'*25} {'-'*18} {'-'*18} {'-'*7} {'-'*5} {'-'*11} {'-'*11}")
for code, grp in csv.sort_values('timestamp').groupby('participant_code'):
    ts = grp['timestamp'].sort_values()
    span = (ts.max() - ts.min()).total_seconds() / 86400
    gaps = ts.diff().dt.total_seconds().dropna() / 3600
    med_gap = gaps.median() if len(gaps) else float('nan')
    max_gap = gaps.max() if len(gaps) else float('nan')
    print(f"  {str(code):<25} {fmt(ts.min()):<18} {fmt(ts.max()):<18} {span:>7.1f} {len(ts):>5} {med_gap:>11.1f} {max_gap:>11.1f}")

sub("3c — CSV: inter-reading gap distribution (all participants combined)")
all_gaps_csv = []
for _, grp in csv.groupby('participant_code'):
    gaps = grp.sort_values('timestamp')['timestamp'].diff().dt.total_seconds().dropna() / 3600
    all_gaps_csv.extend(gaps.tolist())
if all_gaps_csv:
    s = pd.Series(all_gaps_csv)
    print(qdesc(s, "h"))

sub("3d — CSV: duplicate timestamps per participant")
dupes = csv[csv.duplicated(subset=['participant_code', 'timestamp'], keep=False)]
if dupes.empty:
    print("  ✓  No duplicate timestamps found.")
else:
    print(f"  ⚠  {len(dupes)} rows share a (participant_code, timestamp) pair:")
    print(dupes[['participant_code', 'timestamp']].to_string())

sub("3e — CSV: timestamps outside plausible study window")
bad_ts = csv[(csv['timestamp'] < STUDY_START) | (csv['timestamp'] > TODAY)]
if bad_ts.empty:
    print(f"  ✓  All timestamps are within [{STUDY_START.date()} → {TODAY.date()}].")
else:
    print(f"  ⚠  {len(bad_ts)} out-of-range timestamps:")
    print(bad_ts[['participant_code', 'timestamp']].to_string())

if not api.empty:
    sub("3f — API: global range")
    print(f"  Min timestamp: {fmt(api['timestamp'].min())}")
    print(f"  Max timestamp: {fmt(api['timestamp'].max())}")

    sub("3g — API: per-device coverage and completeness")
    print(f"  {'device_id':<45} {'first':<18} {'last':<18} {'span(d)':>7} "
          f"{'actual':>7} {'expect@5m':>10} {'complete%':>10} {'part_code'}")
    print(f"  {'-'*45} {'-'*18} {'-'*18} {'-'*7} {'-'*7} {'-'*10} {'-'*10} {'-'*20}")
    for did, grp in api.sort_values('timestamp').groupby('device_id'):
        ts = grp['timestamp'].sort_values()
        span = (ts.max() - ts.min()).total_seconds() / 86400
        expected = int(span * 24 * 60 / 5) + 1
        actual   = len(ts)
        completeness = pct(actual, expected)
        pc = BY_DEVICE_ID.get(did, {}).get('participant_code', '—')
        print(f"  {did:<45} {fmt(ts.min()):<18} {fmt(ts.max()):<18} {span:>7.1f} "
              f"{actual:>7} {expected:>10} {completeness:>10}  {pc}")

    sub("3h — API: inter-reading gap distribution per device")
    long_gaps_1h  = 0
    long_gaps_6h  = 0
    long_gaps_24h = 0
    for did, grp in api.groupby('device_id'):
        ts = grp.sort_values('timestamp')['timestamp']
        gaps = ts.diff().dt.total_seconds().dropna() / 3600
        if gaps.empty:
            continue
        pc = BY_DEVICE_ID.get(did, {}).get('participant_code') or did[:12] + '…'
        print(f"  {pc}  ({did[:8]}…)")
        print(f"    {qdesc(gaps, 'h').strip()}")
        g1  = (gaps > 1).sum()
        g6  = (gaps > 6).sum()
        g24 = (gaps > 24).sum()
        print(f"    gaps >1h: {g1}  >6h: {g6}  >24h: {g24}")
        long_gaps_1h  += g1
        long_gaps_6h  += g6
        long_gaps_24h += g24
    print(f"\n  Totals across all devices:  gaps >1h={long_gaps_1h}  >6h={long_gaps_6h}  >24h={long_gaps_24h}")

    sub("3i — API: readings per device per day (summary)")
    api['date'] = api['timestamp'].dt.date
    rpd = api.groupby(['device_id', 'date']).size().reset_index(name='n')
    summary = rpd.groupby('device_id')['n'].agg(['mean', 'min', 'max', 'count'])
    summary.columns = ['mean_per_day', 'min_per_day', 'max_per_day', 'days_with_data']
    summary.index = [BY_DEVICE_ID.get(d, {}).get('participant_code') or d[:12]+'…'
                     for d in summary.index]
    print(summary.round(1).to_string())

    sub("3j — API: duplicate timestamps per device")
    dupes_api = api[api.duplicated(subset=['device_id', 'timestamp'], keep=False)]
    if dupes_api.empty:
        print("  ✓  No duplicate timestamps per device.")
    else:
        print(f"  ⚠  {len(dupes_api)} duplicate (device_id, timestamp) rows:")
        print(dupes_api[['device_id', 'timestamp', 'bat']].to_string())

    sub("3k — API: implausible timestamps")
    future = api[api['timestamp'] > TODAY]
    early  = api[api['timestamp'] < STUDY_START]
    if future.empty and early.empty:
        print(f"  ✓  All API timestamps within [{STUDY_START.date()} → {TODAY.date()}].")
    if not future.empty:
        print(f"  ⚠  {len(future)} readings in the future:")
        print(future[['device_id', 'timestamp', 'bat']].to_string())
    if not early.empty:
        print(f"  ⚠  {len(early)} readings before study start:")
        print(early[['device_id', 'timestamp', 'bat']].to_string())


# ══════════════════════════════════════════════════════════════════════════════
# SECTION 4: BATTERY PERCENTAGE
# ══════════════════════════════════════════════════════════════════════════════

hdr("SECTION 4: BATTERY PERCENTAGE")

sub("4a — CSV: battery_percentage distribution")
bp_csv = pd.to_numeric(csv['battery_percentage'], errors='coerce')
print(qdesc(bp_csv, "%"))
print(f"  Nulls: {bp_csv.isna().sum()}  ({pct(bp_csv.isna().sum(), len(bp_csv))})")
print(f"  At 0%: {(bp_csv == 0).sum()}  |  At 100%: {(bp_csv == 100).sum()}")
impossible = ((bp_csv < 0) | (bp_csv > 100)).sum()
print(f"  Impossible values (<0 or >100): {impossible}")

sub("4b — CSV: per-participant battery stats")
print(f"  {'code':<25} {'min':>5} {'mean':>7} {'max':>5} {'n':>5}")
print(f"  {'-'*25} {'-'*5} {'-'*7} {'-'*5} {'-'*5}")
for code, grp in csv.groupby('participant_code'):
    bp = pd.to_numeric(grp['battery_percentage'], errors='coerce').dropna()
    if bp.empty: continue
    print(f"  {str(code):<25} {bp.min():>5.0f} {bp.mean():>7.1f} {bp.max():>5.0f} {len(bp):>5}")

if not api.empty:
    sub("4c — API: bat distribution")
    print(qdesc(api['bat'], "%"))
    print(f"  Nulls: {api['bat'].isna().sum()}")
    print(f"  At 0%: {(api['bat'] == 0).sum()}  |  At 100%: {(api['bat'] == 100).sum()}")
    impossible_api = ((api['bat'] < 0) | (api['bat'] > 100)).sum()
    print(f"  Impossible values: {impossible_api}")

    sub("4d — API: charging=1 vs charging=0 breakdown")
    ch1 = api[api['charging'] == 1]
    ch0 = api[api['charging'] == 0]
    print(f"  charging=1 (on charge): {len(ch1):>6}  ({pct(len(ch1), len(api))})")
    print(f"  charging=0 (off charge): {len(ch0):>5}  ({pct(len(ch0), len(api))})")
    print(f"\n  bat when charging=1: {qdesc(ch1['bat'], '%').strip()}")
    print(f"  bat when charging=0: {qdesc(ch0['bat'], '%').strip()}")

    sub("4e — API: per-device battery stats")
    print(f"  {'device/participant':<30} {'min':>5} {'mean':>7} {'max':>5} {'n':>6}")
    print(f"  {'-'*30} {'-'*5} {'-'*7} {'-'*5} {'-'*6}")
    for did, grp in api.groupby('device_id'):
        label = BY_DEVICE_ID.get(did, {}).get('participant_code') or did[:10] + '…'
        b = grp['bat'].dropna()
        print(f"  {str(label):<30} {b.min():>5.0f} {b.mean():>7.1f} {b.max():>5.0f} {len(b):>6}")

    sub("4f — API: bat=0 and charging=0 (dead watch still logging)")
    dead = api[(api['bat'] == 0) & (api['charging'] == 0)]
    print(f"  Count: {len(dead)}")
    if not dead.empty:
        print(dead[['device_id', 'timestamp', 'bat', 'charging']].to_string())

    sub("4g — API: bat=100 and charging=0 (implausible full battery without charge)")
    full_no_charge = api[(api['bat'] >= 100) & (api['charging'] == 0)]
    print(f"  Count: {len(full_no_charge)}")
    if not full_no_charge.empty:
        print(full_no_charge[['device_id', 'timestamp', 'bat', 'charging']].head(20).to_string())

    sub("4h — API: battery increases while not charging (per device)")
    print(f"  {'device/participant':<30} {'↑>1%':>6} {'↑>5%':>6} {'↑>10%':>7}")
    print(f"  {'-'*30} {'-'*6} {'-'*6} {'-'*7}")
    for did, grp in api.groupby('device_id'):
        g = grp.sort_values('timestamp')
        g_off = g[g['charging'] == 0].copy()
        if len(g_off) < 2: continue
        delta = g_off['bat'].diff()
        label = BY_DEVICE_ID.get(did, {}).get('participant_code') or did[:10] + '…'
        print(f"  {str(label):<30} {(delta > 1).sum():>6} {(delta > 5).sum():>6} {(delta > 10).sum():>7}")

    sub("4i — API: battery % when charging starts (last reading before charging=1 begins)")
    charge_starts = []
    for did, grp in api.groupby('device_id'):
        g = grp.sort_values('timestamp').reset_index(drop=True)
        for i in range(1, len(g)):
            if g.loc[i, 'charging'] == 1 and g.loc[i-1, 'charging'] == 0:
                charge_starts.append(g.loc[i-1, 'bat'])
    if charge_starts:
        s = pd.Series(charge_starts)
        print(f"  n={len(s)} charge-start events")
        print(f"  {qdesc(s, '%').strip()}")
    else:
        print("  (no charging transitions found)")

    sub("4j — API: battery % when charging stops (first reading after charging=1 → 0)")
    charge_ends = []
    for did, grp in api.groupby('device_id'):
        g = grp.sort_values('timestamp').reset_index(drop=True)
        for i in range(1, len(g)):
            if g.loc[i, 'charging'] == 0 and g.loc[i-1, 'charging'] == 1:
                charge_ends.append(g.loc[i, 'bat'])
    if charge_ends:
        s = pd.Series(charge_ends)
        print(f"  n={len(s)} charge-end events")
        print(f"  {qdesc(s, '%').strip()}")
    else:
        print("  (no charge-end transitions found)")


# ══════════════════════════════════════════════════════════════════════════════
# SECTION 5: DISCHARGE EPISODE ANALYSIS (API only)
# ══════════════════════════════════════════════════════════════════════════════

hdr("SECTION 5: DISCHARGE EPISODE ANALYSIS  (API only)")

if api.empty:
    print("  No API data available.")
else:
    all_episodes = []

    for did, grp in api.groupby('device_id'):
        g = grp.sort_values('timestamp').reset_index(drop=True)
        label = BY_DEVICE_ID.get(did, {}).get('participant_code') or did[:10] + '…'

        # find contiguous blocks of charging=0
        in_discharge = False
        seg_start = None

        for i in range(len(g)):
            is_off = (g.loc[i, 'charging'] == 0)
            if is_off and not in_discharge:
                in_discharge = True
                seg_start    = i
            elif (not is_off or i == len(g) - 1) and in_discharge:
                seg_end = i if not is_off else i + 1
                seg     = g.iloc[seg_start:seg_end]

                if len(seg) < 2:
                    in_discharge = False
                    seg_start    = None
                    continue

                start_ts   = seg['timestamp'].iloc[0]
                end_ts     = seg['timestamp'].iloc[-1]
                start_bat  = seg['bat'].iloc[0]
                end_bat    = seg['bat'].iloc[-1]
                duration_h = (end_ts - start_ts).total_seconds() / 3600
                drop_pct   = start_bat - end_bat
                n_readings = len(seg)

                gaps       = seg['timestamp'].diff().dt.total_seconds().dropna() / 3600
                max_gap    = gaps.max() if len(gaps) else 0
                mean_gap   = gaps.mean() if len(gaps) else 0
                bat_up     = (seg['bat'].diff() > 2).sum()

                # compute drain rate only if conditions met
                drain_rate = None
                if duration_h > 1 and max_gap < 2 and drop_pct > 0:
                    drain_rate = (drop_pct / duration_h) * 24

                flags = []
                if duration_h < 1:                  flags.append('short(<1h)')
                if max_gap > 2:                      flags.append('gap>2h')
                if bat_up > 0:                       flags.append(f'bat↑x{bat_up}')
                if n_readings < 5:                   flags.append('few_readings')

                era = get_era(start_ts)

                all_episodes.append({
                    'device_id':  did,
                    'label':      label,
                    'start_ts':   start_ts,
                    'end_ts':     end_ts,
                    'duration_h': duration_h,
                    'start_bat':  start_bat,
                    'end_bat':    end_bat,
                    'drop_pct':   drop_pct,
                    'n_readings': n_readings,
                    'mean_gap_h': mean_gap,
                    'max_gap_h':  max_gap,
                    'drain_rate': drain_rate,
                    'flags':      ', '.join(flags),
                    'clean':      len(flags) == 0,
                    'era':        era,
                })

                in_discharge = False
                seg_start    = None

    ep = pd.DataFrame(all_episodes)
    clean    = ep[ep['clean']]
    flagged  = ep[~ep['clean']]

    sub("5a — Episode count summary")
    print(f"  Total episodes:   {len(ep)}")
    print(f"  Clean:            {len(clean)}  ({pct(len(clean), len(ep))})")
    print(f"  Flagged:          {len(flagged)}  ({pct(len(flagged), len(ep))})")
    print()
    flag_reasons = pd.Series([f for fl in ep['flags'] for f in fl.split(', ') if f]).value_counts()
    print("  Flag breakdown:")
    for reason, cnt in flag_reasons.items():
        print(f"    {reason:<25} {cnt}")

    sub("5b — Episode duration distribution")
    print(f"  All:   {qdesc(ep['duration_h'], 'h').strip()}")
    print(f"  Clean: {qdesc(clean['duration_h'], 'h').strip()}")

    sub("5c — Drain rate distribution (clean episodes with computable rate)")
    clean_with_rate = clean.dropna(subset=['drain_rate'])
    print(f"  n={len(clean_with_rate)} clean episodes with drain rate")
    print(f"  {qdesc(clean_with_rate['drain_rate'], '%/day').strip()}")

    sub("5d — Episodes per device")
    print(f"  {'device/participant':<30} {'total':>6} {'clean':>6} {'flagged':>8} {'longest_clean(h)':>17}")
    print(f"  {'-'*30} {'-'*6} {'-'*6} {'-'*8} {'-'*17}")
    for label, grp in ep.groupby('label'):
        c = grp[grp['clean']]
        longest = c['duration_h'].max() if not c.empty else 0
        print(f"  {str(label):<30} {len(grp):>6} {len(c):>6} {len(grp)-len(c):>8} {longest:>17.1f}")

    sub("5e — Episodes per device per config era")
    if 'era' in ep.columns:
        era_tab = pd.crosstab(ep['label'], ep['era'])
        print(era_tab.to_string())

    sub("5f — All episodes detail (truncated to first 60 for readability)")
    disp = ep[['label', 'start_ts', 'duration_h', 'start_bat', 'end_bat',
               'drop_pct', 'n_readings', 'drain_rate', 'flags']].copy()
    disp['start_ts']   = disp['start_ts'].apply(fmt)
    disp['duration_h'] = disp['duration_h'].round(1)
    disp['drain_rate'] = disp['drain_rate'].round(1)
    with pd.option_context('display.max_rows', 60, 'display.width', 200, 'display.max_colwidth', 40):
        print(disp.head(60).to_string(index=False))
    if len(disp) > 60:
        print(f"  … and {len(disp)-60} more episodes (not shown)")


# ══════════════════════════════════════════════════════════════════════════════
# SECTION 6: SENSOR / CONFIGURATION FLAGS  (CSV only)
# ══════════════════════════════════════════════════════════════════════════════

hdr("SECTION 6: SENSOR / CONFIGURATION FLAGS  (CSV only)")

present_bool = [c for c in BOOL_COLS if c in csv.columns]

sub("6a — Boolean sensor columns: True / False / null counts")
print(f"  {'column':<30} {'True':>6} {'False':>6} {'null':>6}")
print(f"  {'-'*30} {'-'*6} {'-'*6} {'-'*6}")
for col in present_bool:
    t = (csv[col] == True).sum()
    f = (csv[col] == False).sum()
    n = csv[col].isna().sum()
    print(f"  {col:<30} {t:>6} {f:>6} {n:>6}")

sub("6b — Per config_name consistency of each boolean sensor")
print("  Flags: MIXED = same sensor has both True and False values for some participant in this era")
print()
inconsistent_found = False
for cfg in csv['config_name'].unique():
    sub_csv = csv[csv['config_name'] == cfg]
    issues = []
    for col in present_bool:
        for pc, pc_grp in sub_csv.groupby('participant_code'):
            vals = pc_grp[col].dropna().unique()
            if len(vals) > 1:
                issues.append(f"{col}@{pc}")
    if issues:
        inconsistent_found = True
        print(f"  ⚠  {cfg}: MIXED in {issues}")
    else:
        print(f"  ✓  {cfg}: all sensors consistent within each participant")

sub("6c — spo2 value counts")
for v, cnt in csv['spo2'].value_counts(dropna=False).items():
    print(f"  {str(v):<20} {cnt}")

print()
print("  spo2 mode per config_name:")
spo2_cfg = pd.crosstab(csv['config_name'], csv['spo2'])
print(spo2_cfg.to_string())

sub("6d — always_on_display value counts")
if 'always_on_display' in csv.columns:
    for v, cnt in csv['always_on_display'].value_counts(dropna=False).items():
        print(f"  {str(v):<10} {cnt}")
    print()
    aod_cfg = pd.crosstab(csv['config_name'], csv['always_on_display'])
    print("  always_on_display per config_name:")
    print(aod_cfg.to_string())

sub("6e — Configuration fingerprints (unique sensor flag combinations)")
sensor_cols_for_fp = present_bool + (['spo2', 'always_on_display']
                                      if 'spo2' in csv.columns and 'always_on_display' in csv.columns
                                      else [])
sensor_cols_for_fp = [c for c in sensor_cols_for_fp if c in csv.columns]
fps = csv[sensor_cols_for_fp].astype(str).apply(tuple, axis=1).value_counts()
print(f"  Unique fingerprints: {len(fps)}")
print(f"  {'count':>6}  fingerprint")
for fp, cnt in fps.items():
    fp_str = '  '.join(f"{c}={v}" for c, v in zip(sensor_cols_for_fp, fp))
    print(f"  {cnt:>6}  {fp_str}")


# ══════════════════════════════════════════════════════════════════════════════
# SECTION 7: LINKAGE QUALITY
# ══════════════════════════════════════════════════════════════════════════════

hdr("SECTION 7: LINKAGE QUALITY")

csv_codes_set = set(csv['participant_code'].dropna().unique())
api_dids_set  = set(api['device_id'].unique()) if not api.empty else set()

# Build forward and reverse maps from metadata
code_to_did = {p['participant_code']: p['device_id']
               for p in PARTICIPANTS
               if p['participant_code'] and p['device_id']}
did_to_code = {p['device_id']: p['participant_code']
               for p in PARTICIPANTS
               if p['device_id'] and p['participant_code']}

matched_codes      = {c for c in csv_codes_set if code_to_did.get(c) in api_dids_set}
csv_only_codes     = csv_codes_set - matched_codes
api_only_dids      = api_dids_set - set(code_to_did.values())

sub("7a — Summary")
print(f"  participant_codes in CSV:          {len(csv_codes_set)}")
print(f"  device_ids in API:                 {len(api_dids_set)}")
print(f"  Matched (code + device_id both):   {len(matched_codes)}")
print(f"  CSV-only (no API device_id):       {len(csv_only_codes)}")
print(f"  API-only (no CSV match):           {len(api_only_dids)}")

sub("7b — Matched participants: timestamp overlap")
print(f"  {'code':<25} {'csv_start':<18} {'csv_end':<18} {'api_start':<18} {'api_end':<18} {'overlap?'}")
print(f"  {'-'*25} {'-'*18} {'-'*18} {'-'*18} {'-'*18} {'-'*8}")
for code in sorted(matched_codes):
    did      = code_to_did[code]
    csv_grp  = csv[csv['participant_code'] == code]['timestamp']
    api_grp  = api[api['device_id'] == did]['timestamp'] if not api.empty else pd.Series([], dtype='datetime64[ns]')
    if csv_grp.empty or api_grp.empty:
        print(f"  {str(code):<25} (no data on one side)")
        continue
    c1, c2 = csv_grp.min(), csv_grp.max()
    a1, a2 = api_grp.min(), api_grp.max()
    overlap = max(c1, a1) <= min(c2, a2)
    print(f"  {str(code):<25} {fmt(c1):<18} {fmt(c2):<18} {fmt(a1):<18} {fmt(a2):<18} {'✓' if overlap else '⚠ NO'}")

sub("7c — CSV-only participant codes (no device_id in API)")
if csv_only_codes:
    for c in sorted(csv_only_codes):
        cnt = (csv['participant_code'] == c).sum()
        did = code_to_did.get(c, '(not in metadata)')
        print(f"  {str(c):<28}  readings={cnt}  mapped_device_id={did}")
else:
    print("  (none)")

sub("7d — API-only device_ids (no CSV participant_code match)")
if api_only_dids:
    for did in sorted(api_only_dids):
        cnt     = (api['device_id'] == did).sum() if not api.empty else 0
        model   = BY_DEVICE_ID.get(did, {}).get('watch_model', '—')
        name    = BY_DEVICE_ID.get(did, {}).get('participant_name', '—')
        print(f"  {did}  readings={cnt}  model={model}  name={name}")
else:
    print("  (none)")

sub("7e — Device model consistency: CSV vs API part_number")
if not api.empty:
    print(f"  {'code':<25} {'csv_model':<20} {'api_part_number':<22} {'api_model':<20} {'match?'}")
    print(f"  {'-'*25} {'-'*20} {'-'*22} {'-'*20} {'-'*6}")
    for code in sorted(matched_codes):
        did = code_to_did[code]
        csv_models = csv[csv['participant_code'] == code]['device_model'].unique()
        api_pns    = api[api['device_id'] == did]['part_number'].unique()
        for csv_m in csv_models:
            for pn in api_pns:
                api_m  = PART_NUMBER_MODELS.get(pn, '(unknown)')
                match  = '✓' if str(csv_m).lower() == str(api_m).lower() else '⚠'
                print(f"  {str(code):<25} {str(csv_m):<20} {str(pn):<22} {str(api_m):<20} {match}")

sub("7f — Participant codes linked to multiple device_ids (device swap candidates)")
code_multi_device = {}
for p in PARTICIPANTS:
    code = p.get('participant_code')
    did  = p.get('device_id')
    if code and did:
        code_multi_device.setdefault(code, []).append(did)
found = {c: ds for c, ds in code_multi_device.items() if len(ds) > 1}
if found:
    for c, ds in found.items():
        print(f"  ⚠  {c} → {ds}")
else:
    print("  ✓  No participant_code maps to multiple device_ids in metadata.")

sub("7g — Device IDs linked to multiple participant codes (reassignment candidates)")
did_multi_code = {}
for p in PARTICIPANTS:
    code = p.get('participant_code')
    did  = p.get('device_id')
    if code and did:
        did_multi_code.setdefault(did, []).append(code)
found = {d: cs for d, cs in did_multi_code.items() if len(cs) > 1}
if found:
    for d, cs in found.items():
        print(f"  ⚠  {d[:20]}… → {cs}")
else:
    print("  ✓  No device_id maps to multiple participant_codes in metadata.")


# ══════════════════════════════════════════════════════════════════════════════
# SECTION 8: ANOMALIES AND DATA QUALITY FLAGS
# ══════════════════════════════════════════════════════════════════════════════

hdr("SECTION 8: ANOMALIES AND DATA QUALITY FLAGS")

sub("8a — CSV rows with any null values")
null_rows = csv[csv.isnull().any(axis=1)]
print(f"  Rows with ≥1 null: {len(null_rows)}  ({pct(len(null_rows), len(csv))})")
null_by_col = csv.isnull().sum()
null_by_col = null_by_col[null_by_col > 0]
if not null_by_col.empty:
    print("  Null counts by column:")
    for col, cnt in null_by_col.items():
        affected = csv[csv[col].isnull()]['participant_code'].unique()
        print(f"    {col:<30} {cnt:>4}  participants: {list(affected)}")

if not api.empty:
    sub("8b — API: readings with null bat or ts")
    null_bat = api['bat'].isna().sum()
    null_ts  = api['ts'].isna().sum()
    print(f"  null bat: {null_bat}  |  null ts: {null_ts}")

sub("8c — API: devices with very long mid-study gaps (>48h)")
if not api.empty:
    found_any = False
    for did, grp in api.groupby('device_id'):
        g = grp.sort_values('timestamp').reset_index(drop=True)
        gaps = g['timestamp'].diff().dt.total_seconds() / 3600
        big = gaps[gaps > 48]
        if big.empty: continue
        found_any = True
        label = BY_DEVICE_ID.get(did, {}).get('participant_code') or did[:10] + '…'
        for idx in big.index:
            gap_start = fmt(g.loc[idx-1, 'timestamp']) if idx > 0 else '—'
            gap_end   = fmt(g.loc[idx, 'timestamp'])
            print(f"  ⚠  {label:<25} {big[idx]:.0f}h gap:  {gap_start} → {gap_end}")
    if not found_any:
        print("  ✓  No mid-study gaps >48h found.")

sub("8d — CSV: implausible battery jumps between consecutive readings (>50% change)")
jumps_found = False
for code, grp in csv.groupby('participant_code'):
    g = grp.sort_values('timestamp')
    bp = pd.to_numeric(g['battery_percentage'], errors='coerce')
    delta = bp.diff().abs()
    big = delta[delta > 50]
    for idx in big.index:
        jumps_found = True
        prev_bp = bp.iloc[g.index.get_loc(idx) - 1] if g.index.get_loc(idx) > 0 else None
        print(f"  ⚠  {code:<25}  Δ{big[idx]:.0f}%  at {fmt(g.loc[idx,'timestamp'])}"
              f"  ({prev_bp:.0f}% → {bp[idx]:.0f}%)")
if not jumps_found:
    print("  ✓  No jumps >50% found.")

sub("8e — CSV: config era transitions per participant")
print("  (shows exact timestamp when config_name changed per participant)")
for code, grp in csv.sort_values('timestamp').groupby('participant_code'):
    g = grp.sort_values('timestamp').reset_index(drop=True)
    transitions = []
    for i in range(1, len(g)):
        if g.loc[i, 'config_name'] != g.loc[i-1, 'config_name']:
            transitions.append(
                f"{g.loc[i-1,'config_name']} → {g.loc[i,'config_name']}  "
                f"at {fmt(g.loc[i,'timestamp'])}"
            )
    if transitions:
        print(f"\n  {code}:")
        for t in transitions:
            print(f"    {t}")
    else:
        cfg_name = g['config_name'].iloc[0] if len(g) else '—'
        print(f"  {str(code):<30}  (single era throughout: {cfg_name})")

sub("8f — Devices with very few total readings (<10)")
if not api.empty:
    low = api['device_id'].value_counts()
    low = low[low < 10]
    if low.empty:
        print("  ✓  All devices have ≥10 readings.")
    else:
        for did, cnt in low.items():
            label = BY_DEVICE_ID.get(did, {}).get('participant_code') or did[:10] + '…'
            print(f"  ⚠  {label:<30}  {cnt} readings")

sub("8g — API: devices with implausibly long continuous charging (>6h)")
if not api.empty:
    for did, grp in api.groupby('device_id'):
        g = grp.sort_values('timestamp').reset_index(drop=True)
        label = BY_DEVICE_ID.get(did, {}).get('participant_code') or did[:10] + '…'
        in_charge = False
        charge_start = None
        for i in range(len(g)):
            if g.loc[i, 'charging'] == 1 and not in_charge:
                in_charge    = True
                charge_start = g.loc[i, 'timestamp']
            elif g.loc[i, 'charging'] == 0 and in_charge:
                dur = (g.loc[i, 'timestamp'] - charge_start).total_seconds() / 3600
                if dur > 6:
                    print(f"  ⚠  {label:<25}  {dur:.1f}h charging  {fmt(charge_start)} → {fmt(g.loc[i,'timestamp'])}")
                in_charge = False

# ── FINAL SUMMARY TABLE ───────────────────────────────────────────────────────

hdr("FINAL SUMMARY TABLE")

print("  Building per-participant/device rollup …\n")

all_keys = sorted(set(list(csv_codes_set) + [
    BY_DEVICE_ID.get(d, {}).get('participant_code') or d[:10] + '…'
    for d in api_dids_set
]))

summary_rows = []
for key in all_keys:
    # CSV side
    csv_grp = csv[csv['participant_code'] == key]
    csv_n   = len(csv_grp)
    csv_range = (f"{fmt(csv_grp['timestamp'].min())} – {fmt(csv_grp['timestamp'].max())}"
                 if csv_n else "—")

    # API side
    did = code_to_did.get(key)
    if did and not api.empty:
        api_grp  = api[api['device_id'] == did]
        api_n    = len(api_grp)
        api_span = (api_grp['timestamp'].max() - api_grp['timestamp'].min()).total_seconds() / 86400 if api_n > 1 else 0
        expected = int(api_span * 24 * 60 / 5) + 1 if api_span > 0 else 0
        completeness = pct(api_n, expected)
    else:
        api_n        = 0
        api_span     = 0
        completeness = "—"

    # Discharge episodes
    if 'ep' in dir() and not ep.empty and did:
        dev_ep   = ep[ep['device_id'] == did]
        n_ep     = len(dev_ep)
        clean_ep = dev_ep[dev_ep['clean']] if not dev_ep.empty else dev_ep
        rates    = clean_ep['drain_rate'].dropna() if not clean_ep.empty else pd.Series([], dtype=float)
        mean_drain = f"{rates.mean():.1f}" if not rates.empty else "—"
        n_flags  = len(dev_ep) - len(clean_ep)
    else:
        n_ep = 0; mean_drain = "—"; n_flags = 0

    summary_rows.append({
        'Participant': key,
        'CSV_n':       csv_n,
        'API_n':       api_n,
        'API_complete': completeness,
        'Episodes':    n_ep,
        'Mean_%/day':  mean_drain,
        'Flagged_ep':  n_flags,
    })

df_summary = pd.DataFrame(summary_rows)
print(df_summary.to_string(index=False))

print(f"\n{SEP}")
print("  AUDIT COMPLETE")
print(SEP)
print(f"  Generated: {pd.Timestamp.now().strftime('%Y-%m-%d %H:%M:%S')}")
print(f"  CSV rows: {len(csv)}  |  API rows: {len(api)}")
print(SEP)

# ── close output file ─────────────────────────────────────────────────────────
sys.stdout = sys.__stdout__
_out_file.close()
print(f"\nOutput saved to: {_OUT_PATH}")
