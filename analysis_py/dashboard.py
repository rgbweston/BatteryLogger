"""
dashboard.py — Per-device battery analysis dashboard.

Outputs an HTML page with:
  - Model-level battery life summary (top)
  - Active / inactive device status table
  - Per-device sections: battery life (3 methods), discharge episodes,
    charging behaviour, firmware versions, days-of-week logging activity

Usage:
    python dashboard.py
    python dashboard.py --from-date 2026-03-01
    python dashboard.py --days 30

API:
    from dashboard import generate_dashboard
    generate_dashboard(data, save_path='dashboard.html')
"""

import argparse
import datetime
import subprocess
import numpy as np
import pandas as pd

from load import load_all
from metadata import BY_DEVICE_ID, PART_NUMBER_MODELS
from exclusion_list import (
    EXCLUDED_PARTICIPANT_CODES,
    EXCLUDED_DEVICE_IDS,
    SDK_WINDOWS,
    MIN_CYCLE_DURATION_HOURS,
    MAX_DRAIN_PERCENT_PER_DAY,
    MIN_CYCLE_DROP_PERCENT,
)

SIMULATOR_DEVICE_PREFIXES = ['b45b27']
ACTIVE_THRESHOLD_DAYS = 7
DAYS = ['Mon', 'Tue', 'Wed', 'Thu', 'Fri', 'Sat', 'Sun']

MODEL_COLORS = {
    'Vivoactive 5': '#1f77b4',
    'Vivoactive 6': '#ff7f0e',
    'Venu 3S':      '#2ca02c',
    'Venu 4 41mm':  '#d62728',
    'Venu 4 45mm':  '#9467bd',
    'Venu 4':       '#8c564b',
}
DEFAULT_COLOR = '#aaaaaa'

_BAD_FIRMWARE = {'unknown', 'none', 'null', ''}


def _model_color(model):
    return MODEL_COLORS.get(str(model).strip(), DEFAULT_COLOR)


def _utcnow():
    """Return current UTC time as a timezone-naive Timestamp (matches stored data)."""
    return pd.Timestamp(datetime.datetime.now(datetime.timezone.utc).replace(tzinfo=None))


# ── Exclusions ────────────────────────────────────────────────────────────────

def _apply_exclusions(data):
    mask = (
        data['participant_code'].isin(EXCLUDED_PARTICIPANT_CODES) |
        data['device_id'].isin(EXCLUDED_DEVICE_IDS)
    )
    data = data[~mask].reset_index(drop=True)

    drop_idx = set()
    for key, window in SDK_WINDOWS.items():
        match = (data['participant_code'] == key) | (data['device_id'] == key)
        idx = data[match].index
        if window['from_ts'] is not None:
            drop_idx.update(idx[data.loc[idx, 'timestamp'] < window['from_ts']].tolist())
        if window['to_ts'] is not None:
            drop_idx.update(idx[data.loc[idx, 'timestamp'] >= window['to_ts']].tolist())

    if drop_idx:
        data = data.drop(index=drop_idx).reset_index(drop=True)
    return data


def _is_suppressed(device_id):
    if pd.isna(device_id) or str(device_id) == 'unknown':
        return True
    if device_id in EXCLUDED_DEVICE_IDS:
        return True
    return any(str(device_id).startswith(p) for p in SIMULATOR_DEVICE_PREFIXES)


# ── Discharge episode extraction ──────────────────────────────────────────────

def _make_episode(seg):
    start_bat = seg['bat'].iloc[0]
    end_bat   = seg['bat'].iloc[-1]
    start_ts  = seg['timestamp'].iloc[0]
    end_ts    = seg['timestamp'].iloc[-1]
    drop_pct  = start_bat - end_bat
    delta_h   = (end_ts - start_ts).total_seconds() / 3600

    if delta_h <= 0 or drop_pct <= 0:
        return None

    drain_per_day = drop_pct / delta_h * 24
    clean = (
        delta_h >= MIN_CYCLE_DURATION_HOURS and
        drain_per_day <= MAX_DRAIN_PERCENT_PER_DAY and
        drop_pct >= MIN_CYCLE_DROP_PERCENT
    )
    return {
        'start_ts':      start_ts,
        'end_ts':        end_ts,
        'start_bat':     round(start_bat, 1),
        'end_bat':       round(end_bat, 1),
        'drop_pct':      round(drop_pct, 1),
        'delta_h':       round(delta_h, 1),
        'drain_per_day': round(drain_per_day, 1),
        'clean':         clean,
    }


