import subprocess
import pandas as pd
import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt
import matplotlib.dates as mdates
import matplotlib.patches as mpatches
import matplotlib.colors as mcolors
import plotly.graph_objects as go
from plotly.subplots import make_subplots

from config import CONFIG_SORTED, CONFIG_LINE_COLORS, ERA_MARKERS, PALETTE
from cycles import extract_cycles, _participant_key
from exclusion_list import EXCLUDED_PARTICIPANT_CODES, EXCLUDED_DEVICE_IDS


# ── subplot ordering ──────────────────────────────────────────────────────────

_MODEL_ORDER = {
    'Vivoactive 5': 0,
    'Vivoactive 6': 1,
    'Venu 3S':      2,
    'Venu 4':       3,
}


def _sort_key(pkey, dev_data_map):
    """Sort key: (model_order, mst_int) for a participant key."""
    dev = dev_data_map[pkey]
    model = dev['watch_model'].dropna()
    mst   = dev['mst'].dropna()
    model_rank = _MODEL_ORDER.get(model.iloc[0], 99) if len(model) else 99
    try:
        mst_rank = int(mst.iloc[0]) if len(mst) else 99
    except (ValueError, TypeError):
        mst_rank = 99
    return (model_rank, mst_rank)


# ── exclusion ─────────────────────────────────────────────────────────────────

def _apply_exclusions(data):
    """Remove excluded participant_codes and device_ids from data."""
    mask = (
        data['participant_code'].isin(EXCLUDED_PARTICIPANT_CODES) |
        data['device_id'].isin(EXCLUDED_DEVICE_IDS)
    )
    excluded_rows = data[mask]
    excluded_labels = sorted(set(
        excluded_rows['participant_code'].dropna().tolist() +
        excluded_rows['device_id'].dropna().tolist()
    ))
    return data[~mask].reset_index(drop=True), excluded_labels


# ── helpers ───────────────────────────────────────────────────────────────────

def _is_charging_series(dev_data):
    """
    Return a boolean Series — True where a point is a charging step.
    Per-row: API rows use the 'charging' column; CSV rows infer from battery direction.
    Handles participants with both CSV and API data mixed together.
    """
    import numpy as np
    direction = dev_data['bat'].diff().fillna(0)
    from_direction = direction > 0
    if 'charging' in dev_data.columns and 'data_source' in dev_data.columns:
        api_mask     = (dev_data['data_source'] == 'api').values
        from_col     = dev_data['charging'].fillna(0).astype(bool).values
        return pd.Series(np.where(api_mask, from_col, from_direction.values),
                         index=dev_data.index)
    return from_direction


def _subplot_label(dev_data):
    """Return subplot title: participant_code if known, else short device_id."""
    pc = dev_data['participant_code'].dropna()
    if len(pc):
        return pc.iloc[0]
    did = dev_data['device_id'].dropna()
    return (str(did.iloc[0])[:8] + '…') if len(did) else 'unknown'


def _subplot_annotation(dev_data):
    """Return top-right annotation string: 'MST X  |  Watch Model'."""
    mst   = dev_data['mst'].dropna()
    model = dev_data['watch_model'].dropna()
    mst_str   = f"MST {mst.iloc[0]}" if len(mst) else ''
    model_str = model.iloc[0] if len(model) else ''
    if mst_str and model_str:
        return f"{mst_str}  |  {model_str}"
    return mst_str or model_str


def _draw_segments(ax, dev_data, color):
    """Draw charge (dashed black) / discharge (coloured fill) segments.

    - API: charging column drives segment breaks; clean line, no markers.
    - CSV: direction-based; annotate each point with '{bat}%'.
    """
    ts       = dev_data['timestamp'].reset_index(drop=True)
    bp       = dev_data['bat'].reset_index(drop=True)
    charging = _is_charging_series(dev_data.reset_index(drop=True))

    seg_start = 0
    for j in range(1, len(ts) + 1):
        at_end   = j == len(ts)
        boundary = at_end or (charging.iloc[j] != charging.iloc[seg_start])
        if boundary:
            seg_ts     = ts.iloc[seg_start:j]
            seg_bp     = bp.iloc[seg_start:j]
            is_chg_seg = charging.iloc[seg_start]

            if is_chg_seg:
                ax.plot(seg_ts, seg_bp, color='black', lw=1.2, ls='--', zorder=3)
            else:
                ax.plot(seg_ts, seg_bp, color=color, lw=1.5, zorder=3)
                ax.fill_between(seg_ts, seg_bp, alpha=0.2, color=color)

            seg_start = j - 1

    # CSV rows: label each point with its battery %; API rows: no label
    for _, row in dev_data.iterrows():
        if row.get('data_source', 'csv') == 'csv':
            ax.annotate(f"{int(row['bat'])}%",
                        xy=(row['timestamp'], row['bat']),
                        xytext=(0, 6), textcoords='offset points',
                        fontsize=6, ha='center', color='#333333', zorder=4)


