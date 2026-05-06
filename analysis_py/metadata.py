# metadata.py
# Single source of truth for all participant/device info.
#
# device_id: hash from the BatteryLogger watch app (leave as None until the
#            watch has synced at least once and you can look it up).
#
# participant_code: links back to the battery_report CSV data.

PARTICIPANTS = [
    {
        'participant_code': None,
        'participant_name': 'Liza Pekosak',
        'mst':              '4',
        'watch_model':      'Vivoactive 5',
        'device_id':        '727287ece99f866e56f84b53c3887b040aee29f3',
        'study_start':      None,
    },
    {
        'participant_code': None,
        'participant_name': 'Rohan Barrowcliff',
        'mst':              '2',
        'watch_model':      'Vivoactive 6',
        'device_id':        '0457c34ac33a3bc3ee0196003561d39b6b9a4080',
        'study_start':      None,
    },
    {
        'participant_code': 'clever-gecko-71',
        'participant_name': None,
        'mst':              '2',
        'watch_model':      'Vivoactive 5',
        'device_id':        None,
        'study_start':      None,
    },
    {
        'participant_code': 'cool-seal-27',
        'participant_name': 'Xiaoyu Zheng',
        'mst':              '3',
        'watch_model':      'Venu 4 41mm',
        'device_id':        '997a99dd411177745a9e99c8b61b410febdb26d3',
        'study_start':      None,
    },
    {
        'participant_code': None,
        'participant_name': 'Xiaoyu Zheng',
        'mst':              '3',
        'watch_model':      'Venu 4 45mm',
        'device_id':        'fb947d3c61491c139176d0cc2ea98cee6d214393',
        'study_start':      None,
    },
    {
        'participant_code': 'fierce-newt-7',
        'participant_name': 'Rohan Barrowcliff',
        'mst':              '2',
        'watch_model':      'Vivoactive 5',
        'device_id':        '82af553af94a99f25b403e73cb6e2c6edbd04919',
        'study_start':      None,
    },
    {
        'participant_code': 'fierce-owl-1',
        'participant_name': 'Benard Bene',
        'mst':              '7',
        'watch_model':      'Vivoactive 5',
        'device_id':        '4d4c82eaef432d2ddbc7448a662134e285b70b85',
        'study_start':      None,
    },
    {
        'participant_code': 'gentle-owl-208',
        'participant_name': 'Liza Pekosak',
        'mst':              '4',
        'watch_model':      'Venu 4 41mm',
        'device_id':        None,
        'study_start':      None,
    },
    {
        'participant_code': 'gentle-owl-33',
        'participant_name': 'John Daniels',
        'mst':              '7',
        'watch_model':      'Vivoactive 6',
        'device_id':        None,
        'study_start':      None,
    },
    {
        'participant_code': 'jolly-seal-25',
        'participant_name': 'Roselinde?',
        'mst':              '7',
        'watch_model':      'Venu 4 41mm',
        'device_id':        None,
        'study_start':      None,
    },
    {
        'participant_code': 'keen-hawk-4',
        'participant_name': 'Sabrina Demirdjian',
        'mst':              '5',
        'watch_model':      'Venu 3S',
        'device_id':        'e3b9d5c770b359892b7911839eb8e870b22fe559',
        'study_start':      None,
    },
    {
        'participant_code': 'merry-moose-23',
        'participant_name': 'Roselinde?',
        'mst':              '2',
        'watch_model':      'Venu 4 41mm',
        'device_id':        None,
        'study_start':      None,
    },
    {
        'participant_code': 'merry-panda-18',
        'participant_name': 'Eric Auyoung',
        'mst':              '3',
        'watch_model':      'Venu 3S',
        'device_id':        '3f727e94476661dac969cbb771b1a119eaab225b',
        'study_start':      None,
    },
    {
        'participant_code': 'noble-numbat-5',
        'participant_name': None,
        'mst':              '3',
        'watch_model':      'Venu 4',
        'device_id':        None,
        'study_start':      None,
    },
    {
        'participant_code': 'plucky-bison-10',
        'participant_name': None,
        'mst':              '5',
        'watch_model':      'Venu 3S',
        'device_id':        None,
        'study_start':      None,
    },
    {
        'participant_code': 'quick-otter-3',
        'participant_name': 'Emma Raywood',
        'mst':              '4',
        'watch_model':      'Vivoactive 6',
        'device_id':        '182fe10af4611e572f80124619c02bde653c1b64',
        'study_start':      None,
    },
    {
        'participant_code': 'snappy-seal-7',
        'participant_name': None,
        'mst':              '5',
        'watch_model':      'Venu 3S',
        'device_id':        None,
        'study_start':      None,
    },
    {
        'participant_code': 'trusty-koala-846',
        'participant_name': None,
        'mst':              '4',
        'watch_model':      'Vivoactive 5',
        'device_id':        None,
        'study_start':      None,
    },
    {
        'participant_code': 'warm-fox-8',
        'participant_name': None,
        'mst':              '2',
        'watch_model':      'Venu 4',
        'device_id':        None,
        'study_start':      None,
    },
    {
        'participant_code': 'wise-fox-66',
        'participant_name': None,
        'mst':              '3',
        'watch_model':      'Vivoactive 6',
        'device_id':        None,
        'study_start':      None,
    },
    {
        'participant_code': None,
        'participant_name': 'Runcong Zhao',
        'mst':              '3',
        'watch_model':      'Vivoactive 5',
        'device_id':        '504ee0cf39ff7ffc6a6302463ad7a4fbd5c639af',
        'study_start':      None,
    },
    {
        'participant_code': None,
        'participant_name': 'Yiwei Ji',
        'mst':              '2',
        'watch_model':      'Vivoactive 6',
        'device_id':        '04376431f8bce5d2a81e8b2bd5953ae0e0aa43a4',
        'study_start':      None,
    },
    {
        'participant_code': None,
        'participant_name': 'John Daniels',
        'mst':              '6',
        'watch_model':      'Venu 3S',
        'device_id':        '39492696cac7db14c5dd1102ebb468c79304c3fb',
        'study_start':      None,
    },
    {
        'participant_code': None,
        'participant_name': 'Mary Abichi',
        'mst':              '7',
        'watch_model':      'Venu 4 41mm',
        'device_id':        'b63b6eb396d0801216f2f9de1c114675ee84592b',
        'study_start':      None,
    },
    {
        'participant_code': None,
        'participant_name': 'Xinyu Wang',
        'mst':              '3',
        'watch_model':      'Venu 3S',
        'device_id':        '98a5acccfb6f99af1b98ab4459b6fce647598e51',
        'study_start':      None,
    }
]

# ── Part number → model name ──────────────────────────────────────────────────
# Extracted from SDK compiler.json files. Regional variants (APAC etc.) may have
# different last two digits — unrecognised values fall back to the raw part number.

PART_NUMBER_MODELS = {
    '006-B4426-00': 'Vivoactive 5',
    '006-B4625-00': 'Vivoactive 6',
    '006-B4261-00': 'Venu 3S',
    '006-B4644-00': 'Venu 4 41mm',
    '006-B4643-00': 'Venu 4 45mm',
}

# ── Lookup helpers ────────────────────────────────────────────────────────────

# Keyed by device_id for fast lookup from API data (excludes None device_ids)
BY_DEVICE_ID = {
    p['device_id']: p
    for p in PARTICIPANTS
    if p['device_id'] is not None
}

# Keyed by participant_code for fast lookup from CSV data (excludes None codes)
BY_PARTICIPANT_CODE = {
    p['participant_code']: p
    for p in PARTICIPANTS
    if p['participant_code'] is not None
}
