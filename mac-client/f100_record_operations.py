# SPDX-License-Identifier: GPL-3.0-only
"""Single-operation workflow with exact binding and explicit confirmations.

The GUI adapter calls this workflow with separately bound operations.
Neither completion nor ACK alone is hardware validation.
"""
import hashlib
import json
from pathlib import Path
import sys
import time
import f100_readonly as ro
from f100_maintenance import (read_state, describe, save_new, validate_confirmation_source,
                              require_empty_settings_memory, confirm_counter_e)

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'mac-connection'))
import f100_operation_scope as scopes


def run(link, folder, confirm, *, actor, channel):
    """Backup, explicit review, full state recheck, one write, full read-back."""
    validate_confirmation_source(actor, channel)
    operation = scopes.validate(link.capture.integration.get('operation'), link.capture.command)
    if link.capture.operation_scope != operation['scope']:
        raise ro.ProtocolError('Workflow/capture scope mismatch')
    folder = Path(folder)
    before = read_state(link)
    target = int(operation['payload_hex'], 16) if operation['opcode'] == 'NP' else None
    if target is not None:
        # Do not infer semantics for status bits outside the verified settings mask.
        if before['mq'] & ~0x0b:
            raise ro.ProtocolError('Unknown MQ bits; no settings written')
        if before['mq'] & 0x0b == target:
            return {'status': 'unchanged', 'before': describe(before), 'write_attempts': 0}
        require_empty_settings_memory(before)
    backup = folder / 'backup-lq.bin'
    save_new(backup, before['payload'])
    digest = hashlib.sha256(before['payload']).hexdigest()
    save_new(folder / 'backup.json', json.dumps({'sha256': digest, **describe(before),
             'decoded': before['decoded']}, ensure_ascii=False, indent=2).encode())
    details = {'operation': operation, 'backup': str(backup), 'backup_sha256': digest,
               'before': describe(before)}
    answer = confirm(operation['scope'], details)
    accepted = answer is True
    link.capture.record('operation_confirmation', confirmed=accepted, actor=actor,
                        channel=channel, **details)
    if not accepted:
        return {'status': 'cancelled', 'write_attempts': 0, **details}
    if target is not None and not confirm_counter_e(link, confirm, actor=actor, channel=channel):
        return {'status': 'cancelled', 'reason': 'counter_e_not_confirmed', 'write_attempts': 0, **details}
    current = read_state(link)
    if target is not None:
        require_empty_settings_memory(current)
    if (current['mq'] != before['mq'] or current['payload'] != before['payload']
            or backup.read_bytes() != before['payload']):
        raise ro.ProtocolError('Camera or backup changed after review; nothing written')
    payload = bytes.fromhex(operation['payload_hex'])
    link.arm(operation['opcode'], payload)
    link.mutate(operation['opcode'], payload)
    after = read_state(link)
    if target is None:
        if (after['oq'] or len(after['payload']) != 1 or after['frames']
                or (after['mq'] & 0x0b) != (before['mq'] & 0x0b)):
            raise ro.ProtocolError('Empty memory or unchanged settings not verified; no retry')
    else:
        if ((after['mq'] & 0x0b) != target
                or (after['mq'] & ~0x0b) != (before['mq'] & ~0x0b)):
            raise ro.ProtocolError('Settings read-back mismatch; no retry')
        # Empty global mode byte is recorded, not used as a mode assertion.
        if before['oq'] == 0:
            if after['oq'] or len(after['payload']) != 1 or after['frames']:
                raise ro.ProtocolError('Memory changed during settings write; no retry')
        elif after['payload'] != before['payload']:
            raise ro.ProtocolError('Stored records changed during settings write; no retry')
    result = {'status': 'verified', 'write_attempts': 1, **details, 'after': describe(after)}
    if target is not None:
        result['recording_effective'] = 'next_film_advanced_to_first_frame'
    save_new(folder / 'result.json', json.dumps(result, ensure_ascii=False, indent=2).encode())
    link.capture.record('operation_verified', **result)
    return result


class OperationLink(ro.F100Link):
    """One exact NP or EP attempt; never uses read retry logic for writes."""
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self._armed = None
        self._attempted = False
        self.verify_before_mutation = None

    def arm(self, opcode, payload):
        self._armed = (opcode, payload)

    def mutate(self, opcode, payload):
        if self._armed != (opcode, payload) or self._attempted:
            raise ro.ProtocolError('No unused reviewed operation')
        self._armed = None
        if self.capture is None:
            raise ro.ProtocolError('Capture required')
        op = scopes.validate(self.capture.integration.get('operation'), self.capture.command)
        if (self.capture.operation_scope != op['scope']
                or self.capture.integration.get('operation_scope') != op['scope']
                or self.capture.integration.get('command') != op['scope']
                or type(payload) is not bytes or opcode != op['opcode']
                or payload.hex() != op['payload_hex']):
            raise ro.ProtocolError('Write differs from bound operation')
        if self.verify_before_mutation is None:
            raise ro.ProtocolError('Fresh binding check required before write')
        current = self.verify_before_mutation()
        if current != self.capture.integration:
            raise ro.ProtocolError('Operation binding changed before write')
        self._attempted = True  # also consumed on uncertain open/write/read failure
        self.capture.record('operation_write_intent', operation=op, automatic_retry=False)
        frame = opcode.encode('ascii') + len(payload).to_bytes(2, 'big') + payload
        with self._open() as ser:
            for data, role in ((b'\0', 'attention'), (frame, 'command')):
                call = self.capture.tx_attempt(data, role=role, opcode=opcode)
                try:
                    n = ser.write(data)
                except BaseException as exc:
                    self.capture.tx_exception(call, exc, role=role, opcode=opcode)
                    raise
                self.capture.tx_result(call, data, int(n or 0), role=role, opcode=opcode)
                if n != len(data):
                    raise ro.ProtocolError('Partial operation write; outcome uncertain, no retry')
                time.sleep(ro.ATTENTION_WAIT_S if role == 'attention' else ro.READ_WAIT_S)
            response = self._read_single_response(ser, opcode, maximum_length=1)
        if response.status != ro.STATUS_SUCCESS or response.data:
            raise ro.ProtocolError('Operation not acknowledged; no retry or rollback')