# ── annotated matplotlib plot ─────────────────────────────────────────────────

def plot_annotated(data, save_path="battery_annotated.png"):
    """Matplotlib plot with discharge cycle boxes and config event lines."""
    data, excluded_labels = _apply_exclusions(data)

    all_cycles = extract_cycles(data)

    rates = [c['hourly_rate'] for c in all_cycles] if all_cycles else []
    _cmap = plt.cm.RdYlGn_r
    _vmin, _vmax = (min(rates), max(rates)) if len(rates) > 1 else (0, 1)
    _norm = mcolors.Normalize(vmin=_vmin, vmax=_vmax)

    def _cycle_color(hourly_rate):
        return _cmap(_norm(hourly_rate))

    data = data.copy()
    data['_pkey'] = data.apply(_participant_key, axis=1)
    pkeys = data['_pkey'].unique().tolist()

    # Build per-pkey data map for sort key lookup
    dev_data_map = {pk: data[data['_pkey'] == pk] for pk in pkeys}
    pkeys = sorted(pkeys, key=lambda pk: _sort_key(pk, dev_data_map))

    n_pkeys = len(pkeys)
    fig, axes = plt.subplots(n_pkeys, 1, figsize=(18, 5 * n_pkeys),
                             sharex=True, sharey=True)
    if n_pkeys == 1:
        axes = [axes]

    x_min = data['timestamp'].min()
    x_max = data['timestamp'].max()

    cycles_by_pkey = {}
    for c in all_cycles:
        cycles_by_pkey.setdefault(c['participant_key'], []).append(c)

    for i, (ax, pkey) in enumerate(zip(axes, pkeys)):
        dev_data = dev_data_map[pkey].sort_values('timestamp').reset_index(drop=True)
        color    = PALETTE[i % len(PALETTE)]

        _draw_segments(ax, dev_data, color)

        # cycle annotation boxes
        bracket_top = 113
        for c in cycles_by_pkey.get(pkey, []):
            s_ts, e_ts = c['start_ts'], c['end_ts']
            mid_ts = s_ts + (e_ts - s_ts) / 2
            mid_bp = (c['start_bp'] + c['end_bp']) / 2
            era    = c['era']

            ax.plot([s_ts, s_ts], [bracket_top - 4, bracket_top], color='#555555', lw=0.8)
            ax.plot([e_ts, e_ts], [bracket_top - 4, bracket_top], color='#555555', lw=0.8)
            ax.plot([s_ts, e_ts], [bracket_top, bracket_top],     color='#555555', lw=0.8)

            days_life = round(100 / c['daily_rate'], 1) if c['daily_rate'] else '—'
            label = (f"Cycle {c['cycle_idx']} {ERA_MARKERS.get(era, '?')}\n"
                     f"{c['start_bp']}% → {c['end_bp']}%\n"
                     f"{c['hourly_rate']}%/hr\n"
                     f"({c['daily_rate']}%/day)\n"
                     f"{days_life} days")
            ax.text(mid_ts, bracket_top + 1, label,
                    ha='center', va='bottom', fontsize=5.5, color='#222222',
                    bbox=dict(boxstyle='round,pad=0.35',
                              fc=_cycle_color(c['hourly_rate']),
                              ec='#aaaaaa', alpha=0.92), zorder=6)
            ax.annotate('', xy=(mid_ts, mid_bp), xytext=(mid_ts, bracket_top),
                        arrowprops=dict(arrowstyle='->', color='#888888',
                                        lw=0.8, connectionstyle='arc3,rad=0.0'),
                        zorder=5)

        # config event lines
        for event_name, event_ts in CONFIG_SORTED:
            lc = CONFIG_LINE_COLORS[event_name]
            ax.axvline(event_ts, color=lc, lw=1.2, ls=':', alpha=0.9, zorder=5)
            ax.text(event_ts, 106, f' {event_name}→',
                    fontsize=5, color=lc, va='top', ha='left')

        # night shading 00:00–06:00
        current = x_min.normalize()
        while current <= x_max:
            ax.axvspan(current, current + pd.Timedelta(hours=6),
                       color='grey', alpha=0.08, zorder=0)
            current += pd.Timedelta(hours=24)

        title_str = _subplot_label(dev_data)
        annot_str = _subplot_annotation(dev_data)
        ax.set_title(title_str, fontsize=9, loc='left', pad=3, fontweight='bold')
        if annot_str:
            ax.text(0.99, 0.97, annot_str, transform=ax.transAxes,
                    fontsize=7, va='top', ha='right', color='#444444')

        ax.set_ylabel("Battery %", fontsize=8)
        ax.set_ylim(0, 135)
        ax.set_yticks([0, 25, 50, 75, 100])
        ax.spines[['top', 'right']].set_visible(False)
        ax.yaxis.grid(True, ls='--', lw=0.3, alpha=0.4, color='grey')
        ax.xaxis.grid(False)
        ax.set_axisbelow(True)

    axes[0].set_xlim(x_min, x_max)
    for ax in axes:
        ax.xaxis.set_major_locator(mdates.DayLocator())
        ax.xaxis.set_major_formatter(mdates.DateFormatter('%-d %b'))
        ax.tick_params(axis='x', labelsize=7, rotation=0, labelbottom=True)

    legend_elements = (
        [
            mpatches.Patch(fc=_cmap(0.0), ec='#aaaaaa', label=f'Low drain ({min(rates):.1f}%/hr)'),
            mpatches.Patch(fc=_cmap(0.5), ec='#aaaaaa', label='Mid drain'),
            mpatches.Patch(fc=_cmap(1.0), ec='#aaaaaa', label=f'High drain ({max(rates):.1f}%/hr)'),
        ] if rates else []
    ) + [
        plt.Line2D([0], [0], color='black', lw=1.2, ls='--', label='Charging'),
    ] + [
        plt.Line2D([0], [0], color=lc, lw=1.2, ls=':', label=name)
        for name, lc in CONFIG_LINE_COLORS.items()
    ]
    fig.legend(handles=legend_elements, loc='upper right', fontsize=8, framealpha=0.9, ncol=3)
    fig.suptitle("Battery % Over Time — Cycle Annotations", fontsize=13, y=1.005)

    # Discrete exclusion banner at top of figure
    if excluded_labels:
        excl_str = "Excluded: " + ", ".join(str(x) for x in excluded_labels)
        fig.text(0.01, 1.002, excl_str, fontsize=6.5, color='#888888',
                 va='bottom', ha='left', style='italic',
                 transform=fig.transFigure)

    fig.tight_layout()
    plt.savefig(save_path, dpi=150, bbox_inches='tight')
    print(f"Saved: {save_path}")
    subprocess.run(['open', save_path])
    plt.close()


