# SPDX-License-Identifier: GPL-3.0-only
"""Preserved first inspection plus a fresh, strictly matching reconnect snapshot.

This candidate only creates/checks evidence. It never collects a snapshot itself,
opens a port, or claims the camera is connected. A separate client must validate
the complete binding before requesting live capability. Hashes are continuity checks, not
user authentication or resistance to an attacker controlling all local files.
"""
import argparse
import json
import os
from datetime import datetime, timezone
from pathlib import Path
import f100_live_binding as binding
import f100_offline_usb_gate as gate
import f100_operation_scope as scopes

REGISTRATION = 'f100-reviewed-cable-registration/0.1'
REPORT = 'f100-cable-reconnect-report/0.1'
GATE = 'f100-cable-reconnect-gate/0.1'
HASH_FIELD = 'self_sha256_without_this_field'


def utc():
    return datetime.now(timezone.utc).isoformat().replace('+00:00', 'Z')


def save(path, value):
    value = dict(value)
    value.pop(HASH_FIELD, None)
    value[HASH_FIELD] = binding._canonical_hash(value)
    payload = (json.dumps(value, ensure_ascii=False, indent=2) + '\n').encode()
    with Path(path).open('xb') as f:
        f.write(payload)
        f.flush()
        os.fsync(f.fileno())
    if Path(path).read_bytes() != payload:
        raise binding.BindingError('Evidence read-back mismatch')
    return value


def load(path, schema):
    return binding._load_sealed(Path(path), schema, HASH_FIELD, schema)


def source_files(session):
    # Do not enroll old captures or outputs; preserve all first-inspection inputs.
    files = [session/'orchestration-plan.json']
    files.extend(p for p in (session/'mac-admission').rglob('*') if p.is_file() or p.is_symlink())
    if any(p.is_symlink() for p in files):
        raise binding.BindingError('Symlink in original inspection evidence')
    return {str(p.relative_to(session)): binding._sha256(p) for p in sorted(files)}


def first_args(session):
    plan = binding._load(session/'orchestration-plan.json', 'original plan')
    if plan.get('mac_command') not in ('cq', 'mq', 'oq', 'lq') or plan.get('mode') != 'mac-client':
        raise binding.BindingError('Registration requires an original Mac read-only inspection')
    return dict(orchestration_plan=session/'orchestration-plan.json',
                admission_report=session/'mac-admission/report.json',
                forwarding_gate=session/'mac-admission/utm-forwarding-gate.json',
                integration_session_id=session.name, serial_port=plan.get('serial_port'),
                expected_mode='mac-client', expected_command=plan.get('mac_command'))


def register(path, session, *, user_confirmed, actor, channel):
    if user_confirmed is not True or actor not in ('user', 'assistant') or channel not in ('gui', 'terminal', 'chat-relay'):
        raise binding.BindingError('Explicit registration confirmation and attribution required')
    if (actor == 'assistant') != (channel == 'chat-relay'):
        raise binding.BindingError('Confirmation attribution mismatch')
    session = Path(session).resolve(strict=True)
    args = first_args(session)
    validated = binding._validate_first_use_binding(**args)  # fresh at registration
    approval = binding._load(session/'mac-admission/approval.json', 'original approval')
    record = {'schema': REGISTRATION, 'generated_utc': utc(), 'original_session': str(session),
              'original_files': source_files(session), 'original_binding': validated,
              'serial_port': args['serial_port'], 'expected_vid': approval['expected_vid'],
              'expected_pid': approval['expected_pid'], 'fingerprint_sha256': approval['fingerprint_sha256'],
              'confirmation': {'confirmed': True, 'actor': actor, 'channel': channel},
              'scope': 'previously-reviewed-cable-only', 'camera_identity_claim': False}
    save(path, record)
    return Path(path)


def validate_registration(path):
    reg = load(path, REGISTRATION)
    if reg.get('scope') != 'previously-reviewed-cable-only' or reg.get('camera_identity_claim') is not False:
        raise binding.BindingError('Registration boundary mismatch')
    c = reg.get('confirmation', {})
    if (c.get('confirmed') is not True or c.get('actor') not in ('user', 'assistant')
            or c.get('channel') not in ('gui', 'terminal', 'chat-relay')
            or ((c.get('actor') == 'assistant') != (c.get('channel') == 'chat-relay'))):
        raise binding.BindingError('Registration confirmation missing')
    session = Path(reg['original_session']).resolve(strict=True)
    if source_files(session) != reg.get('original_files'):
        raise binding.BindingError('Original inspection evidence changed')
    # Historic validity only. This never refreshes or authorizes the old session.
    validated = binding._validate_first_use_binding(**first_args(session), require_freshness=False)
    if validated != reg.get('original_binding'):
        raise binding.BindingError('Original inspection binding changed')
    approval = binding._load(session/'mac-admission/approval.json', 'original approval')
    for field in ('serial_port', 'expected_vid', 'expected_pid', 'fingerprint_sha256'):
        if reg.get(field) != approval.get(field):
            raise binding.BindingError('Registered cable identity mismatch: ' + field)
    after = binding._load(session/'mac-admission/after.json', 'original after')
    return reg, after


