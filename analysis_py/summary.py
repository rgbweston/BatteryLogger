"""
summary.py — Cross-participant drain pattern summary.

Outputs a single HTML page with:
  1. Mean drain rate (% /day) by config era × watch model
  2. Cycle scatter: one dot per cycle, era on x, %/day on y, coloured by model
  3. Per-participant summary table

Run from the analysis_py directory:
    python summary.py
or:
    python summary.py --days 30
"""

import argparse
import subprocess
import time
import pandas as pd
import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt
import matplotlib.patches as mpatches
import io, base64
import plotly.graph_objects as go

from load import load_all
from cycles import extract_cycles
from config import ERA_LABEL_MAP, CONFIG_SORTED
from exclusion_list import (
    EXCLUDED_PARTICIPANT_CODES,
    EXCLUDED_DEVICE_IDS,
    SDK_WINDOWS,
    MIN_CYCLE_DURATION_HOURS,
    MAX_DRAIN_PERCENT_PER_DAY,
    MIN_CYCLE_DROP_PERCENT,
)
from metadata import PARTICIPANTS

# ── model colour map (consistent across all charts) ──────────────────────────

MODEL_COLORS = {
    'Vivoactive 5': '#1f77b4',
    'Vivoactive 6': '#ff7f0e',
    'Venu 3S':      '#2ca02c',
    'Venu 4 41mm':  '#d62728',
    'Venu 4 45mm':  '#9467bd',
    'Venu 4':       '#8c564b',
}
DEFAULT_COLOR = '#aaaaaa'

# ── participant name lookup ───────────────────────────────────────────────────
# Build a map from participant_code → name and device_id → name
_NAME_BY_CODE = {p['participant_code']: p['participant_name']
                 for p in PARTICIPANTS
                 if p.get('participant_code') and p.get('participant_name')}
_NAME_BY_DEVICE = {p['device_id']: p['participant_name']
                   for p in PARTICIPANTS
                   if p.get('device_id') and p.get('participant_name')}


def _participant_name(pkey):
    """Return 'Name (code)' if name known, else just pkey."""
    name = _NAME_BY_CODE.get(pkey) or _NAME_BY_DEVICE.get(pkey)
    if name:
        return f"{name} ({pkey})"
    return pkey


def _model_color(model):
    return MODEL_COLORS.get(str(model).strip(), DEFAULT_COLOR)


# ── exclusions ────────────────────────────────────────────────────────────────

def _apply_exclusions(data):
    # Drop fully excluded participants / devices
    mask = (
        data['participant_code'].isin(EXCLUDED_PARTICIPANT_CODES) |
        data['device_id'].isin(EXCLUDED_DEVICE_IDS)
    )
    data = data[~mask].reset_index(drop=True)

    # Apply per-participant SDK connectivity windows
    drop_idx = set()
    for key, window in SDK_WINDOWS.items():
        # Match on participant_code or device_id
        match = (data['participant_code'] == key) | (data['device_id'] == key)
        idx = data[match].index
        if window['from_ts'] is not None:
            drop_idx.update(idx[data.loc[idx, 'timestamp'] < window['from_ts']].tolist())
        if window['to_ts'] is not None:
            drop_idx.update(idx[data.loc[idx, 'timestamp'] >= window['to_ts']].tolist())

    if drop_idx:
        print(f"SDK window filter: dropped {len(drop_idx)} readings outside connected periods")
    return data.drop(index=drop_idx).reset_index(drop=True)


def _filter_outlier_cycles(
    cycles,
    min_duration_hours=MIN_CYCLE_DURATION_HOURS,
    max_daily_rate=MAX_DRAIN_PERCENT_PER_DAY,
    min_drop_percent=MIN_CYCLE_DROP_PERCENT,
):
    """Drop unreliable / noisy cycles.

    Filters applied:
      - Too short (duration)
      - Too extreme (%/day)
      - Too small battery drop (optional noise filter)
    """
    before = len(cycles)

    filtered = []
    for c in cycles:
        duration = c.get('delta_hrs', 0)
        rate     = c.get('daily_rate', 0)
        drop     = (c.get('start_bp', 0) - c.get('end_bp', 0))

        if duration < min_duration_hours:
            continue
        if rate > max_daily_rate:
            continue
        if drop < min_drop_percent:
            continue

        filtered.append(c)

    dropped = before - len(filtered)
    if dropped:
        print(
            f"Cycle filter: dropped {dropped} / {before} cycles "
            f"(short < {min_duration_hours}h, "
            f"rate > {max_daily_rate}%/day, "
            f"drop < {min_drop_percent}%)"
        )

    return filtered


