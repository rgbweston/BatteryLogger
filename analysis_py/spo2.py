"""
spo2.py — Per-participant SpO2 "All Day" experiment analysis.

Analyses the intra-config experiment initiated on Friday 25 April 2026,
where selected participants switched their Pulse Ox setting to "All Day".

Outputs spo2.html with:
  1. Change log table
  2. Per-participant battery timeline (±N days around each switch)
  3. Paired before/after drain rate chart
  4. Before/after summary stats table

Run from the analysis_py directory:
    python spo2.py
    python spo2.py --window-days 7
"""

import argparse
import io
import base64
import subprocess
import time

import pandas as pd
import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt
import matplotlib.dates as mdates
import plotly.graph_objects as go

from load import load_all
from cycles import extract_cycles, _participant_key, _make_cycle
from exclusion_list import EXCLUDED_PARTICIPANT_CODES, EXCLUDED_DEVICE_IDS
from metadata import BY_DEVICE_ID, BY_PARTICIPANT_CODE
from config import PALETTE
from summary import _filter_outlier_cycles, _model_color
from zoom import _draw_segments

# ── SpO2 change log ───────────────────────────────────────────────────────────
# Rohan switched first: Friday 24 April 2026 08:30
# Most participants switched Friday 25 April; Sabrina on Monday 28 April

SPO2_CHANGES = [
    {
        'name':         'Rohan Barrowcliff',
        'device':       'Vivoactive 6',
        'lookup_id':    '0457c34ac33a3bc3ee0196003561d39b6b9a4080',
        'from_setting': 'Sleep Only',
        'switch_ts':    pd.Timestamp('2026-04-24 08:30'),
    },
    {
        'name':         'Emma Raywood',
        'device':       'Vivoactive 6',
        'lookup_code':  'quick-otter-3',
        'from_setting': 'During Sleep',
        'switch_ts':    pd.Timestamp('2026-04-25 08:38'),
    },
    {
        'name':         'Liza Pekosak',
        'device':       'Vivoactive 5',
        'lookup_id':    '727287ece99f866e56f84b53c3887b040aee29f3',
        'from_setting': 'Sleep Only',
        'switch_ts':    pd.Timestamp('2026-04-25 08:39'),
    },
    {
        'name':         'Eric Auyoung',
        'device':       'Venu 3S',
        'lookup_code':  'merry-panda-18',
        'from_setting': 'Sleep Only',
        'switch_ts':    pd.Timestamp('2026-04-25 08:45'),
    },
    {
        'name':         'John Daniels',
        'device':       'Venu 3S',
        'lookup_id':    '39492696cac7db14c5dd1102ebb468c79304c3fb',
        'from_setting': 'On Demand',
        'switch_ts':    pd.Timestamp('2026-04-25 09:24'),
    },
    {
        'name':         'Xinyu Wang',
        'device':       'Venu 3S',
        'lookup_id':    '98a5acccfb6f99af1b98ab4459b6fce647598e51',
        'from_setting': 'On Demand',
        'switch_ts':    pd.Timestamp('2026-04-25 10:40'),
    },
    {
        'name':         'Xiaoyu Zheng',
        'device':       'Venu 4 45mm',
        'lookup_id':    'fb947d3c61491c139176d0cc2ea98cee6d214393',
        'from_setting': 'Unknown',
        'switch_ts':    pd.Timestamp('2026-04-25 10:45'),
    },
    {
        'name':         'Benard Bene',
        'device':       'Vivoactive 5',
        'lookup_code':  'fierce-owl-1',
        'from_setting': 'Sleep Only',
        'switch_ts':    pd.Timestamp('2026-04-25 18:37'),
    },
    {
        'name':         'Sabrina Demirdjian',
        'device':       'Venu 3S',
        'lookup_code':  'keen-hawk-4',
        'from_setting': 'During Sleep',
        'switch_ts':    pd.Timestamp('2026-04-28 09:29'),
    },
]


# ── helpers ───────────────────────────────────────────────────────────────────

