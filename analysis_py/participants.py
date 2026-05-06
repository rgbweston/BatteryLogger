# participants.py — Study participant roster.
# One entry per person. 'name' is the real name if known, else the participant
# code. 'mst' is the Monk Skin Tone (1–10), or None if unknown.

PARTICIPANTS = [
    # ── Named participants ────────────────────────────────────────────────────
    {'name': 'Benard Bene',        'mst': '7'},
    {'name': 'Emma Raywood',       'mst': '4'},
    {'name': 'Eric Auyoung',       'mst': '3'},
    {'name': 'John Daniels',       'mst': '6'},   # NOTE: gentle-owl-33 entry has MST 7 — verify
    {'name': 'Liza Pekosak',       'mst': '4'},
    {'name': 'Mary Abichi',        'mst': '7'},
    {'name': 'Rohan Barrowcliff',  'mst': '2'},
    {'name': 'Runcong Zhao',       'mst': '3'},
    {'name': 'Sabrina Demirdjian', 'mst': '5'},
    {'name': 'Xiaoyu Zheng',       'mst': '3'},
    {'name': 'Xinyu Wang',         'mst': '3'},
    {'name': 'Yiwei Ji',           'mst': '2'},
    # ── Participants with uncertain identity ──────────────────────────────────
    # jolly-seal-25 and merry-moose-23 both labelled "Roselinde?" but have
    # conflicting MSTs (7 and 2) — may be two different people; verify.
    {'name': 'jolly-seal-25',      'mst': '7'},
    {'name': 'merry-moose-23',     'mst': '2'},
    # ── Participants known only by code ───────────────────────────────────────
    {'name': 'clever-gecko-71',    'mst': '2'},
    {'name': 'noble-numbat-5',     'mst': '3'},
    {'name': 'plucky-bison-10',    'mst': '5'},
    {'name': 'snappy-seal-7',      'mst': '5'},
    {'name': 'trusty-koala-846',   'mst': '4'},
    {'name': 'warm-fox-8',         'mst': '2'},
    {'name': 'wise-fox-66',        'mst': '3'},
]