def _discharge_episodes(dev_df):
    """Consecutive sequences where charging == 0 (API data only)."""
    api = dev_df[dev_df['data_source'] == 'api'].copy()
    if api.empty:
        return []

    api = (api[api['charging'].isin([0, 1])]
           .sort_values('timestamp')
           .reset_index(drop=True))
    if len(api) < 2:
        return []

    episodes  = []
    in_seg    = api['charging'].iloc[0] == 0
    seg_start = 0

    for i in range(1, len(api)):
        c = api['charging'].iloc[i]
        if c == 0 and not in_seg:
            seg_start = i
            in_seg    = True
        elif c == 1 and in_seg:
            seg = api.iloc[seg_start:i].reset_index(drop=True)
            if len(seg) >= 2:
                ep = _make_episode(seg)
                if ep:
                    episodes.append(ep)
            in_seg = False

    if in_seg:
        seg = api.iloc[seg_start:].reset_index(drop=True)
        if len(seg) >= 2:
            ep = _make_episode(seg)
            if ep:
                episodes.append(ep)

    return episodes


# ── Battery life estimates ────────────────────────────────────────────────────

def _battery_life_option1(episodes):
    """100 / drain_rate_per_day per clean episode → median."""
    clean = [e for e in episodes if e['clean'] and e['drain_per_day'] > 0]
    if not clean:
        return None
    days = [100 / e['drain_per_day'] for e in clean]
    return {'days': round(float(np.median(days)), 1), 'n': len(clean)}


def _battery_life_option2(dev_df):
    """Extrapolated days from unplug → next plug-in boundary."""
    api = dev_df[dev_df['data_source'] == 'api'].copy()
    if api.empty:
        return None

    api = (api[api['charging'].isin([0, 1])]
           .sort_values('timestamp')
           .reset_index(drop=True))
    if len(api) < 2:
        return None

    transitions = []
    for i in range(1, len(api)):
        prev_c = api['charging'].iloc[i - 1]
        curr_c = api['charging'].iloc[i]
        ts  = api['timestamp'].iloc[i]
        bat = api['bat'].iloc[i]
        if prev_c == 1 and curr_c == 0:
            transitions.append(('unplug', ts, bat))
        elif prev_c == 0 and curr_c == 1:
            transitions.append(('plugin', ts, bat))

    cycles = []
    i = 0
    while i < len(transitions):
        if transitions[i][0] == 'unplug':
            j = i + 1
            while j < len(transitions) and transitions[j][0] != 'plugin':
                j += 1
            if j < len(transitions):
                _, unplug_ts, unplug_bat = transitions[i]
                _, plugin_ts, plugin_bat  = transitions[j]
                delta_h = (plugin_ts - unplug_ts).total_seconds() / 3600
                drop    = unplug_bat - plugin_bat
                if delta_h > 0 and drop > 5:
                    rate = drop / delta_h * 24
                    if 0 < rate <= MAX_DRAIN_PERCENT_PER_DAY:
                        cycles.append(round(100 / rate, 1))
                i = j
        i += 1

    if not cycles:
        return None
    return {'days': round(float(np.median(cycles)), 1), 'n': len(cycles)}


def _battery_life_option3(episodes):
    """100 / weighted-average drain rate across all clean episodes."""
    clean = [e for e in episodes if e['clean']]
    if not clean:
        return None
    total_drop = sum(e['drop_pct'] for e in clean)
    total_h    = sum(e['delta_h']  for e in clean)
    if total_h <= 0:
        return None
    mean_rate = total_drop / total_h * 24
    if mean_rate <= 0:
        return None
    return {'days': round(100 / mean_rate, 1), 'mean_rate': round(mean_rate, 1), 'n': len(clean)}


# ── Charging behaviour ────────────────────────────────────────────────────────