def _apply_exclusions(data):
    mask = (
        data['participant_code'].isin(EXCLUDED_PARTICIPANT_CODES) |
        data['device_id'].isin(EXCLUDED_DEVICE_IDS)
    )
    return data[~mask].reset_index(drop=True)


def _resolve_pkeys(changes, data):
    """Add '_pkey' and 'mst' to each change entry by matching against loaded data."""
    for entry in changes:
        pkey = None
        if 'lookup_code' in entry:
            sub = data[data['participant_code'] == entry['lookup_code']]
            if not sub.empty:
                pkey = _participant_key(sub.iloc[0])
            meta = BY_PARTICIPANT_CODE.get(entry['lookup_code'], {})
            entry.setdefault('mst', meta.get('mst', '—'))
        elif 'lookup_id' in entry:
            sub = data[data['device_id'] == entry['lookup_id']]
            if not sub.empty:
                pkey = _participant_key(sub.iloc[0])
            meta = BY_DEVICE_ID.get(entry['lookup_id'], {})
            entry.setdefault('mst', meta.get('mst', '—'))
        else:
            entry.setdefault('mst', '—')

        entry['_pkey'] = pkey
        if pkey is None:
            print(f"  Warning: no data found for {entry['name']} ({entry['device']})")

    return changes


def _split_cycles_at_switches(cycles, changes):
    """Split any cycle that straddles a participant's SpO2 switch timestamp.

    Cycles that cross the switch boundary are not attributable to before or after,
    so we split them at the switch_ts using the stored cycle_data segment.
    cycle_idx is renumbered per participant chronologically after splitting.
    """
    switch_by_pkey = {e['_pkey']: e['switch_ts'] for e in changes if e.get('_pkey')}
    out = []
    for c in cycles:
        switch_ts = switch_by_pkey.get(c['participant_key'])
        if switch_ts is None or not (c['start_ts'] < switch_ts < c['end_ts']):
            out.append(c)
            continue
        seg    = c['cycle_data']
        before = seg[seg['timestamp'] <  switch_ts].reset_index(drop=True)
        after  = seg[seg['timestamp'] >= switch_ts].reset_index(drop=True)
        if len(before) >= 2:
            cb = _make_cycle(before, c['participant_key'], c['cycle_idx'])
            if cb:
                out.append(cb)
        if len(after) >= 2:
            ca = _make_cycle(after, c['participant_key'], c['cycle_idx'])
            if ca:
                out.append(ca)

    # Renumber cycle_idx per participant in chronological order
    from collections import defaultdict
    by_pkey = defaultdict(list)
    for c in out:
        by_pkey[c['participant_key']].append(c)
    result = []
    for pkey, plist in by_pkey.items():
        plist.sort(key=lambda c: c['start_ts'])
        for idx, c in enumerate(plist, 1):
            c['cycle_idx'] = idx
            result.append(c)
    return result


def _before_after_rates(all_cycles, changes, window_days):
    """Compute mean %/day within window_days before/after each participant's switch."""
    window = pd.Timedelta(days=window_days)
    for entry in changes:
        pkey = entry.get('_pkey')
        if not pkey:
            entry.update({'before_rate': None, 'after_rate': None,
                          'before_n': 0, 'after_n': 0, 'delta': None})
            continue

        switch_ts = entry['switch_ts']
        pcycles = [c for c in all_cycles if c['participant_key'] == pkey]

        before = [c for c in pcycles
                  if c['end_ts'] <= switch_ts and c['start_ts'] >= switch_ts - window]
        after  = [c for c in pcycles
                  if c['start_ts'] >= switch_ts and c['end_ts'] <= switch_ts + window]

        br = round(sum(c['daily_rate'] for c in before) / len(before), 1) if before else None
        ar = round(sum(c['daily_rate'] for c in after)  / len(after),  1) if after  else None
        delta = round(ar - br, 1) if (br is not None and ar is not None) else None

        entry.update({
            'before_rate': br,
            'after_rate':  ar,
            'before_n':    len(before),
            'after_n':     len(after),
            'delta':       delta,
        })
    return changes


# ── Section 1: change log table ───────────────────────────────────────────────

