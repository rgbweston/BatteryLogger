import pandas as pd

# ── Config change events ───────────────────────────────────────────────────────
# Full study history — add new entries here as the study progresses.

CONFIG_EVENTS = {
    'SpO2 All-Day':     pd.Timestamp('2026-03-17 12:00:00'),
    'SDK All Off':      pd.Timestamp('2026-03-18 17:30:00'),
    'SDK All On':       pd.Timestamp('2026-03-19 12:15:00'),
    'Acc/Gyro Off':     pd.Timestamp('2026-03-23 15:42:00'),
    'Acc/Gyro/BBI Off': pd.Timestamp('2026-03-25 13:30:00'),
    'Derived Off':      pd.Timestamp('2026-03-26 17:00:00'),
    '↓ Logging':        pd.Timestamp('2026-03-30 15:04:00'),
    'SDK All On #2':    pd.Timestamp('2026-04-01 15:19:00'),
    'SDK All Off #2':   pd.Timestamp('2026-04-14 15:17:00'),
    'Only HR':          pd.Timestamp('2026-04-14 17:52:00'),
    'SDK All On #3':    pd.Timestamp('2026-04-14 21:30:00')
}

CONFIG_SORTED = sorted(CONFIG_EVENTS.items(), key=lambda x: x[1])

# ── Era styling ───────────────────────────────────────────────────────────────

ERA_COLORS = {
    'Pre SpO2':             'lightyellow',
    'Post SpO2 All-Day':    '#ffe0e0',
    'Post SDK All Off':     '#f0e0ff',
    'Post SDK All On':      '#e0f0e0',
    'Post Acc/Gyro Off':    '#e0f4ff',
    'Post Acc/Gyro/BBI Off':'#d0e8ff',
    'Post Derived Off':     '#fff0d0',
    'Post ↓ Logging':       '#f0fff0',
    'Post SDK All On #2':   '#c8f0c8',
    'Post SDK All Off #2': '#f0d0d0',
    'Post SDK All On #3':  '#c8f5c8',
    'Post Only HR':        '#e8d0f0',
}

ERA_MARKERS = {
    'Pre SpO2':             '○',
    'Post SpO2 All-Day':    '●',
    'Post SDK All Off':     '◆',
    'Post SDK All On':      '★',
    'Post Acc/Gyro Off':    '▲',
    'Post Acc/Gyro/BBI Off':'■',
    'Post Derived Off':     '◇',
    'Post ↓ Logging':       '▽',
    'Post SDK All On #2':   '★',
    'Post SDK All Off #2':  '◆',
    'Post SDK All On #3':   '★',
    'Post Only HR':         '♥',
}

ERA_LABEL_MAP = {
    'Pre SpO2':             'Initial',
    'Post SpO2 All-Day':    'SpO2 All Day',
    'Post SDK All Off':     'SDK Off',
    'Post SDK All On':      'SDK All On',
    'Post Acc/Gyro Off':    'Acc/Gyro Off',
    'Post Acc/Gyro/BBI Off':'Acc/Gyro/BBI Off',
    'Post Derived Off':     'Derived Off',
    'Post ↓ Logging':       '↓ Logging',
    'Post SDK All On #2':   'SDK All On #2',
    'Post SDK All Off #2':  'SDK All Off #2',
    'Post SDK All On #3':   'SDK All On #3',
    'Post Only HR':         'Only HR',
}

CONFIG_LINE_COLORS = {
    'SpO2 All-Day':     '#cc0000',
    'SDK All Off':      '#7b0000',
    'SDK All On':       '#006600',
    'Acc/Gyro Off':     '#0055aa',
    'Acc/Gyro/BBI Off': '#00008b',
    'Derived Off':      '#cc6600',
    '↓ Logging':        '#9b59b6',
    'SDK All On #2':    '#00aa44',
    'SDK All Off #2':   '#aa0000',
    'SDK All On #3':    '#00cc55',
    'Only HR':          '#8833cc',
}

# ── Plot palette ──────────────────────────────────────────────────────────────

PALETTE = [
    '#1f77b4', '#ff7f0e', '#2ca02c', '#d62728', '#9467bd',
    '#8c564b', '#e377c2', '#7f7f7f', '#bcbd22', '#17becf',
    '#aec7e8', '#ffbb78',
]
