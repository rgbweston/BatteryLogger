"""
zoom.py — 4-day zoomed battery plot centred on a specific day/hour.

Usage:
    python zoom.py                        # centre on current hour
    python zoom.py --day 2026-04-12             # centre on noon of that day
    python zoom.py --day 2026-04-12 --hour 15  # centre on 15:00 that day
    python zoom.py --day 2026-04-12 --hour 15 --minute 23  # centre on 15:23

The plot shows ±2 days around the centre point with hourly x-axis ticks.
"""

import argparse
import subprocess
import pandas as pd
import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt
import matplotlib.dates as mdates
import matplotlib.patches as mpatches
import matplotlib.colors as mcolors

from load import load_all
from config import CONFIG_SORTED, CONFIG_LINE_COLORS, ERA_MARKERS, PALETTE
from cycles import extract_cycles, _participant_key
from exclusion_list import EXCLUDED_PARTICIPANT_CODES, EXCLUDED_DEVICE_IDS

_MODEL_ORDER = {
    'Vivoactive 5': 0,
    'Vivoactive 6': 1,
    'Venu 3S':      2,
    'Venu 4':       3,
}


def _sort_key(pkey, dev_data_map):
    dev   = dev_data_map[pkey]
    model = dev['watch_model'].dropna()
    mst   = dev['mst'].dropna()
    model_rank = _MODEL_ORDER.get(model.iloc[0], 99) if len(model) else 99
    try:
        mst_rank = int(mst.iloc[0]) if len(mst) else 99
    except (ValueError, TypeError):
        mst_rank = 99
    return (model_rank, mst_rank)


def _apply_exclusions(data):
    mask = (
        data['participant_code'].isin(EXCLUDED_PARTICIPANT_CODES) |
        data['device_id'].isin(EXCLUDED_DEVICE_IDS)
    )
    excluded_rows  = data[mask]
    excluded_labels = sorted(set(
        excluded_rows['participant_code'].dropna().tolist() +
        excluded_rows['device_id'].dropna().tolist()
    ))
    return data[~mask].reset_index(drop=True), excluded_labels


def _is_charging_series(dev_data):
    import numpy as np
    direction    = dev_data['bat'].diff().fillna(0)
    from_direction = direction > 0
    if 'charging' in dev_data.columns and 'data_source' in dev_data.columns:
        api_mask = (dev_data['data_source'] == 'api').values
        from_col = dev_data['charging'].fillna(0).astype(bool).values
        return pd.Series(np.where(api_mask, from_col, from_direction.values),
                         index=dev_data.index)
    return from_direction


def _subplot_label(dev_data):
    pc = dev_data['participant_code'].dropna()
    if len(pc):
        return pc.iloc[0]
    did = dev_data['device_id'].dropna()
    return (str(did.iloc[0])[:8] + '…') if len(did) else 'unknown'


def _subplot_annotation(dev_data):
    mst   = dev_data['mst'].dropna()
    model = dev_data['watch_model'].dropna()
    mst_str   = f"MST {mst.iloc[0]}" if len(mst) else ''
    model_str = model.iloc[0] if len(model) else ''
    if mst_str and model_str:
        return f"{mst_str}  |  {model_str}"
    return mst_str or model_str


def _draw_segments(ax, dev_data, color):
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
                ax.plot(seg_ts, seg_bp, color='black', lw=1.5, ls='--', zorder=3)
            else:
                ax.plot(seg_ts, seg_bp, color=color, lw=2.0, zorder=3)
                ax.fill_between(seg_ts, seg_bp, alpha=0.2, color=color)

            seg_start = j - 1

    for _, row in dev_data.iterrows():
        if row.get('data_source', 'csv') == 'csv':
            ax.annotate(f"{int(row['bat'])}%",
                        xy=(row['timestamp'], row['bat']),
                        xytext=(0, 6), textcoords='offset points',
                        fontsize=6, ha='center', color='#333333', zorder=4)