def _change_log_html(changes):
    rows = ''
    for e in changes:
        ts_str   = e['switch_ts'].strftime('%a %-d %b %H:%M')
        has_data = '✓' if e.get('_pkey') else '—'
        approx   = ' <span style="color:#aaa;font-size:11px">(approx)</span>' if e['name'] == 'Eric Auyoung' else ''
        rows += (
            f'<tr>'
            f'<td>{e["name"]}</td>'
            f'<td>{e["device"]}</td>'
            f'<td style="color:#888">{e["from_setting"]}</td>'
            f'<td style="color:#cc0000;font-weight:600">All Day</td>'
            f'<td style="color:#555;font-size:12px">{ts_str}{approx}</td>'
            f'<td style="color:#aaa;font-size:11px;text-align:center">{has_data}</td>'
            f'</tr>\n'
        )
    return f'''
<table>
  <thead>
    <tr>
      <th>Participant</th><th>Device</th>
      <th>Previous Setting</th><th>Changed To</th>
      <th>Time</th><th>Data</th>
    </tr>
  </thead>
  <tbody>{rows}</tbody>
</table>'''


# ── Section 2: battery timelines ─────────────────────────────────────────────

def _battery_timelines_html(data, changes, split_cycles, window_days):
    """Per-participant battery-over-time plots, one subplot each, centred on switch."""
    affected = [e for e in changes if e.get('_pkey')]
    if not affected:
        return '<p>No participant data found.</p>'

    cycles_by_pkey = {}
    for c in split_cycles:
        cycles_by_pkey.setdefault(c['participant_key'], []).append(c)

    n     = len(affected)
    delta = pd.Timedelta(days=window_days)
    fig, axes = plt.subplots(n, 1, figsize=(20, 4 * n))
    if n == 1:
        axes = [axes]

    for i, (ax, entry) in enumerate(zip(axes, affected)):
        pkey      = entry['_pkey']
        switch_ts = entry['switch_ts']
        x_min     = switch_ts - delta
        x_max     = switch_ts + delta

        dev_data = data[
            (data['_pkey'] == pkey) &
            (data['timestamp'] >= x_min - pd.Timedelta(hours=1)) &
            (data['timestamp'] <= x_max + pd.Timedelta(hours=1))
        ].sort_values('timestamp').reset_index(drop=True)

        color = PALETTE[i % len(PALETTE)]
        if not dev_data.empty:
            _draw_segments(ax, dev_data, color)

        # Cycle annotation brackets
        bracket_top = 113
        for c in cycles_by_pkey.get(pkey, []):
            s_ts, e_ts = c['start_ts'], c['end_ts']
            if e_ts < x_min or s_ts > x_max:
                continue
            mid_ts = s_ts + (e_ts - s_ts) / 2
            mid_bp = (c['start_bp'] + c['end_bp']) / 2
            ax.plot([s_ts, s_ts], [bracket_top - 4, bracket_top], color='#555555', lw=0.8)
            ax.plot([e_ts, e_ts], [bracket_top - 4, bracket_top], color='#555555', lw=0.8)
            ax.plot([s_ts, e_ts], [bracket_top,     bracket_top], color='#555555', lw=0.8)
            label = (f"Cycle {c['cycle_idx']}\n"
                     f"{c['start_bp']:.0f}% → {c['end_bp']:.0f}%\n"
                     f"{c['daily_rate']}%/day")
            ax.text(mid_ts, bracket_top + 1, label,
                    ha='center', va='bottom', fontsize=5.5, color='#222222',
                    bbox=dict(boxstyle='round,pad=0.35', fc='#ffffcc', ec='#aaaaaa', alpha=0.92),
                    zorder=6)
            ax.annotate('', xy=(mid_ts, mid_bp), xytext=(mid_ts, bracket_top),
                        arrowprops=dict(arrowstyle='->', color='#888888', lw=0.8),
                        zorder=5)

        # SpO2 switch line
        ax.axvline(switch_ts, color='#cc0000', lw=2.0, ls='-', alpha=0.9, zorder=7)
        ax.text(switch_ts + pd.Timedelta(minutes=30), 100,
                f' SpO2: {entry["from_setting"]} → All Day',
                fontsize=7, color='#cc0000', va='top', ha='left', zorder=8)

        # Before/after rate labels
        br = entry.get('before_rate')
        ar = entry.get('after_rate')
        if br is not None:
            ax.text(switch_ts - pd.Timedelta(minutes=30), 8,
                    f'{br}%/day  ({entry["before_n"]} cycles)',
                    fontsize=7.5, color='#333333', ha='right', va='bottom',
                    bbox=dict(fc='white', ec='#cccccc', alpha=0.85, pad=3))
        if ar is not None:
            ax.text(switch_ts + pd.Timedelta(minutes=30), 8,
                    f'{ar}%/day  ({entry["after_n"]} cycles)',
                    fontsize=7.5, color='#cc0000', ha='left', va='bottom',
                    bbox=dict(fc='white', ec='#cc0000', alpha=0.85, pad=3))

        # Night shading 00:00–06:00
        current = x_min.normalize()
        while current <= x_max:
            ax.axvspan(current, current + pd.Timedelta(hours=6),
                       color='grey', alpha=0.08, zorder=0)
            current += pd.Timedelta(hours=24)

        ax.set_title(f"{entry['name']} — {entry['device']}",
                     fontsize=9, loc='left', pad=3, fontweight='bold')
        ax.text(0.99, 0.97, f"MST {entry.get('mst', '—')}",
                transform=ax.transAxes, fontsize=7, va='top', ha='right', color='#444444')
        ax.set_ylabel('Battery %', fontsize=8)
        ax.set_ylim(0, 135)
        ax.set_yticks([0, 25, 50, 75, 100])
        ax.set_xlim(x_min, x_max)
        ax.spines[['top', 'right']].set_visible(False)
        ax.yaxis.grid(True, ls='--', lw=0.3, alpha=0.4, color='grey')
        ax.xaxis.grid(True, ls=':', lw=0.3, alpha=0.3, color='grey')
        ax.set_axisbelow(True)
        ax.xaxis.set_major_locator(mdates.HourLocator(interval=6))
        ax.xaxis.set_major_formatter(mdates.DateFormatter('%-d %b\n%H:%M'))
        ax.xaxis.set_minor_locator(mdates.HourLocator(interval=1))
        ax.tick_params(axis='x', which='major', labelsize=7, rotation=0, labelbottom=True)
        ax.tick_params(axis='x', which='minor', length=3)

    fig.suptitle(f'Battery % — ±{window_days} day window around each SpO2 switch',
                 fontsize=12, y=1.005)
    fig.tight_layout()

    buf = io.BytesIO()
    fig.savefig(buf, format='png', dpi=130, bbox_inches='tight')
    buf.seek(0)
    b64 = base64.b64encode(buf.read()).decode()
    plt.close(fig)
    return f'<img src="data:image/png;base64,{b64}" style="width:100%;max-width:1100px;">'