def _charging_behaviour(dev_df):
    """Time-of-day and battery % at charge-start (0→1) and charge-end (1→0)."""
    api = dev_df[dev_df['data_source'] == 'api'].copy()
    if api.empty:
        return None

    api = (api[api['charging'].isin([0, 1])]
           .sort_values('timestamp')
           .reset_index(drop=True))
    if len(api) < 2:
        return None

    starts, ends = [], []
    for i in range(1, len(api)):
        prev_c = api['charging'].iloc[i - 1]
        curr_c = api['charging'].iloc[i]
        ts  = api['timestamp'].iloc[i]
        bat = api['bat'].iloc[i]
        tod = ts.hour + ts.minute / 60
        if prev_c == 0 and curr_c == 1:
            starts.append({'tod': tod, 'bat': bat})
        elif prev_c == 1 and curr_c == 0:
            ends.append({'tod': tod, 'bat': bat})

    if not starts and not ends:
        return None

    def _stats(events, label):
        if not events:
            return None
        bats = [e['bat'] for e in events]
        tods = [e['tod'] for e in events]
        med  = float(np.median(tods))
        h, m = int(med), int((med % 1) * 60)
        return {
            'label':       label,
            'n':           len(events),
            'median_time': f'{h:02d}:{m:02d}',
            'median_bat':  round(float(np.median(bats)), 1),
            'mean_bat':    round(float(np.mean(bats)), 1),
        }

    return {
        'charge_start': _stats(starts, 'Plug in (start charging)'),
        'charge_end':   _stats(ends,   'Unplug (stop charging)'),
    }


# ── Days-of-week ──────────────────────────────────────────────────────────────

def _days_of_week(dev_df):
    counts = [0] * 7
    for ts in dev_df['timestamp']:
        counts[ts.dayofweek] += 1
    return counts


# ── HTML helpers ──────────────────────────────────────────────────────────────

def _mini_bar(value, max_val, width=100):
    pct = int(value / max_val * width) if max_val else 0
    return (f'<div style="display:inline-block;width:{pct}px;height:12px;'
            f'background:#1f77b4;vertical-align:middle;border-radius:2px"></div>')


def _days_html(counts):
    max_c = max(counts) if any(counts) else 1
    rows = ''
    for day, cnt in zip(DAYS, counts):
        rows += (f'<tr>'
                 f'<td style="width:36px;font-size:12px;color:#555">{day}</td>'
                 f'<td>{_mini_bar(cnt, max_c)}</td>'
                 f'<td style="font-size:12px;color:#666;padding-left:8px">{cnt}</td>'
                 f'</tr>')
    return f'<table style="border:none;margin:0;width:auto">{rows}</table>'


def _battery_life_html(opt1, opt2, opt3):
    def _row(label, result):
        if result:
            return (f'<tr><td>{label}</td>'
                    f'<td style="text-align:right"><strong>{result["days"]}</strong> days</td>'
                    f'<td style="color:#888;font-size:12px">n={result["n"]} cycles</td>'
                    f'</tr>\n')
        return (f'<tr><td>{label}</td>'
                f'<td colspan="2" style="color:#bbb">—</td></tr>\n')

    rows = (
        _row('Direct from clean discharge cycles', opt1) +
        _row('From charge cycle boundaries',       opt2) +
        _row('Normalised drain rate',              opt3)
    )
    return (f'<table>'
            f'<thead><tr><th>Method</th>'
            f'<th style="text-align:right;width:90px">Estimate</th>'
            f'<th>Notes</th></tr></thead>'
            f'<tbody>{rows}</tbody></table>')