# ── fig → base64 PNG ──────────────────────────────────────────────────────────

def _fig_to_b64(fig):
    buf = io.BytesIO()
    fig.savefig(buf, format='png', dpi=130, bbox_inches='tight')
    buf.seek(0)
    return base64.b64encode(buf.read()).decode()
    plt.close(fig)


# ── 1. drain rate table: era × model ─────────────────────────────────────────

def _era_model_table(cycles):
    rows = []
    for c in cycles:
        rows.append({
            'era':        ERA_LABEL_MAP.get(c['era'], c['era']),
            'model':      c.get('watch_model', '—'),
            'daily_rate': c['daily_rate'],
        })
    df = pd.DataFrame(rows)
    if df.empty:
        return '<p>No cycle data available.</p>'

    pivot = (df.groupby(['era', 'model'])['daily_rate']
               .agg(['mean', 'count'])
               .round(1)
               .reset_index())
    pivot.columns = ['Era', 'Model', 'Mean %/day', 'N cycles']

    # Order eras chronologically using the same key construction as get_era()
    era_order = [ERA_LABEL_MAP.get('Pre SpO2', 'Initial')] + [
        ERA_LABEL_MAP.get(f'Post {n}', n) for n, _ in CONFIG_SORTED
    ]
    pivot['_era_rank'] = pivot['Era'].apply(
        lambda e: era_order.index(e) if e in era_order else 999)
    pivot = pivot.sort_values(['_era_rank', 'Model']).drop(columns='_era_rank')

    # Colour-code mean column: darker red = faster drain
    max_rate = pivot['Mean %/day'].max()
    min_rate = pivot['Mean %/day'].min()

    def cell_style(val):
        if pd.isna(val) or max_rate == min_rate:
            return ''
        norm = (val - min_rate) / (max_rate - min_rate)
        r = int(255)
        g = int(255 - norm * 120)
        b = int(255 - norm * 120)
        return f'background:rgb({r},{g},{b})'

    html_rows = ''
    prev_era = None
    for _, row in pivot.iterrows():
        era_cell = f'<td><b>{row["Era"]}</b></td>' if row['Era'] != prev_era else '<td style="color:#aaa">″</td>'
        prev_era = row['Era']
        style = cell_style(row['Mean %/day'])
        html_rows += (
            f'<tr>{era_cell}'
            f'<td>{row["Model"]}</td>'
            f'<td style="{style}">{row["Mean %/day"]}</td>'
            f'<td style="color:#888">{int(row["N cycles"])}</td></tr>\n'
        )

    return f'''
<table>
  <thead>
    <tr><th>Era</th><th>Model</th><th>Mean %/day</th><th>N cycles</th></tr>
  </thead>
  <tbody>{html_rows}</tbody>
</table>'''


# ── scatter helpers ───────────────────────────────────────────────────────────

# Distinct colours for MST values 1-7
# Official Monk Skin Tone hex values (MST 1–10)
MST_COLORS = {
    '1':  '#f6ede4',  # rgb(246, 237, 228)
    '2':  '#f3e7db',  # rgb(243, 231, 219)
    '3':  '#f7ead0',  # rgb(247, 234, 208)
    '4':  '#eadaba',  # rgb(234, 218, 186)
    '5':  '#d7bd96',  # rgb(215, 189, 150)
    '6':  '#a07e56',  # rgb(160, 126, 86)
    '7':  '#825c43',  # rgb(130, 92, 67)
    '8':  '#604134',  # rgb(96, 65, 52)
    '9':  '#3a312a',  # rgb(58, 49, 42)
    '10': '#292420',  # rgb(41, 36, 32)
}

# Lighter tones (1–5) need a visible border against a white background
MST_BORDER = {
    '1': '#c8b8a8', '2': '#c4b4a4', '3': '#c8c0a0',
    '4': '#b8a880', '5': '#a08060',
}