# ── Section 3: paired before/after dot chart ──────────────────────────────────

def _paired_dot_html(changes, window_days):
    """Plotly chart: one x position per participant, hollow=before, filled=after."""
    eligible = [e for e in changes
                if e.get('before_rate') is not None or e.get('after_rate') is not None]
    if not eligible:
        return '<p>No rate data available yet.</p>'

    fig = go.Figure()
    models = sorted({e['device'] for e in eligible})

    for model in models:
        sub   = [e for e in eligible if e['device'] == model]
        color = _model_color(model)

        # Connector lines between before and after for same participant
        for e in sub:
            if e.get('before_rate') is not None and e.get('after_rate') is not None:
                fig.add_trace(go.Scatter(
                    x=[e['name'], e['name']],
                    y=[e['before_rate'], e['after_rate']],
                    mode='lines',
                    line=dict(color=color, width=1.5, dash='dot'),
                    showlegend=False,
                    hoverinfo='skip',
                ))

        # Before dots (hollow)
        before_pts = [e for e in sub if e.get('before_rate') is not None]
        if before_pts:
            fig.add_trace(go.Scatter(
                x=[e['name'] for e in before_pts],
                y=[e['before_rate'] for e in before_pts],
                mode='markers',
                name=f'{model} — before',
                marker=dict(color='white', size=12, opacity=1.0,
                            line=dict(color=color, width=2.5)),
                text=[
                    f"<b>{e['name']}</b>  ·  {model}<br>"
                    f"Before switch: <b>{e['before_rate']}%/day</b>  ({e['before_n']} cycles)<br>"
                    f"Window: ±{window_days} days"
                    for e in before_pts
                ],
                hovertemplate='%{text}<extra></extra>',
            ))

        # After dots (filled)
        after_pts = [e for e in sub if e.get('after_rate') is not None]
        if after_pts:
            def _after_label(e):
                base = (f"<b>{e['name']}</b>  ·  {model}<br>"
                        f"After switch: <b>{e['after_rate']}%/day</b>  ({e['after_n']} cycles)<br>"
                        f"Window: ±{window_days} days")
                if e.get('delta') is not None:
                    sign = '+' if e['delta'] > 0 else ''
                    base += f"<br>Change: <b>{sign}{e['delta']}%/day</b>"
                return base

            fig.add_trace(go.Scatter(
                x=[e['name'] for e in after_pts],
                y=[e['after_rate'] for e in after_pts],
                mode='markers',
                name=f'{model} — after',
                marker=dict(color=color, size=12, opacity=0.9,
                            line=dict(color=color, width=1)),
                text=[_after_label(e) for e in after_pts],
                hovertemplate='%{text}<extra></extra>',
            ))

    fig.update_layout(
        xaxis=dict(tickangle=-30, showgrid=False),
        yaxis=dict(title='Drain rate (%/day)', rangemode='tozero',
                   gridcolor='rgba(180,180,180,0.3)'),
        legend=dict(orientation='h', yanchor='bottom', y=1.02, xanchor='left', x=0),
        plot_bgcolor='white',
        paper_bgcolor='white',
        height=440,
        margin=dict(l=60, r=30, t=70, b=100),
        hovermode='closest',
    )
    return fig.to_html(full_html=False, include_plotlyjs='cdn')