def check_current(reg, reviewed, snapshot, serial_port):
    if snapshot.get('snapshot_complete') is not True or snapshot.get('schema') != binding.SNAPSHOT_SCHEMA:
        raise binding.BindingError('Incomplete reconnect snapshot')
    if serial_port != reg['serial_port'] or serial_port not in snapshot.get('serial_paths', []):
        raise binding.BindingError('Reconnect port changed; first inspection required')
    if gate._enumeration_view(snapshot) != gate._enumeration_view(reviewed):
        raise binding.BindingError('Reconnect fingerprint, port or topology changed; first inspection required')
    devices = [d for d in snapshot.get('usb_devices', []) if d.get('fingerprint_sha256') == reg['fingerprint_sha256']]
    if len(devices) != 1 or any(str(devices[0].get(k, '')).lower() != reg[v]
                              for k, v in (('vendor_id', 'expected_vid'), ('product_id', 'expected_pid'))):
        raise binding.BindingError('Reconnect VID/PID/fingerprint mismatch')


def prepare(root, session_id, registration_path, snapshot, network_report, *, command='lq', record_value=None):
    """Inputs must be fresh observations, not edited historical snapshots."""
    import f100_orchestrator as orchestrator
    registration_path = Path(registration_path).resolve(strict=True)
    reg, reviewed = validate_registration(registration_path)
    if command not in ('cq', 'mq', 'oq', 'lq', 'record-settings', 'erase-records'):
        raise binding.BindingError('Unsupported reconnect command')
    now = datetime.now(timezone.utc)
    binding._require_fresh(snapshot, 'current snapshot', now, 900)
    binding._require_fresh(network_report, 'current network observation', now, 900)
    check_current(reg, reviewed, snapshot, reg['serial_port'])
    session_root = Path(root)
    args = argparse.Namespace(root=session_root, session_id=session_id, mode='mac-client', program=None,
                              guest_com=None, serial_port=reg['serial_port'], vm_pty=None,
                              mac_command=command, record_value=record_value)
    plan_path = orchestrator.create_plan(args)
    session = plan_path.parent
    plan = binding._load(plan_path, 'reconnect plan')
    adm = session/'mac-admission'
    save(adm/'current.json', binding._without_source_hash(snapshot))
    save(adm/'network.json', binding._without_source_hash(network_report))
    report = {'schema': REPORT, 'generated_utc': utc(), 'session_id': session_id,
              'registration_file': str(registration_path), 'registration_sha256': binding._sha256(registration_path),
              'plan_sha256': binding._sha256(plan_path), 'snapshot_sha256': binding._sha256(adm/'current.json'),
              'network_sha256': binding._sha256(adm/'network.json'), 'serial_port': reg['serial_port'],
              'command': command, 'operation': plan.get('operation'), 'camera_connection_state': 'not_asserted',
              'status': 'MATCHED_PREVIOUS_CABLE', 'candidate_live_blocked': False,
              'live_policy_revision': scopes.LIVE_POLICY_REVISION}
    save(adm/'report.json', report)
    save(adm/'utm-forwarding-gate.json', {'schema': GATE, 'generated_utc': utc(),
         'session_id': session_id, 'report_sha256': binding._sha256(adm/'report.json'),
         'registration_sha256': report['registration_sha256'], 'plan_sha256': report['plan_sha256'],
         'serial_device_was_opened': False, 'execution_authorized': False, 'candidate_live_blocked': False,
         'live_policy_revision': scopes.LIVE_POLICY_REVISION})
    # Recompute every comparison; producer status is never the reason for acceptance.
    validate_binding(orchestration_plan=plan_path, admission_report=adm/'report.json',
                     forwarding_gate=adm/'utm-forwarding-gate.json', integration_session_id=session_id,
                     serial_port=reg['serial_port'], expected_mode='mac-client', expected_command=command)
    return session