def _episodes_html(episodes):
    if not episodes:
        return ('<p style="color:#aaa;font-size:12px">'
                'No discharge episodes detected (requires API data with charging field).</p>')

    n_clean   = sum(1 for e in episodes if e['clean'])
    n_flagged = len(episodes) - n_clean
    total_h   = sum(e['delta_h'] for e in episodes if e['clean'])
    avg_h     = total_h / n_clean if n_clean else 0.0

    rows = ''
    for ep in sorted(episodes, key=lambda e: e['start_ts']):
        flag = ('' if ep['clean']
                else '&thinsp;<span style="color:#e65100;font-size:10px">⚑</span>')
        rows += (
            f'<tr>'
            f'<td style="font-size:11px;color:#666">{ep["start_ts"]:%d %b %H:%M}</td>'
            f'<td style="font-size:11px;color:#666">{ep["end_ts"]:%d %b %H:%M}</td>'
            f'<td style="text-align:right">{ep["delta_h"]:.1f}</td>'
            f'<td style="text-align:right">{ep["start_bat"]:.0f}% → {ep["end_bat"]:.0f}%</td>'
            f'<td style="text-align:right">{ep["drop_pct"]:.0f}%</td>'
            f'<td style="text-align:right">{ep["drain_per_day"]:.1f}{flag}</td>'
            f'</tr>\n'
        )

    summary = (f'{len(episodes)} cycles &nbsp;·&nbsp; '
               f'{n_clean} clean, {n_flagged} flagged &nbsp;·&nbsp; '
               f'{total_h:.1f} total discharge hours &nbsp;·&nbsp; '
               f'{avg_h:.1f} h avg (clean)')

    return f'''<p style="font-size:12px;color:#666;margin-bottom:6px">{summary}</p>
<div style="max-height:220px;overflow-y:auto">
<table style="font-size:12px">
  <thead>
    <tr>
      <th>Start</th><th>End</th>
      <th style="text-align:right">Hours</th>
      <th style="text-align:right">Range</th>
      <th style="text-align:right">Drop</th>
      <th style="text-align:right">%/day</th>
    </tr>
  </thead>
  <tbody>{rows}</tbody>
</table>
</div>'''


def _charging_html(chg):
    if not chg:
        return '<p style="color:#aaa;font-size:12px">No charging transitions detected.</p>'

    rows = ''
    for key in ('charge_end', 'charge_start'):
        s = chg.get(key)
        if not s:
            continue
        rows += (f'<tr>'
                 f'<td>{s["label"]}</td>'
                 f'<td style="text-align:right">{s["median_time"]}</td>'
                 f'<td style="text-align:right">{s["median_bat"]}%</td>'
                 f'<td style="color:#888;font-size:12px">'
                 f'n={s["n"]}  ·  mean {s["mean_bat"]}%</td>'
                 f'</tr>\n')

    return (f'<table><thead>'
            f'<tr><th>Event</th>'
            f'<th style="text-align:right">Median time</th>'
            f'<th style="text-align:right">Median bat%</th>'
            f'<th>Notes</th></tr>'
            f'</thead><tbody>{rows}</tbody></table>')


# ── Model-level summary ───────────────────────────────────────────────────────

def _model_summary_html(device_analyses, summaries):
    """Top-level table: median battery life estimates grouped by watch model."""
    model_data = {}
    for s in summaries:
        model = str(s['model'])
        an    = device_analyses[s['device_id']]
        md    = model_data.setdefault(model, {'opt1': [], 'opt2': [], 'opt3': [], 'n': 0})
        md['n'] += 1
        if an['opt1']:
            md['opt1'].append(an['opt1']['days'])
        if an['opt2']:
            md['opt2'].append(an['opt2']['days'])
        if an['opt3']:
            md['opt3'].append(an['opt3']['days'])

    def _fmt(vals):
        if not vals:
            return '—'
        return f'{round(float(np.median(vals)), 1)} d'

    rows = ''
    for model in sorted(model_data.keys()):
        md    = model_data[model]
        color = _model_color(model)
        dot   = f'<span style="color:{color};font-size:16px">●</span>'
        rows += (f'<tr>'
                 f'<td>{dot} {model}</td>'
                 f'<td style="text-align:right">{_fmt(md["opt1"])}</td>'
                 f'<td style="text-align:right">{_fmt(md["opt2"])}</td>'
                 f'<td style="text-align:right">{_fmt(md["opt3"])}</td>'
                 f'<td style="text-align:right;color:#888">{md["n"]}</td>'
                 f'</tr>')

    return (f'<table>'
            f'<thead><tr>'
            f'<th>Model</th>'
            f'<th style="text-align:right">Direct (clean cycles)</th>'
            f'<th style="text-align:right">Charge boundaries</th>'
            f'<th style="text-align:right">Normalised drain rate</th>'
            f'<th style="text-align:right">Devices</th>'
            f'</tr></thead>'
            f'<tbody>{rows}</tbody></table>')


# ── Per-device section ────────────────────────────────────────────────────────