def _mst_color(mst):
    return MST_COLORS.get(str(mst).strip(), DEFAULT_COLOR)

def _mst_border(mst):
    return MST_BORDER.get(str(mst).strip(), 'white')


def _cycles_to_df(cycles):
    """Convert cycle list to a tidy DataFrame with era labels."""
    rows = []
    for c in cycles:
        era_label = ERA_LABEL_MAP.get(c['era'], c['era'])
        daily = c['daily_rate']
        days_life = round(100.0 / daily, 1) if daily > 0 else None
        rows.append({
            'era':        era_label,
            'model':      c.get('watch_model', '—'),
            'mst':        str(c.get('mst', '—')),
            'daily_rate': daily,
            'days_life':  days_life,
            'hourly_rate':c['hourly_rate'],
            'pkey':       c['participant_key'],
            'cycle_idx':  c['cycle_idx'],
            'start_bp':   c['start_bp'],
            'end_bp':     c['end_bp'],
            'delta_hrs':  c['delta_hrs'],
            'start_ts':   c['start_ts'],
            'end_ts':     c['end_ts'],
        })
    df = pd.DataFrame(rows)

    era_order = [ERA_LABEL_MAP.get('Pre SpO2', 'Initial')] + [
        ERA_LABEL_MAP.get(f'Post {n}', n) for n, _ in CONFIG_SORTED
    ]
    seen = set(df['era'].values)
    present_eras = [e for e in era_order if e in seen]
    era_x = {e: i for i, e in enumerate(present_eras)}

    return df, era_x


def _hover_text(row):
    days = f"{row['days_life']:.1f} days" if row['days_life'] else '—'
    return (
        f"<b>{_participant_name(row['pkey'])}</b>  ·  cycle {row['cycle_idx']}<br>"
        f"MST {row['mst']}  ·  {row['model']}<br>"
        f"Era: {row['era']}<br>"
        f"─────────────────<br>"
        f"Drain: <b>{row['daily_rate']:.1f} %/day</b>  ({row['hourly_rate']:.2f} %/hr)<br>"
        f"Battery life at this rate: <b>{days}</b><br>"
        f"Start → End: {row['start_bp']:.0f}% → {row['end_bp']:.0f}%  "
        f"(Δ {row['start_bp'] - row['end_bp']:.0f}%)<br>"
        f"Duration: {row['delta_hrs']:.1f} h<br>"
        f"From: {pd.Timestamp(row['start_ts']).strftime('%d %b %H:%M')}<br>"
        f"To:   {pd.Timestamp(row['end_ts']).strftime('%d %b %H:%M')}"
    )


def _add_era_means(fig, df, era_x, y_col='daily_rate'):
    """Add a short horizontal mean bar per era."""
    for era, x in era_x.items():
        vals = df[df['era'] == era][y_col].dropna()
        if len(vals):
            fig.add_shape(type='line',
                          x0=x - 0.38, x1=x + 0.38,
                          y0=vals.mean(), y1=vals.mean(),
                          line=dict(color='#333333', width=2),
                          layer='above')


def _scatter_layout(fig, era_x, ytitle):
    fig.update_layout(
        xaxis=dict(
            tickmode='array',
            tickvals=list(era_x.values()),
            ticktext=list(era_x.keys()),
            tickangle=-35,
            tickfont=dict(size=11),
            showgrid=False,
        ),
        yaxis=dict(
            title=ytitle,
            rangemode='tozero',
            gridcolor='rgba(180,180,180,0.3)',
        ),
        legend=dict(orientation='h', yanchor='bottom', y=1.02, xanchor='left', x=0),
        plot_bgcolor='white',
        paper_bgcolor='white',
        height=480,
        margin=dict(l=60, r=30, t=50, b=100),
        hovermode='closest',
    )


# ── 2a. drain rate scatter — coloured by watch model ─────────────────────────