# ── Section 4: before/after stats table ───────────────────────────────────────

def _stats_table_html(changes):
    rows = ''
    for e in changes:
        br  = e.get('before_rate')
        ar  = e.get('after_rate')
        d   = e.get('delta')
        bn  = e.get('before_n', 0)
        an  = e.get('after_n', 0)

        br_str = f'{br:.1f}' if br is not None else '<span style="color:#aaa">—</span>'
        ar_str = f'{ar:.1f}' if ar is not None else '<span style="color:#aaa">—</span>'
        if d is not None:
            sign  = '+' if d > 0 else ''
            dcol  = '#b71c1c' if d > 0 else '#2e7d32'
            d_str = f'<span style="color:{dcol};font-weight:600">{sign}{d:.1f}</span>'
        else:
            d_str = '<span style="color:#aaa">—</span>'

        color = _model_color(e['device'])
        dot   = f'<span style="color:{color};font-size:16px">●</span>'
        rows += (
            f'<tr>'
            f'<td>{e["name"]}</td>'
            f'<td>{dot} {e["device"]}</td>'
            f'<td style="color:#555">MST {e.get("mst", "—")}</td>'
            f'<td style="text-align:right">{br_str}</td>'
            f'<td style="text-align:right;color:#aaa;font-size:12px">{bn}</td>'
            f'<td style="text-align:right">{ar_str}</td>'
            f'<td style="text-align:right;color:#aaa;font-size:12px">{an}</td>'
            f'<td style="text-align:right">{d_str}</td>'
            f'</tr>\n'
        )

    return f'''
<table>
  <thead>
    <tr>
      <th>Participant</th><th>Device</th><th>MST</th>
      <th style="text-align:right">Before (%/day)</th>
      <th style="text-align:right;color:#aaa;font-weight:normal">n</th>
      <th style="text-align:right">After (%/day)</th>
      <th style="text-align:right;color:#aaa;font-weight:normal">n</th>
      <th style="text-align:right">Δ</th>
    </tr>
  </thead>
  <tbody>{rows}</tbody>
</table>'''


