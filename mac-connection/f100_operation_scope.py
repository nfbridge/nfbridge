# SPDX-License-Identifier: GPL-3.0-only
"""Exact, additive operation descriptors. No device access or authorization."""
NEW_SCOPES = frozenset(('record-settings', 'erase-records'))
NP_VALUES = frozenset(('01', '02', '03', '09', '0a', '0b'))
LIVE_POLICY_REVISION = 'v0.7-manual-conformance-2026-09-13'


def validate_live_policy(value):
    """Require newly generated evidence; this marker is not user authentication."""
    if (value.get('candidate_live_blocked') is not False or
            value.get('live_policy_revision') != LIVE_POLICY_REVISION):
        raise ValueError('Live policy revision missing or candidate still blocked; create fresh evidence')


def descriptor(scope, payload_hex=None):
    if scope == 'record-settings' and type(payload_hex) is str and payload_hex in NP_VALUES:
        opcode = 'NP'
    elif scope == 'erase-records' and payload_hex is None:
        opcode, payload_hex = 'EP', ''
    else:
        raise ValueError('Unsupported operation or exact NP payload')
    return {'scope': scope, 'opcode': opcode, 'payload_hex': payload_hex,
            'maximum_write_attempts': 1, 'automatic_write_retry': False,
            'automatic_rollback': False, 'dp_implemented': False}


def validate(value, command):
    if not isinstance(value, dict) or command not in NEW_SCOPES:
        raise ValueError('Missing operation descriptor')
    expected = descriptor(command, value.get('payload_hex') if command == 'record-settings' else None)
    # Equality alone admits True==1; reject alternate JSON types as well.
    if value != expected or any(type(value.get(k)) is not type(v) for k, v in expected.items()):
        raise ValueError('Operation scope/opcode/payload mismatch')
    return dict(expected)
