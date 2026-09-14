# SPDX-License-Identifier: GPL-3.0-only
"""Check the exact export being kept before EP; roll numbers alone never match."""
from collections import Counter
import hashlib
import json
from pathlib import Path


class ArchiveIncomplete(ValueError):
    def __init__(self, report):
        self.report = report
        super().__init__('Camera record archive could not be verified')


def roll_key(mode, roll):
    return hashlib.sha256(json.dumps({'mode': mode, 'roll': roll}, ensure_ascii=False,
                                    sort_keys=True, separators=(',', ':')).encode()).hexdigest()


def inspect(directory, expected):
    """Re-read JSON and original payload, retaining duplicate roll occurrences."""
    directory = Path(directory)
    rolls = expected['rolls']
    result = {'archive': str(directory), 'total_rolls': len(rolls), 'verified_rolls': 0,
              'unverified_rolls': len(rolls), 'unverified_roll_numbers': [r['roll_number'] for r in rolls],
              'payload_verified': False, 'ok': False}
    path = directory / 'shooting-data.json'
    try:
        if directory.is_symlink() or path.is_symlink():
            raise ValueError('Archive path must not be a symlink')
        raw = path.read_bytes()
        saved = json.loads(raw)
        source = saved['_source']
        payload = bytes.fromhex(source['payload_hex'])
        expected_source = expected['_source']
        result['payload_verified'] = (
            hashlib.sha256(payload).hexdigest() == source['sha256'] == expected_source['sha256']
            and payload == bytes.fromhex(expected_source['payload_hex']))
        available = Counter(roll_key(saved['mode'], r) for r in saved['rolls'])
        missing = []
        for roll in rolls:
            key = roll_key(expected['mode'], roll)
            if result['payload_verified'] and available[key]:
                available[key] -= 1
            else:
                missing.append(roll['roll_number'])
        result.update(unverified_roll_numbers=missing, unverified_rolls=len(missing),
                      verified_rolls=len(rolls)-len(missing), archive_json_sha256=hashlib.sha256(raw).hexdigest())
        result['ok'] = (not missing and result['payload_verified'] and saved['mode'] == expected['mode']
                        and saved['roll_count'] == len(rolls) == len(saved['rolls']))
    except (OSError, ValueError, TypeError, KeyError):
        pass
    return result


def require(directory, expected):
    result = inspect(directory, expected)
    if not result['ok']:
        raise ArchiveIncomplete(result)
    return result