# ── interactive plotly plot ───────────────────────────────────────────────────

def _compute_hover_stats(dev_data):
    bp  = dev_data['bat'].values
    ts  = dev_data['timestamp'].values
    hover_texts = []
    for idx in range(len(dev_data)):
        ts_str = pd.Timestamp(ts[idx]).strftime('%d %b %H:%M')
        bp_val = int(bp[idx])
        if idx == 0:
            hover_texts.append(f"<b>{ts_str}</b><br>Battery: {bp_val}%<br><i>First log</i>")
            continue
        delta_pct = float(bp[idx]) - float(bp[idx - 1])
        delta_hrs = (pd.Timestamp(ts[idx]) - pd.Timestamp(ts[idx - 1])).total_seconds() / 3600
        if delta_hrs == 0:
            hover_texts.append(f"<b>{ts_str}</b><br>Battery: {bp_val}%<br><i>Same timestamp</i>")
            continue
        hourly    = delta_pct / delta_hrs
        sign      = "+" if delta_pct > 0 else ""
        direction = "▲ Charging" if delta_pct > 0 else "▼ Discharging"
        hover_texts.append(
            f"<b>{ts_str}</b><br>Battery: {bp_val}%<br>──────────────<br>"
            f"{direction}<br>Change: {sign}{delta_pct:.1f}% over {delta_hrs:.1f}h<br>"
            f"Hourly: {sign}{hourly:.2f}%/hr<br>Daily: {sign}{hourly*24:.1f}%/day"
        )
    return hover_texts


