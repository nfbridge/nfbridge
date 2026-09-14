#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-3.0-only
"""Explicit, backed-up erase then Detailed setup. No automatic write retry."""
import argparse
import hashlib
import json
import os
from pathlib import Path
import sys
import time
import f100_readonly as ro

ACTION = 'erase-and-detailed'


def save_new(path, payload):
    with Path(path).open('xb') as f:
        f.write(payload)
        f.flush()
        os.fsync(f.fileno())
    if Path(path).read_bytes() != payload:
        raise ro.ProtocolError('Backup read-back mismatch')


def read_state(link):
    mq = link.request('MQ', expected_len=1).require_success()
    oq = link.request('OQ', expected_len=2).require_success()
    data = link.request('LQ', live_capability=ro._EXPERIMENTAL_LQ_LIVE_CAPABILITY).require_success()
    if len(mq) != 1 or len(oq) != 2 or not data or data[0] not in (0, 1):
        raise ro.ProtocolError('Invalid MQ/OQ/LQ state')
    if int.from_bytes(oq, 'big') != len(data)-1:
        raise ro.ProtocolError('OQ/LQ length mismatch; camera may have changed')
    if len(data) > 1 and bool(mq[0] & 8) != bool(data[0]):
        raise ro.ProtocolError('MQ/LQ mode mismatch')
    decoded = ro.decode_lq(data)
    return {'mq':mq[0], 'oq':int.from_bytes(oq,'big'), 'payload':data,
            'frames':sum(r['frame_count'] for r in decoded['rolls']), 'decoded':decoded}


def describe(state):
    return {**{k:v for k,v in state.items() if k not in ('payload','decoded')},
            'lq_global_raw':state['payload'][:1].hex(), 'lq_payload_bytes':len(state['payload'])}


def validate_confirmation_source(actor, channel):
    if actor not in ('user', 'assistant') or channel not in ('gui', 'terminal', 'chat-relay'):
        raise ro.ProtocolError('Confirmation actor and channel must be explicit')
    if (actor == 'assistant') != (channel == 'chat-relay'):
        raise ro.ProtocolError('Assistant relay must be identified as chat-relay')


def require_empty_settings_memory(state):
    if state['oq'] != 0 or len(state['payload']) != 1 or state['frames'] != 0:
        raise ro.ProtocolError('Settings require empty memory: OQ=0, LQ=1 byte, frames=0; no NP sent')


def confirm_counter_e(link, confirm, *, actor, channel):
    # MQ/OQ/LQ cannot establish the film counter. This is an operator observation,
    # separate from deletion permission and the program's empty-memory checks.
    details = {'required_counter': 'E', 'source': 'operator_observation',
               'camera_counter_read_by_app': False}
    accepted = confirm('counter-e', details) is True
    link.capture.record('camera_counter_e_confirmation', confirmed=accepted,
                        actor=actor, channel=channel, **details)
    return accepted


def run(link, folder, confirm, *, actor, channel):
    """Confirmation occurs after durable backup. Each mutation occurs at most once."""
    validate_confirmation_source(actor, channel)
    folder = Path(folder)
    before = read_state(link)
    backup = folder/'backup-lq.bin'
    save_new(backup, before['payload'])
    backup_hash = hashlib.sha256(before['payload']).hexdigest()
    save_new(folder/'backup.json', json.dumps({'sha256':backup_hash, **describe(before),
             'decoded':before['decoded']},ensure_ascii=False,indent=2).encode())
    link.capture.record('maintenance_backup_verified', sha256=backup_hash, **describe(before))
    result = {'backup_sha256':backup_hash, 'before':describe(before), 'erased':False, 'detailed_set':False}
    if confirm('erase', {'backup':str(backup), 'backup_sha256':backup_hash, **describe(before)}) is not True:
        result['status']='cancelled_before_erase'
        return result
    # Reread the full memory after the user has reviewed the backup.
    current = read_state(link)
    if current['mq'] != before['mq'] or current['payload'] != before['payload'] or backup.read_bytes()!=before['payload']:
        raise ro.ProtocolError('Camera or backup changed after review; nothing erased')
    link.arm('EP', b'')
    link.mutate('EP', b'')
    empty = read_state(link)
    if empty['oq'] != 0 or len(empty['payload']) != 1 or empty['frames']:
        raise ro.ProtocolError('EP acknowledged but empty memory not verified; no NP sent')
    result['erased']=True
    link.capture.record('maintenance_erase_verified', **describe(empty))
    # Read AFTER EP, preserving unknown bits and the full-memory policy.
    if empty['mq'] & ~0x0b:
        raise ro.ProtocolError('Unknown MQ bits remain after erase; no NP sent')
    target = empty['mq'] | 0x0a
    if target != empty['mq']:
        require_empty_settings_memory(empty)
        if confirm('detailed', {'before_mq':empty['mq'], 'target_mq':target}) is not True:
            result['status']='erased_settings_unchanged'
            return result
        if not confirm_counter_e(link, confirm, actor=actor, channel=channel):
            result['status']='erased_settings_unchanged'
            result['reason']='counter_e_not_confirmed'
            return result
        latest = read_state(link)
        require_empty_settings_memory(latest)
        if latest['mq']!=empty['mq'] or latest['payload']!=empty['payload']:
            raise ro.ProtocolError('Camera changed before NP; no settings written')
        link.arm('NP', bytes([target]))
        link.mutate('NP', bytes([target]))
    final = read_state(link)
    if final['mq'] != target or len(final['payload']) != 1 or final['oq'] != 0:
        raise ro.ProtocolError('Final verification mismatch; no automatic repair attempted')
    result.update(status='verified', detailed_set=True, after=describe(final),
                  recording_effective='next_film_advanced_to_first_frame')
    link.capture.record('maintenance_final_verified', **describe(final))
    return result


