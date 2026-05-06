# device_models.py — Garmin part number → watch model name.
# Extracted from SDK compiler.json files.
# Regional variants (APAC etc.) may differ in the last two digits;
# unrecognised part numbers fall back to the raw string elsewhere.

PART_NUMBER_MODELS = {
    '006-B4426-00': 'Vivoactive 5',
    '006-B4625-00': 'Vivoactive 6',
    '006-B4260-00': 'Venu 3',
    '006-B4261-00': 'Venu 3S',
    '006-B4644-00': 'Venu 4 41mm',
    '006-B4643-00': 'Venu 4 45mm',
}