def plot_zoom(centre: pd.Timestamp, save_path="battery_zoom.png"):
    x_min = centre - pd.Timedelta(days=2)
    x_max = centre + pd.Timedelta(days=2)

    data = load_all()
    data, excluded_labels = _apply_exclusions(data)

    # Grab a slightly wider slice for context (so segments near the edge aren't clipped)
    window = data[(data['timestamp'] >= x_min - pd.Timedelta(hours=1)) &
                  (data['timestamp'] <= x_max + pd.Timedelta(hours=1))].copy()

    if window.empty:
        print(f"No data in window {x_min:%Y-%m-%d %H:%M} → {x_max:%Y-%m-%d %H:%M}")
        return

    all_cycles = extract_cycles(window)
    rates      = [c['hourly_rate'] for c in all_cycles] if all_cycles else [0, 1]
    _cmap      = plt.cm.RdYlGn_r
    _norm      = mcolors.Normalize(vmin=min(rates), vmax=max(rates))

    def _cycle_color(hourly_rate):
        return _cmap(_norm(hourly_rate))

    window['_pkey'] = window.apply(_participant_key, axis=1)
    pkeys = window['_pkey'].unique().tolist()

    dev_data_map = {pk: window[window['_pkey'] == pk] for pk in pkeys}
    pkeys = sorted(pkeys, key=lambda pk: _sort_key(pk, dev_data_map))

    n_pkeys = len(pkeys)
    fig, axes = plt.subplots(n_pkeys, 1, figsize=(20, 4 * n_pkeys),
                             sharex=True, sharey=True)
    if n_pkeys == 1:
        axes = [axes]

    cycles_by_pkey = {}
    for c in (all_cycles or []):
        cycles_by_pkey.setdefault(c['participant_key'], []).append(c)

    for i, (ax, pkey) in enumerate(zip(axes, pkeys)):
        dev_data = dev_data_map[pkey].sort_values('timestamp').reset_index(drop=True)
        color    = PALETTE[i % len(PALETTE)]

        _draw_segments(ax, dev_data, color)

        # cycle annotation boxes (only if within window)
        bracket_top = 113
        for c in cycles_by_pkey.get(pkey, []):
            s_ts, e_ts = c['start_ts'], c['end_ts']
            if e_ts < x_min or s_ts > x_max:
                continue
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
            if not (x_min <= event_ts <= x_max):
                continue
            lc = CONFIG_LINE_COLORS[event_name]
            ax.axvline(event_ts, color=lc, lw=1.5, ls=':', alpha=0.9, zorder=5)
            ax.text(event_ts, 106, f' {event_name}→',
                    fontsize=6, color=lc, va='top', ha='left')

        # night shading 00:00–06:00
        current = x_min.normalize()
        while current <= x_max:
            ax.axvspan(current, current + pd.Timedelta(hours=6),
                       color='grey', alpha=0.08, zorder=0)
            current += pd.Timedelta(hours=24)

        # centre-point marker
        ax.axvline(centre, color='#cc6600', lw=1.2, ls='-', alpha=0.5, zorder=4)

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
        ax.xaxis.grid(True, ls=':', lw=0.3, alpha=0.3, color='grey')
        ax.set_axisbelow(True)

    axes[0].set_xlim(x_min, x_max)
    for ax in axes:
        ax.xaxis.set_major_locator(mdates.HourLocator(interval=6))
        ax.xaxis.set_major_formatter(mdates.DateFormatter('%-d %b\n%H:%M'))
        ax.xaxis.set_minor_locator(mdates.HourLocator(interval=1))
        ax.tick_params(axis='x', which='major', labelsize=7, rotation=0, labelbottom=True)
        ax.tick_params(axis='x', which='minor', length=3)

    legend_elements = (
        [
            mpatches.Patch(fc=_cmap(0.0), ec='#aaaaaa', label=f'Low drain ({min(rates):.1f}%/hr)'),
            mpatches.Patch(fc=_cmap(0.5), ec='#aaaaaa', label='Mid drain'),
            mpatches.Patch(fc=_cmap(1.0), ec='#aaaaaa', label=f'High drain ({max(rates):.1f}%/hr)'),
        ] if len(rates) > 1 else []
    ) + [
        plt.Line2D([0], [0], color='black', lw=1.2, ls='--', label='Charging'),
    ] + [
        plt.Line2D([0], [0], color=lc, lw=1.2, ls=':', label=name)
        for name, lc in CONFIG_LINE_COLORS.items()
        if any(x_min <= ts <= x_max for _, ts in CONFIG_SORTED if _ == name)
    ]
    if legend_elements:
        fig.legend(handles=legend_elements, loc='upper right', fontsize=8,
                   framealpha=0.9, ncol=3)

    centre_str = centre.strftime('%Y-%m-%d %H:%M')
    fig.suptitle(f"Battery % — ±2 day window around {centre_str}",
                 fontsize=12, y=1.005)

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


if __name__ == "__main__":
    parser = argparse.ArgumentParser(
        description="Zoomed 4-day battery plot centred on a given day/hour."
    )
    parser.add_argument("--day",    type=str, default=None,
                        help="Centre date as YYYY-MM-DD (default: today)")
    parser.add_argument("--hour",   type=int, default=None,
                        help="Centre hour 0–23 (default: current hour)")
    parser.add_argument("--minute", type=int, default=None,
                        help="Centre minute 0–59 (default: current minute)")
    args = parser.parse_args()

    now = pd.Timestamp.now()
    day    = pd.Timestamp(args.day) if args.day else now.normalize()
    hour   = args.hour   if args.hour   is not None else now.hour
    minute = args.minute if args.minute is not None else now.minute
    centre = day.replace(hour=hour, minute=minute, second=0, microsecond=0)

    print(f"Centre: {centre:%Y-%m-%d %H:%M}  |  window: "
          f"{centre - pd.Timedelta(days=2):%d %b} → "
          f"{centre + pd.Timedelta(days=2):%d %b}")

    plot_zoom(centre, save_path="battery_zoom.png")