def _cycle_scatter(cycles):
    """%/day scatter, one dot per cycle, coloured by watch model."""
    if not cycles:
        return ''

    df, era_x = _cycles_to_df(cycles)
    models = sorted(df['model'].unique())
    n_models = len(models)
    fig = go.Figure()

    for model in models:
        sub = df[df['model'] == model].copy()
        jitter = (models.index(model) - n_models / 2) * 0.12
        sub['x'] = sub['era'].map(era_x) + jitter
        hover = [_hover_text(row) for _, row in sub.iterrows()]

        fig.add_trace(go.Scatter(
            x=sub['x'], y=sub['daily_rate'],
            mode='markers', name=model,
            marker=dict(color=_model_color(model), size=8, opacity=0.8,
                        line=dict(width=0.5, color='white')),
            hovertemplate='%{text}<extra></extra>',
            text=hover,
        ))

    _add_era_means(fig, df, era_x, 'daily_rate')
    _scatter_layout(fig, era_x, 'Drain rate (%/day)')
    return fig.to_html(full_html=False, include_plotlyjs='cdn')


# ── 2b. drain rate scatter — coloured by MST ─────────────────────────────────

def _cycle_scatter_mst(cycles):
    """Same as _cycle_scatter but dots coloured by MST value."""
    if not cycles:
        return ''

    df, era_x = _cycles_to_df(cycles)
    msts = sorted(df['mst'].unique(), key=lambda m: (m == '—', m))
    n_msts = len(msts)

    # Keep same x-jitter logic but group by MST instead of model
    models = sorted(df['model'].unique())
    n_models = len(models)
    fig = go.Figure()

    for mst in msts:
        sub = df[df['mst'] == mst].copy()
        # jitter by model so same-MST dots from different models don't overlap
        sub['x'] = sub.apply(
            lambda r: era_x[r['era']] + (models.index(r['model']) - n_models / 2) * 0.12,
            axis=1
        )
        hover = [_hover_text(row) for _, row in sub.iterrows()]
        label = f"MST {mst}" if mst != '—' else 'MST unknown'

        fig.add_trace(go.Scatter(
            x=sub['x'], y=sub['daily_rate'],
            mode='markers', name=label,
            marker=dict(color=_mst_color(mst), size=9, opacity=1.0,
                        line=dict(width=1.2, color=_mst_border(mst))),
            hovertemplate='%{text}<extra></extra>',
            text=hover,
        ))

    _add_era_means(fig, df, era_x, 'daily_rate')
    _scatter_layout(fig, era_x, 'Drain rate (%/day)')
    return fig.to_html(full_html=False, include_plotlyjs='cdn')


# ── 2c. battery life scatter — coloured by watch model ───────────────────────

def _cycle_scatter_life(cycles):
    """Y-axis = days battery would last at this cycle's drain rate, coloured by model."""
    if not cycles:
        return ''

    df, era_x = _cycles_to_df(cycles)
    df = df.dropna(subset=['days_life'])
    models = sorted(df['model'].unique())
    n_models = len(models)
    fig = go.Figure()

    for model in models:
        sub = df[df['model'] == model].copy()
        jitter = (models.index(model) - n_models / 2) * 0.12
        sub['x'] = sub['era'].map(era_x) + jitter
        hover = [_hover_text(row) for _, row in sub.iterrows()]

        fig.add_trace(go.Scatter(
            x=sub['x'], y=sub['days_life'],
            mode='markers', name=model,
            marker=dict(color=_model_color(model), size=8, opacity=0.8,
                        line=dict(width=0.5, color='white')),
            hovertemplate='%{text}<extra></extra>',
            text=hover,
        ))

    _add_era_means(fig, df, era_x, 'days_life')
    _scatter_layout(fig, era_x, 'Estimated battery life (days)')
    return fig.to_html(full_html=False, include_plotlyjs='cdn')


# ── 4b. battery life scatter — coloured by MST ───────────────────────────────