def _firmware_str(dev_df):
    if 'firmware_version' not in dev_df.columns:
        return '—'
    fws = [str(f) for f in dev_df['firmware_version'].dropna().unique()
           if str(f).strip().lower() not in _BAD_FIRMWARE]
    return ', '.join(sorted(fws)) if fws else '—'


def _device_section_html(device_id, dev_df, is_active, analysis):
    meta  = BY_DEVICE_ID.get(device_id, {})
    model = (dev_df['watch_model'].dropna().iloc[0]
             if dev_df['watch_model'].notna().any()
             else (meta.get('watch_model') or '—'))

    fw_str   = _firmware_str(dev_df)
    n        = len(dev_df)
    n_cycles = len([e for e in analysis['episodes'] if e['clean']])
    date_range = (f"{dev_df['timestamp'].min():%d %b %Y}"
                  f" – {dev_df['timestamp'].max():%d %b %Y}")
    color = _model_color(str(model))
    dot   = f'<span style="color:{color};font-size:20px;line-height:1">●</span>'

    status_cls   = 'status-active'   if is_active else 'status-inactive'
    status_label = 'Active'          if is_active else 'Inactive'

    return f'''
<div class="device-section" id="dev-{device_id[:8]}">
  <div class="device-header">
    <div class="device-header-main">
      {dot}
      <span class="device-model">{model}</span>
      <span class="device-meta">FW: {fw_str} &nbsp;·&nbsp; {n} readings &nbsp;·&nbsp; {n_cycles} cycles &nbsp;·&nbsp; {date_range}</span>
      <span class="device-status {status_cls}">{status_label}</span>
    </div>
    <div class="device-id">{device_id}</div>
  </div>
  <div class="device-body">

    <div class="section-block">
      <div class="block-title">Battery Life Estimates</div>
      {_battery_life_html(analysis['opt1'], analysis['opt2'], analysis['opt3'])}
    </div>

    <div class="section-block">
      <div class="block-title">Discharge Cycles</div>
      {_episodes_html(analysis['episodes'])}
    </div>

    <div class="two-col">
      <div class="section-block">
        <div class="block-title">Charging Behaviour</div>
        {_charging_html(analysis['chg'])}
      </div>
      <div class="section-block">
        <div class="block-title">Days of Week (logging activity)</div>
        {_days_html(analysis['dow'])}
      </div>
    </div>

  </div>
</div>'''


# ── Status table ──────────────────────────────────────────────────────────────

def _relative_time(ts, now):
    secs = (now - ts).total_seconds()
    if secs < 60:      return f'{int(secs)}s ago'
    if secs < 3600:    return f'{int(secs // 60)}m ago'
    if secs < 86400:   return f'{int(secs // 3600)}h ago'
    return f'{int(secs // 86400)}d ago'


def _status_style(ts, now):
    secs = (now - ts).total_seconds()
    if secs < 1800:    return ('#e8f5e9', '#2e7d32', '●')
    if secs < 21600:   return ('#fff8e1', '#f57f17', '●')
    if secs < 172800:  return ('#fff3e0', '#e65100', '●')
    return ('#ffebee', '#b71c1c', '●')


def _status_table_html(summaries):
    rows = ''
    prev_active = None
    for s in summaries:
        if prev_active is not None and prev_active and not s['is_active']:
            rows += ('<tr><td colspan="7" style="background:#f5f5f5;'
                     'font-size:11px;color:#999;padding:4px 12px;'
                     'border-top:2px solid #ddd">Inactive</td></tr>')
        prev_active = s['is_active']

        bg, fg, dot_char = s['status_style']
        color     = _model_color(str(s['model']))
        model_dot = f'<span style="color:{color}">●</span>'
        anchor    = f'#dev-{s["device_id"][:8]}'
        rows += (
            f'<tr>'
            f'<td><a href="{anchor}" style="font-family:monospace;font-size:12px;'
            f'color:#333;text-decoration:none">{s["device_id"][:16]}…</a></td>'
            f'<td>{model_dot} {s["model"]}</td>'
            f'<td style="font-family:monospace;font-size:11px;color:#888">{s["firmware"]}</td>'
            f'<td style="text-align:right">{s["n_readings"]}</td>'
            f'<td style="text-align:right">{s["last_bat"]:.0f}%</td>'
            f'<td style="font-size:12px;color:#666">{s["last_seen_str"]}</td>'
            f'<td style="background:{bg};color:{fg};text-align:center;font-size:16px">{dot_char}</td>'
            f'</tr>'
        )

    return (f'<table>'
            f'<thead><tr>'
            f'<th>Device ID</th><th>Model</th><th>Firmware</th>'
            f'<th style="text-align:right">Readings</th>'
            f'<th style="text-align:right">Last bat%</th>'
            f'<th>Last seen</th><th>Status</th>'
            f'</tr></thead>'
            f'<tbody>{rows}</tbody></table>')


