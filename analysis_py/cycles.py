import pandas as pd
from config import CONFIG_SORTED, ERA_COLORS, ERA_MARKERS


def get_era(timestamp):
    """Return the config era a timestamp falls in."""
    era = 'Pre SpO2'
    for name, ts in CONFIG_SORTED:
        if timestamp >= ts:
            era = f'Post {name}'
    return era


def _participant_key(row):
    """Return participant_code if available, else truncated device_id."""
    if pd.notna(row.get('participant_code')):
        return row['participant_code']
    did = row.get('device_id')
    return (str(did)[:8] + '…') if pd.notna(did) else 'unknown'


def _make_cycle(seg, participant_key, cycle_idx):
    """Compute cycle stats from a discharge segment DataFrame."""
    start_bp  = seg['bat'].iloc[0]
    end_bp    = seg['bat'].iloc[-1]
    start_ts  = seg['timestamp'].iloc[0]
    end_ts    = seg['timestamp'].iloc[-1]
    delta_pct = start_bp - end_bp
    delta_hrs = (end_ts - start_ts).total_seconds() / 3600

    if delta_hrs == 0 or delta_pct <= 0:
        return None

    daily_rate_raw = (delta_pct / delta_hrs) * 24
    if daily_rate_raw > 0 and (100 / daily_rate_raw) > 10:
        return None

    eras = [get_era(t) for t in seg['timestamp']]
    era  = max(set(eras), key=eras.count)

    return {
        'participant_key': participant_key,
        'cycle_idx':       cycle_idx,
        'start_bp':        start_bp,
        'end_bp':          end_bp,
        'start_ts':        start_ts,
        'end_ts':          end_ts,
        'delta_pct':       delta_pct,
        'delta_hrs':       round(delta_hrs, 1),
        'hourly_rate':     round(delta_pct / delta_hrs, 2),
        'daily_rate':      round((delta_pct / delta_hrs) * 24, 1),
        'era':             era,
        'cycle_data':      seg,
    }


def extract_cycles(data):
    """
    Extract discharge cycles, splitting at config change events and charge events.
    Groups by participant_code (falling back to device_id[:8]).
    Returns list of cycle dicts.
    """
    all_cycles = []
    config_timestamps = [ts for _, ts in CONFIG_SORTED]

    # Build grouping key column
    data = data.copy()
    data['_pkey'] = data.apply(_participant_key, axis=1)

    for pkey in data['_pkey'].unique():
        participant_data = (data[data['_pkey'] == pkey]
                            .sort_values('timestamp').reset_index(drop=True))
        bp = participant_data['bat']
        ts = participant_data['timestamp']

        # Find where config events fall between consecutive points
        split_indices = set()
        for config_ts in config_timestamps:
            for i in range(1, len(participant_data)):
                if ts.iloc[i - 1] < config_ts <= ts.iloc[i]:
                    split_indices.add(i)
                    break

        boundaries = sorted({0} | split_indices)
        boundaries.append(len(participant_data))

        cycle_idx = 1
        for b in range(len(boundaries) - 1):
            segment = participant_data.iloc[boundaries[b]:boundaries[b + 1]].reset_index(drop=True)
            if len(segment) < 2:
                continue

            seg_bp    = segment['bat']
            sub_start = 0
            for i in range(1, len(segment)):
                if seg_bp.iloc[i] > seg_bp.iloc[i - 1]:
                    sub_seg = segment.iloc[sub_start:i].reset_index(drop=True)
                    if len(sub_seg) >= 2:
                        c = _make_cycle(sub_seg, pkey, cycle_idx)
                        if c:
                            all_cycles.append(c)
                            cycle_idx += 1
                    sub_start = i
            sub_seg = segment.iloc[sub_start:].reset_index(drop=True)
            if len(sub_seg) >= 2:
                c = _make_cycle(sub_seg, pkey, cycle_idx)
                if c:
                    all_cycles.append(c)
                    cycle_idx += 1

    print(f"✓ {len(all_cycles)} cycles across {len(set(c['participant_key'] for c in all_cycles))} participant(s)")
    for era in ERA_COLORS:
        n = sum(1 for c in all_cycles if c['era'] == era)
        if n:
            print(f"  {ERA_MARKERS.get(era, '?')} {era}: {n} cycles")
    return all_cycles