def plot_interactive(data, save_path="battery_interactive.html"):
    """Plotly interactive chart with hover stats and config event lines."""
    data, _ = _apply_exclusions(data)

    data = data.copy()
    data['_pkey'] = data.apply(_participant_key, axis=1)
    pkeys = data['_pkey'].unique().tolist()

    dev_data_map = {pk: data[data['_pkey'] == pk] for pk in pkeys}
    pkeys = sorted(pkeys, key=lambda pk: _sort_key(pk, dev_data_map))
    n_pkeys = len(pkeys)

    fig = make_subplots(rows=n_pkeys, cols=1, shared_xaxes=True,
                        vertical_spacing=0.03,
                        subplot_titles=[_subplot_label(dev_data_map[pk]) for pk in pkeys])

    x_min = data['timestamp'].min()
    x_max = data['timestamp'].max()

    for i, pkey in enumerate(pkeys):
        row      = i + 1
        color    = PALETTE[i % len(PALETTE)]
        r_, g_, b_ = int(color[1:3], 16), int(color[3:5], 16), int(color[5:7], 16)
        fill_color = f'rgba({r_},{g_},{b_},0.18)'

        dev_data    = dev_data_map[pkey].sort_values('timestamp').reset_index(drop=True)
        ts          = dev_data['timestamp']
        bp          = dev_data['bat']
        hover_texts = _compute_hover_stats(dev_data)
        charging    = _is_charging_series(dev_data)

        seg_start = 0
        for j in range(1, len(dev_data) + 1):
            at_end   = j == len(dev_data)
            boundary = at_end or (charging.iloc[j] != charging.iloc[seg_start])
            if boundary:
                seg_ts     = ts.iloc[seg_start:j].tolist()
                seg_bp     = bp.iloc[seg_start:j].tolist()
                seg_hover  = hover_texts[seg_start:min(j, len(hover_texts))]
                is_chg_seg = charging.iloc[seg_start]

                fig.add_trace(go.Scatter(
                    x=seg_ts, y=seg_bp,
                    mode='lines',
                    line=dict(color='black' if is_chg_seg else color,
                              width=2, dash='dash' if is_chg_seg else 'solid'),
                    fill='tozeroy' if not is_chg_seg else None,
                    fillcolor=fill_color if not is_chg_seg else None,
                    hovertemplate="%{text}<extra></extra>",
                    text=seg_hover, showlegend=False,
                ), row=row, col=1)
                seg_start = j - 1

        # config event lines
        for event_name, event_ts in CONFIG_SORTED:
            lc = CONFIG_LINE_COLORS[event_name]
            fig.add_trace(go.Scatter(
                x=[event_ts, event_ts], y=[0, 105],
                mode='lines',
                line=dict(color=lc, width=1.5, dash='dot'),
                hovertemplate=f'{event_name}<extra></extra>',
                showlegend=False,
            ), row=row, col=1)

        # night shading
        current = x_min.normalize()
        while current <= x_max:
            fig.add_vrect(x0=current, x1=current + pd.Timedelta(hours=6),
                          fillcolor="grey", opacity=0.07, layer="below",
                          line_width=0, row=row, col=1)
            current += pd.Timedelta(hours=24)

        fig.update_yaxes(range=[0, 105], tickvals=[0, 50, 100],
                         ticksuffix='%', tickfont=dict(size=9),
                         gridcolor='rgba(180,180,180,0.25)', showgrid=True,
                         row=row, col=1)

    fig.update_xaxes(dtick=6 * 3600 * 1000, tickformat='%d %b\n%H:%M',
                     showticklabels=True, tickfont=dict(size=8), showgrid=False)
    fig.update_layout(height=320 * n_pkeys,
                      title=dict(text="Battery % Over Time", font=dict(size=14)),
                      hovermode='closest', plot_bgcolor='white',
                      paper_bgcolor='white', showlegend=False,
                      margin=dict(l=60, r=30, t=60, b=40))

    fig.write_html(save_path)
    print(f"Saved: {save_path}")
    subprocess.run(['open', save_path])