def _cycle_scatter_life_mst(cycles):
    """Y-axis = days battery would last, dots coloured by MST."""
    if not cycles:
        return ''

    df, era_x = _cycles_to_df(cycles)
    df = df.dropna(subset=['days_life'])
    models = sorted(df['model'].unique())
    n_models = len(models)
    msts = sorted(df['mst'].unique(), key=lambda m: (m == '—', m))
    fig = go.Figure()

    for mst in msts:
        sub = df[df['mst'] == mst].copy()
        sub['x'] = sub.apply(
            lambda r: era_x[r['era']] + (models.index(r['model']) - n_models / 2) * 0.12,
            axis=1
        )
        hover = [_hover_text(row) for _, row in sub.iterrows()]
        label = f"MST {mst}" if mst != '—' else 'MST unknown'

        fig.add_trace(go.Scatter(
            x=sub['x'], y=sub['days_life'],
            mode='markers', name=label,
            marker=dict(color=_mst_color(mst), size=9, opacity=1.0,
                        line=dict(width=1.2, color=_mst_border(mst))),
            hovertemplate='%{text}<extra></extra>',
            text=hover,
        ))

    _add_era_means(fig, df, era_x, 'days_life')
    _scatter_layout(fig, era_x, 'Estimated battery life (days)')
    return fig.to_html(full_html=False, include_plotlyjs='cdn')


# ── 3. per-participant summary table ─────────────────────────────────────────

def _participant_table(data, cycles):
    rows = []
    from cycles import _participant_key
    data = data.copy()
    data['_pkey'] = data.apply(_participant_key, axis=1)

    cycles_by_pkey = {}
    for c in cycles:
        cycles_by_pkey.setdefault(c['participant_key'], []).append(c)

    for pkey in sorted(data['_pkey'].unique()):
        sub = data[data['_pkey'] == pkey]
        pcycles = cycles_by_pkey.get(pkey, [])
        rates = [c['daily_rate'] for c in pcycles]

        model = sub['watch_model'].dropna()
        mst   = sub['mst'].dropna()
        pc    = sub['participant_code'].dropna()

        rows.append({
            'Participant': pc.iloc[0] if len(pc) else pkey,
            'MST':         mst.iloc[0] if len(mst) else '—',
            'Model':       model.iloc[0] if len(model) else '—',
            'Readings':    len(sub),
            'Cycles':      len(pcycles),
            'Avg %/day':   round(sum(rates) / len(rates), 1) if rates else '—',
            'Best cycle':  f"{min(rates):.1f}" if rates else '—',
            'Worst cycle': f"{max(rates):.1f}" if rates else '—',
            'Date range':  (f"{sub['timestamp'].min():%d %b} – "
                            f"{sub['timestamp'].max():%d %b}"),
        })

    df = pd.DataFrame(rows).sort_values(['Model', 'MST'])

    html_rows = ''
    for _, r in df.iterrows():
        color = _model_color(str(r['Model']))
        dot = f'<span style="color:{color};font-size:16px">●</span>'
        html_rows += (
            f'<tr><td>{r["Participant"]}</td>'
            f'<td>{r["MST"]}</td>'
            f'<td>{dot} {r["Model"]}</td>'
            f'<td style="text-align:right">{r["Readings"]}</td>'
            f'<td style="text-align:right">{r["Cycles"]}</td>'
            f'<td style="text-align:right">{r["Avg %/day"]}</td>'
            f'<td style="text-align:right;color:#2e7d32">{r["Best cycle"]}</td>'
            f'<td style="text-align:right;color:#b71c1c">{r["Worst cycle"]}</td>'
            f'<td style="color:#888;font-size:12px">{r["Date range"]}</td></tr>\n'
        )

    return f'''
<table>
  <thead>
    <tr>
      <th>Participant</th><th>MST</th><th>Model</th>
      <th style="text-align:right">Readings</th>
      <th style="text-align:right">Cycles</th>
      <th style="text-align:right">Avg %/day</th>
      <th style="text-align:right">Best cycle</th>
      <th style="text-align:right">Worst cycle</th>
      <th>Date range</th>
    </tr>
  </thead>
  <tbody>{html_rows}</tbody>
</table>'''


# ── enrich cycles with watch_model and MST ───────────────────────────────────

def _enrich_cycles(cycles, data):
    from cycles import _participant_key
    data = data.copy()
    data['_pkey'] = data.apply(_participant_key, axis=1)
    model_map = (data.dropna(subset=['watch_model'])
                     .groupby('_pkey')['watch_model']
                     .first()
                     .to_dict())
    mst_map = (data.dropna(subset=['mst'])
                   .groupby('_pkey')['mst']
                   .first()
                   .to_dict())
    for c in cycles:
        c['watch_model'] = model_map.get(c['participant_key'], '—')
        c['mst']         = mst_map.get(c['participant_key'], '—')
    return cycles