def validate_binding(*, orchestration_plan, admission_report, forwarding_gate, integration_session_id,
                     serial_port, expected_mode, expected_command=None, expected_guest_com=None,
                     max_age_seconds=900, require_freshness=True, now=None):
    if (not binding.SESSION_ID_RE.fullmatch(integration_session_id) or not binding.SERIAL_RE.fullmatch(serial_port)
            or not (0 < max_age_seconds <= 3600) or expected_mode != 'mac-client' or expected_guest_com is not None):
        raise binding.BindingError('Invalid reconnect binding arguments')
    plan_path = Path(orchestration_plan).resolve(strict=True)
    session = plan_path.parent
    adm = session/'mac-admission'
    if (session.name != integration_session_id or plan_path.name != 'orchestration-plan.json'
            or Path(admission_report).resolve(strict=True) != adm/'report.json'
            or Path(forwarding_gate).resolve(strict=True) != adm/'utm-forwarding-gate.json'):
        raise binding.BindingError('Noncanonical reconnect evidence paths')
    plan = binding._load(plan_path, 'reconnect plan')
    binding._validate_self_hash(plan, 'plan_sha256_without_this_field', 'reconnect plan')
    if (plan.get('schema') != binding.PLAN_SCHEMA or plan.get('session_id') != integration_session_id
            or plan.get('mode') != 'mac-client' or plan.get('serial_port') != serial_port
            or plan.get('execution_authorized') is not False or plan.get('lq_default_live_blocked') is not True
            or not binding.HASH_RE.fullmatch(str(plan.get('capture_binding_nonce', '')))
            or plan.get('mac_command') != expected_command):
        raise binding.BindingError('Reconnect plan mismatch')
    operation = None
    if expected_command in scopes.NEW_SCOPES:
        scopes.validate_live_policy(plan)
        operation = scopes.validate(plan.get('operation'), expected_command)
        if (plan.get('np_dp_ep_implemented') is not True or plan.get('dp_implemented') is not False
                or plan.get('automatic_write_retry') is not False):
            raise binding.BindingError('Reconnect operation boundary mismatch')
    elif expected_command not in ('cq', 'mq', 'oq', 'lq') or plan.get('np_dp_ep_implemented') is not False:
        raise binding.BindingError('Reconnect read-only boundary mismatch')
    report = load(adm/'report.json', REPORT)
    final = load(adm/'utm-forwarding-gate.json', GATE)
    regpath = Path(report['registration_file']).resolve(strict=True)
    if binding._sha256(regpath) != report.get('registration_sha256'):
        raise binding.BindingError('Registration hash mismatch')
    reg, reviewed = validate_registration(regpath)
    snapshot = load(adm/'current.json', binding.SNAPSHOT_SCHEMA)
    network = binding._load(adm/'network.json', 'current network')
    binding._validate_self_hash(network, HASH_FIELD, 'current network')
    check_current(reg, reviewed, snapshot, serial_port)
    original_gate = binding._load(Path(reg['original_session'])/'mac-admission/utm-forwarding-gate.json', 'original gate')
    if original_gate.get('network_gate_status') != 'EXEMPT_USER_REVIEWED_CABLE':
        gate._network_pass(network, 'reconnect')
    for key, value in {'session_id': integration_session_id, 'serial_port': serial_port,
                       'command': expected_command, 'operation': operation, 'plan_sha256': binding._sha256(plan_path),
                       'snapshot_sha256': binding._sha256(adm/'current.json'),
                       'network_sha256': binding._sha256(adm/'network.json'),
                       'camera_connection_state': 'not_asserted', 'status': 'MATCHED_PREVIOUS_CABLE',
                       'candidate_live_blocked': False,
                       'live_policy_revision': scopes.LIVE_POLICY_REVISION}.items():
        if report.get(key) != value or type(report.get(key)) is not type(value):
            raise binding.BindingError('Reconnect report mismatch: ' + key)
    for key, value in {'session_id': integration_session_id, 'report_sha256': binding._sha256(adm/'report.json'),
                       'registration_sha256': binding._sha256(regpath), 'plan_sha256': binding._sha256(plan_path),
                       'serial_device_was_opened': False, 'execution_authorized': False,
                       'candidate_live_blocked': False,
                       'live_policy_revision': scopes.LIVE_POLICY_REVISION}.items():
        if final.get(key) != value or type(final.get(key)) is not type(value):
            raise binding.BindingError('Reconnect gate mismatch: ' + key)
    if require_freshness:
        now = now or datetime.now(timezone.utc)
        for label, value in (('snapshot', snapshot), ('network', network), ('report', report), ('gate', final)):
            binding._require_fresh(value, label, now, max_age_seconds)
    return {'binding_schema': 'f100-reconnect-binding/0.1', 'session_id': integration_session_id,
            'serial_port': serial_port, 'mode': expected_mode, 'command': expected_command,
            'operation_scope': expected_command if operation else 'read-only', 'operation': operation,
            'capture_binding_nonce': plan['capture_binding_nonce'],
            'orchestration_plan_file': str(plan_path), 'orchestration_plan_sha256': binding._sha256(plan_path),
            'admission_report_file': str(adm/'report.json'), 'admission_report_sha256': binding._sha256(adm/'report.json'),
            'utm_forwarding_gate_file': str(adm/'utm-forwarding-gate.json'),
            'utm_forwarding_gate_sha256': binding._sha256(adm/'utm-forwarding-gate.json'),
            'registration_file': str(regpath), 'registration_sha256': binding._sha256(regpath),
            'verified_before_device_open': True, 'candidate_live_blocked': False,
            'live_policy_revision': scopes.LIVE_POLICY_REVISION}