class MaintenanceLink(ro.F100Link):
    """Only the two ordered operation calls are available; read API stays unchanged."""
    def __init__(self,*args,**kwargs):
        super().__init__(*args,**kwargs)
        self._mutations=[]
        self._armed=None
        self.verify_before_mutation=None

    def arm(self, opcode, payload):
        self._armed=(opcode,payload)

    def mutate(self, opcode, payload):
        if self._armed != (opcode,payload):
            raise ro.ProtocolError('No reviewed operation is armed')
        self._armed=None
        if self.capture is None or self.capture.integration.get('command')!='maintenance':
            raise ro.ProtocolError('Maintenance requires its own verified binding')
        if opcode=='EP' and payload==b'' and not self._mutations:
            frame=b'EP\x00\x00'
        elif opcode=='NP' and type(payload) is bytes and len(payload)==1 and payload[0] in (0x0a,0x0b) and self._mutations==['EP']:
            frame=b'NP\x00\x01'+payload
        else:
            raise ro.ProtocolError('Operation outside ordered EP then Detailed NP scope')
        if self.verify_before_mutation is None:
            raise ro.ProtocolError('Fresh maintenance binding check required')
        self.verify_before_mutation()
        self._mutations.append(opcode)  # consumed even if delivery is uncertain
        self.capture.record('maintenance_write_intent',opcode=opcode,payload_hex=payload.hex(),automatic_retry=False)
        with self._open() as ser:
            for data,role in [(b'\x00','attention'),(frame,'command')]:
                call=self.capture.tx_attempt(data,role=role,opcode=opcode)
                try:
                    n=ser.write(data)
                except BaseException as exc:
                    self.capture.tx_exception(call,exc,role=role,opcode=opcode)
                    raise
                self.capture.tx_result(call,data,int(n or 0),role=role,opcode=opcode)
                if n!=len(data):raise ro.ProtocolError('Partial maintenance write; outcome uncertain, no retry')
                time.sleep(ro.ATTENTION_WAIT_S if role=='attention' else ro.READ_WAIT_S)
            response=self._read_single_response(ser,opcode,maximum_length=1)
        # Empty 79 is also a stop: writes never inherit read retries.
        if response.status!=ro.STATUS_SUCCESS or response.data:
            raise ro.ProtocolError('Maintenance not acknowledged; no retry or repair attempted')


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    for name in ['port','integration-session-id']:
        parser.add_argument('--'+name,required=True)
    for name in ['orchestration-plan','admission-report','utm-forwarding-gate','capture-dir']:
        parser.add_argument('--'+name,type=Path,required=True)
    parser.add_argument('--max-binding-age-seconds',type=float,default=900)
    parser.add_argument('--execute-erase-and-detailed',action='store_true')
    parser.add_argument('--confirmation-actor', choices=('user','assistant'), default='user')
    parser.add_argument('--confirmation-channel', choices=('terminal','chat-relay'), default='terminal')
    args=parser.parse_args();args.command='maintenance'
    if not args.execute_erase_and_detailed:
        parser.error('Explicit --execute-erase-and-detailed required; no device opened')
    capture=None
    try:
        validate_confirmation_source(args.confirmation_actor, args.confirmation_channel)
        binding=ro._validate_cli_live_binding(args,args.port)
        capture=ro.CaptureSession(args.capture_dir,port=args.port,command='maintenance',
            serial_config=ro.SERIAL_CONFIG,integration=binding.integration,operation_scope=ACTION)
        auth=ro._issue_live_transport_authorization(port=args.port,capture=capture,verified_binding=binding)
        link=MaintenanceLink(args.port,capture=capture,live_authorization=auth)
        def revalidate():
            current=ro._validate_cli_live_binding(args,args.port)
            if current.integration != binding.integration:
                raise ro.ProtocolError('Maintenance binding changed after review')
        link.verify_before_mutation=revalidate
        def confirm(action, details):
            print(json.dumps(details,ensure_ascii=False,indent=2))
            prompt={
                'erase':'백업한 촬영기록을 카메라에서 모두 삭제할까요?',
                'detailed':'기록 ON·Detailed로 바꿀까요? 다음 필름을 장전해 1컷으로 진행하면 적용됩니다. 가득 찰 때 동작은 유지합니다.',
                'counter-e':'카메라의 필름 카운터가 E입니까? 직접 확인해 주세요. 앱은 필름 유무를 알 수 없습니다.',
            }[action]
            answer=input(prompt+' [y/N]: ').strip().lower() in ('y','yes','예','네')
            capture.record('maintenance_user_confirmation',action=action,confirmed=answer,
                           actor=args.confirmation_actor,channel=args.confirmation_channel)
            return answer
        result=run(link,args.capture_dir,confirm,actor=args.confirmation_actor,channel=args.confirmation_channel)
        save_new(args.capture_dir/'result.json',json.dumps(result,indent=2).encode())
        capture.finish('success' if result['status']=='verified' else 'interrupted')
        print(json.dumps(result,ensure_ascii=False,indent=2));return 0
    except (OSError,ValueError,EOFError,KeyboardInterrupt,RuntimeError) as exc:
        if capture:capture.finish('failure',str(exc))
        print('중단: '+str(exc)+'\n자동 재시도하지 않았습니다. 백업과 캡처를 확인하세요.',file=sys.stderr)
        return 2

if __name__=='__main__':raise SystemExit(main())