# ── main ──────────────────────────────────────────────────────────────────────

def generate_summary(data, save_path='summary.html'):
    data = _apply_exclusions(data)
    cycles = extract_cycles(data)
    cycles = _enrich_cycles(cycles, data)
    cycles = _filter_outlier_cycles(cycles)

    era_table_html      = _era_model_table(cycles)
    scatter_model_html  = _cycle_scatter(cycles)
    scatter_mst_html    = _cycle_scatter_mst(cycles)
    scatter_life_html     = _cycle_scatter_life(cycles)
    scatter_life_mst_html = _cycle_scatter_life_mst(cycles)
    participant_html    = _participant_table(data, cycles)

    n_participants = data['participant_code'].nunique() + data.loc[
        data['participant_code'].isna(), 'device_id'].nunique()
    generated = time.strftime('%d %b %Y %H:%M')

    html = f"""<!DOCTYPE html>
<html>
<head>
<meta charset="utf-8">
<title>BatteryLogger — Drain Summary</title>
<style>
  body {{ font-family: -apple-system, sans-serif; margin: 40px; color: #222; max-width: 1100px; }}
  h1 {{ font-size: 20px; margin-bottom: 4px; }}
  h2 {{ font-size: 15px; margin-top: 40px; margin-bottom: 12px; color: #444; border-bottom: 1px solid #eee; padding-bottom: 6px; }}
  .meta {{ font-size: 13px; color: #888; margin-bottom: 28px; }}
  table {{ border-collapse: collapse; width: 100%; font-size: 13px; margin-bottom: 12px; }}
  th {{ text-align: left; padding: 7px 12px; background: #f5f5f5;
        border-bottom: 2px solid #ddd; font-weight: 600; }}
  td {{ padding: 6px 12px; border-bottom: 1px solid #eee; }}
  tr:hover td {{ background: #fafafa; }}
</style>
</head>
<body>
<h1>BatteryLogger — Battery Drain Summary</h1>
<div class="meta">
  {n_participants} participants &nbsp;·&nbsp;
  {len(data)} readings &nbsp;·&nbsp;
  {len(cycles)} discharge cycles &nbsp;·&nbsp;
  Generated {generated}
</div>

<h2>1. Mean drain rate by config era &amp; watch model (%/day)</h2>
{era_table_html}

<h2>2. Drain rate per cycle by era — by watch model</h2>
<p style="font-size:12px;color:#888">Each dot is one discharge cycle. Horizontal bar = era mean. Hover for full details.</p>
{scatter_model_html}

<h2>3. Drain rate per cycle by era — by MST</h2>
<p style="font-size:12px;color:#888">Same cycles and positions, dots coloured by MST value.</p>
{scatter_mst_html}

<h2>4. Estimated battery life per cycle by era — by watch model</h2>
<p style="font-size:12px;color:#888">Y-axis = days the battery would last at each cycle's drain rate (100 ÷ %/day). Coloured by watch model.</p>
{scatter_life_html}

<h2>5. Estimated battery life per cycle by era — by MST</h2>
<p style="font-size:12px;color:#888">Same data, dots coloured by Monk Skin Tone.</p>
{scatter_life_mst_html}

<h2>6. Per-participant summary</h2>
{participant_html}

</body>
</html>"""

    with open(save_path, 'w') as f:
        f.write(html)
    print(f"Saved: {save_path}")
    return save_path


if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('--days', type=int, default=None,
                        help='Only use the last N days of data')
    parser.add_argument('--from-date', type=str, default=None, metavar='YYYY-MM-DD',
                        help='Only use data on or after this date (e.g. 2026-04-01)')
    args = parser.parse_args()

    data = load_all()

    if args.days is not None:
        cutoff = pd.Timestamp.now() - pd.Timedelta(days=args.days)
        data = data[data['timestamp'] >= cutoff].reset_index(drop=True)
        print(f"Filtered to last {args.days} days: {len(data)} readings")
    elif args.from_date is not None:
        cutoff = pd.Timestamp(args.from_date)
        data = data[data['timestamp'] >= cutoff].reset_index(drop=True)
        print(f"Filtered from {args.from_date}: {len(data)} readings")

    out = generate_summary(data, save_path='summary.html')
    subprocess.run(['open', out])