# ── main ──────────────────────────────────────────────────────────────────────

def generate_spo2(data, save_path='spo2.html', window_days=4):
    data = _apply_exclusions(data)
    data = data.copy()
    data['_pkey'] = data.apply(_participant_key, axis=1)

    changes = [{**e} for e in SPO2_CHANGES]
    changes = _resolve_pkeys(changes, data)

    raw_cycles    = extract_cycles(data)
    split_cycles  = _split_cycles_at_switches(raw_cycles, changes)
    filt_cycles   = _filter_outlier_cycles(split_cycles)
    changes       = _before_after_rates(filt_cycles, changes, window_days)

    change_log_html   = _change_log_html(changes)
    timelines_html    = _battery_timelines_html(data, changes, split_cycles, window_days)
    paired_dot_html   = _paired_dot_html(changes, window_days)
    stats_html        = _stats_table_html(changes)

    n_affected  = sum(1 for e in changes if e.get('_pkey'))
    generated   = time.strftime('%d %b %Y %H:%M')

    html = f"""<!DOCTYPE html>
<html>
<head>
<meta charset="utf-8">
<title>BatteryLogger — SpO2 All Day Experiment</title>
<style>
  body {{ font-family: -apple-system, sans-serif; margin: 40px; color: #222; max-width: 1100px; }}
  h1 {{ font-size: 20px; margin-bottom: 4px; }}
  h2 {{ font-size: 15px; margin-top: 40px; margin-bottom: 12px; color: #444;
        border-bottom: 1px solid #eee; padding-bottom: 6px; }}
  .meta {{ font-size: 13px; color: #888; margin-bottom: 28px; }}
  .note {{ font-size: 12px; color: #888; font-style: italic; margin-bottom: 20px; }}
  table {{ border-collapse: collapse; width: 100%; font-size: 13px; margin-bottom: 12px; }}
  th {{ text-align: left; padding: 7px 12px; background: #f5f5f5;
        border-bottom: 2px solid #ddd; font-weight: 600; }}
  td {{ padding: 6px 12px; border-bottom: 1px solid #eee; }}
  tr:hover td {{ background: #fafafa; }}
</style>
</head>
<body>
<h1>BatteryLogger — SpO2 "All Day" Experiment</h1>
<div class="meta">
  Initiated Friday 25 Apr 2026 &nbsp;·&nbsp;
  {n_affected} / {len(changes)} participants with data &nbsp;·&nbsp;
  ±{window_days} day window for before/after comparison &nbsp;·&nbsp;
  Generated {generated}
</div>

<h2>1. Change log</h2>
<p class="note">Rohan switched first on Friday 24 Apr 2026. Most participants switched Friday 25 Apr.
Sabrina switched on Monday 28 Apr. Eric's time is approximate (~08:45).</p>
{change_log_html}

<h2>2. Battery over time — ±{window_days} days around each participant's switch</h2>
<p class="note">Red line = SpO2 switch. Brackets = discharge cycles with drain rate.
Before/after mean rates shown in lower corners. Night shading = 00:00–06:00.</p>
{timelines_html}

<h2>3. Before vs after drain rate — by participant</h2>
<p class="note">Hollow dot = before switch, filled = after. Dotted line connects same participant.
Coloured by watch model. Rates computed from discharge cycles within ±{window_days} days of each switch.</p>
{paired_dot_html}

<h2>4. Before/after summary</h2>
<p class="note">Δ = after − before (%/day). Green = battery improved (lower drain). Red = drain increased.</p>
{stats_html}

</body>
</html>"""

    with open(save_path, 'w') as f:
        f.write(html)
    print(f"Saved: {save_path}")
    return save_path


if __name__ == '__main__':
    parser = argparse.ArgumentParser(
        description='SpO2 All Day experiment analysis — battery drain before vs after.'
    )
    parser.add_argument('--window-days', type=int, default=4,
                        help='Days before/after the switch to include in comparison (default: 4)')
    args = parser.parse_args()

    data = load_all()
    out  = generate_spo2(data, save_path='spo2.html', window_days=args.window_days)
    subprocess.run(['open', out])