# ── Main ──────────────────────────────────────────────────────────────────────

def generate_dashboard(data, save_path='dashboard.html'):
    data = _apply_exclusions(data)
    data = data[~data['device_id'].apply(_is_suppressed)].reset_index(drop=True)
    data = data.dropna(subset=['device_id']).reset_index(drop=True)
    data = (data.drop_duplicates(subset=['device_id', 'timestamp'])
                .reset_index(drop=True))

    # Timestamps in data are UTC-naive; compare against UTC now for correct ages
    now           = _utcnow()
    active_cutoff = now - pd.Timedelta(days=ACTIVE_THRESHOLD_DAYS)
    generated     = datetime.datetime.now(datetime.timezone.utc).strftime('%d %b %Y %H:%M UTC')

    # ── Per-device analysis (computed once, reused for model summary + sections) ──
    device_analyses = {}
    summaries       = []

    for did in data['device_id'].unique():
        dev_df = (data[data['device_id'] == did]
                  .sort_values('timestamp')
                  .reset_index(drop=True))
        meta  = BY_DEVICE_ID.get(did, {})
        model = (dev_df['watch_model'].dropna().iloc[0]
                 if dev_df['watch_model'].notna().any()
                 else (meta.get('watch_model') or '—'))
        fw_str  = _firmware_str(dev_df)
        last_ts = dev_df['timestamp'].max()
        last_bat = dev_df.loc[dev_df['timestamp'] == last_ts, 'bat'].iloc[0]

        episodes = _discharge_episodes(dev_df)
        device_analyses[did] = {
            'episodes': episodes,
            'opt1':     _battery_life_option1(episodes),
            'opt2':     _battery_life_option2(dev_df),
            'opt3':     _battery_life_option3(episodes),
            'chg':      _charging_behaviour(dev_df),
            'dow':      _days_of_week(dev_df),
        }

        summaries.append({
            'device_id':     did,
            'model':         model,
            'firmware':      fw_str,
            'n_readings':    len(dev_df),
            'last_ts':       last_ts,
            'last_bat':      last_bat,
            'last_seen_str': _relative_time(last_ts, now),
            'status_style':  _status_style(last_ts, now),
            'is_active':     last_ts >= active_cutoff,
        })

    summaries.sort(key=lambda s: (not s['is_active'], -s['n_readings']))
    n_active   = sum(1 for s in summaries if s['is_active'])
    n_inactive = len(summaries) - n_active

    # ── Build HTML sections ───────────────────────────────────────────────────
    model_summary = _model_summary_html(device_analyses, summaries)
    status_table  = _status_table_html(summaries)

    device_sections = ''
    prev_active = None
    for s in summaries:
        if prev_active is not None and prev_active and not s['is_active']:
            device_sections += (
                f'<div class="section-divider">Inactive devices ({n_inactive})</div>'
            )
        prev_active = s['is_active']
        did    = s['device_id']
        dev_df = (data[data['device_id'] == did]
                  .sort_values('timestamp')
                  .reset_index(drop=True))
        device_sections += _device_section_html(
            did, dev_df, s['is_active'], device_analyses[did])

    html = f"""<!DOCTYPE html>
<html>
<head>
<meta charset="utf-8">
<title>BatteryLogger — Device Dashboard</title>
<style>
  body {{
    font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', sans-serif;
    margin: 40px; color: #222; max-width: 1200px;
  }}
  h1 {{ font-size: 20px; margin-bottom: 4px; }}
  h2 {{
    font-size: 15px; margin-top: 36px; margin-bottom: 10px;
    color: #444; border-bottom: 1px solid #eee; padding-bottom: 6px;
  }}
  .meta {{ font-size: 13px; color: #888; margin-bottom: 28px; }}
  table {{ border-collapse: collapse; width: 100%; font-size: 13px; margin-bottom: 12px; }}
  th {{
    text-align: left; padding: 7px 12px; background: #f5f5f5;
    border-bottom: 2px solid #ddd; font-weight: 600;
  }}
  td {{ padding: 6px 12px; border-bottom: 1px solid #eee; vertical-align: middle; }}
  tr:hover td {{ background: #fafafa; }}

  /* ── Device cards ── */
  .device-section {{
    margin-top: 20px;
    border: 1px solid #e0e0e0;
    border-radius: 8px;
    overflow: hidden;
  }}
  .device-header {{
    background: #f8f9fa;
    padding: 12px 18px;
    border-bottom: 1px solid #e0e0e0;
  }}
  .device-header-main {{
    display: flex;
    align-items: center;
    gap: 10px;
    flex-wrap: wrap;
  }}
  .device-model {{
    font-size: 15px;
    font-weight: 700;
    color: #222;
  }}
  .device-meta {{
    font-size: 12px;
    color: #666;
    flex: 1;
  }}
  .device-id {{
    font-family: monospace;
    font-size: 11px;
    color: #aaa;
    margin-top: 5px;
    word-break: break-all;
  }}
  .device-status {{
    font-size: 11px; font-weight: 600;
    padding: 3px 10px; border-radius: 10px; white-space: nowrap;
  }}
  .status-active   {{ background: #e8f5e9; color: #2e7d32; }}
  .status-inactive {{ background: #f5f5f5; color: #999; }}

  .device-body {{ padding: 20px; }}
  .section-block {{ margin-bottom: 24px; }}
  .block-title {{
    font-size: 13px; font-weight: 600; color: #444;
    margin-bottom: 8px; padding-bottom: 4px;
    border-bottom: 1px solid #f0f0f0;
  }}
  .two-col {{
    display: grid;
    grid-template-columns: 1fr 1fr;
    gap: 24px;
  }}
  @media (max-width: 800px) {{ .two-col {{ grid-template-columns: 1fr; }} }}
  .section-divider {{
    margin-top: 36px; margin-bottom: 8px;
    font-size: 14px; font-weight: 600; color: #888;
    border-top: 2px solid #eee; padding-top: 14px;
  }}
</style>
</head>
<body>
<h1>BatteryLogger — Device Dashboard</h1>
<div class="meta">
  {len(summaries)} devices &nbsp;·&nbsp;
  <span style="color:#2e7d32"><strong>{n_active}</strong> active (&le;{ACTIVE_THRESHOLD_DAYS}d)</span>
  &nbsp;·&nbsp;
  <span style="color:#999"><strong>{n_inactive}</strong> inactive</span>
  &nbsp;·&nbsp;
  {len(data)} readings &nbsp;·&nbsp;
  Generated {generated}
</div>

<h2>Battery life by model</h2>
<p style="font-size:12px;color:#888;margin-top:-6px">Median across all devices of each model.</p>
{model_summary}

<h2>Device status</h2>
{status_table}

<h2>Per-device analysis</h2>
<p style="font-size:12px;color:#888;margin-top:-6px">
  Active-first, then by number of readings descending.
  Discharge cycles and charging behaviour use API data only.
</p>
{device_sections}

</body>
</html>"""

    with open(save_path, 'w') as f:
        f.write(html)
    print(f"Saved: {save_path}")
    return save_path


if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('--from-date', type=str, default=None, metavar='YYYY-MM-DD')
    parser.add_argument('--days', type=int, default=None)
    args = parser.parse_args()

    data = load_all()

    if args.days:
        cutoff = _utcnow() - pd.Timedelta(days=args.days)
        data   = data[data['timestamp'] >= cutoff].reset_index(drop=True)
        print(f"Filtered to last {args.days} days: {len(data)} readings")
    elif args.from_date:
        cutoff = pd.Timestamp(args.from_date)
        data   = data[data['timestamp'] >= cutoff].reset_index(drop=True)
        print(f"Filtered from {args.from_date}: {len(data)} readings")

    out = generate_dashboard(data, save_path='dashboard.html')
    subprocess.run(['open', out])
