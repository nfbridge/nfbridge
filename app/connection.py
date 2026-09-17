# SPDX-License-Identifier: GPL-3.0-only
"""Guided connection preparation using the existing evidence verifier."""
import argparse
import hashlib
import json
import logging
import sys
from pathlib import Path

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/'mac-connection'))
import f100_usb_admission as admission
import f100_offline_usb_gate as gate
import f100_orchestrator as orchestrator


class ConnectionProblem(ValueError):
    pass


# USB-serial vendor families recognized as candidates for the F100 data-cable
# role. Membership only decides whether a device is *eligible to enter* the
# admission flow (before/after USB snapshot diff, fingerprint sealing,
# topology binding, exactly-one-new-serial-path requirement, explicit user
# "review-cable" confirmation, fail-closed on any other USB change). It is
# not itself the security boundary — that pipeline is unchanged and applies
# identically no matter which family matched, and rejects a candidate that
# fails any of those checks regardless of vendor. A vendor whose product
# happens to not be a serial adapter at all is independently screened out
# there too: with no serial adapter attached, macOS creates no /dev/cu.*
# node, and inspect() requires exactly one new one.
#
# 0x067b (Prolific) covers PL2303 variants; the only one physically tested
# end to end with an F100 is 067b:2303, but other Prolific product_ids are
# admitted at the vendor level for the same reason FTDI is (below) — the
# downstream pipeline, not this pre-gate, is what actually authorizes a
# specific device.
#
# 0x0403 (FTDI, the USB-IF vendor ID assigned to Future Technology Devices
# International Ltd.) covers many product_ids across chip/board variants
# (FT232R, FT230X, ...); no specific product_id has been physically observed
# and recorded in this repository, and guessing one would be worse than not
# checking it, so the FTDI vendor family is admitted instead of a fabricated
# product_id. 0x0403:0x6001 (FT232R) has since been physically verified via
# an FTDI-based Serial-to-USB adapter (see docs/VALIDATION.md), but the
# family-level match was kept rather than narrowed, for consistency with the
# Prolific policy above.
#
# Do not add other chipsets (e.g. CH340/CH341, CP210x) here without the same
# kind of physically-verified justification.
#
# Independent audit (2026-09-17): does this allowlist provide real security
# value, or is it redundant given the downstream pipeline? Empirically, an
# unsupported/unknown vendor reaches REVIEW_REQUIRED with zero violations
# once past this gate (mac-connection/test_f100_offline_usb_gate.py::
# VendorAllowlistSecurityAuditTests) — so against a deliberate attacker who
# can freely set vendor_id/product_id in firmware, this allowlist is not a
# real boundary. The audit also found a genuine, vendor-independent gap it
# did not by itself close: the USB<->serial-path binding in derive_candidate()
# /_bind_candidate_topology() was cardinality-only ("exactly one new USB
# device" + "exactly one new /dev/cu.* path" implies "same device"), with no
# IOKit registry evidence tying the specific serial node to the specific USB
# device subtree. Verdict: HARDEN_THEN_REMOVE.
#
# Hardening (2026-09-17, same day): that gap has since been closed by
# gate._bind_candidate_serial_ancestry(), called from both inspect() and
# prepare() right after _bind_candidate_topology(). It requires the
# candidate /dev/cu.* path to resolve to exactly one IOSerialBSDClient
# registry node (from the new "serial_bsd_clients" snapshot field, collected
# via `ioreg -a -r -c IOSerialBSDClient`) whose registry_entry_id is present
# in the candidate USB device's own serial_client_registry_ids — i.e. real
# IORegistry ancestry, not cardinality alone. This was derived from real
# comparative evidence collected on this Mac from both a physical Prolific
# adapter and a physical FTDI adapter (docs/VALIDATION.md), which share an
# identical class chain (IOUSBHostDevice -> IOUSBHostInterface ->
# IOUserSerial -> IOSerialBSDClient) despite different driver names
# (AppleUSBPLCOM vs AppleUSBFTDI) — the check anchors on the common class,
# never on driver/vendor naming, so it is vendor-independent by
# construction. It fails closed (status="FAIL") on missing, ambiguous,
# mismatched, or unparseable ancestry evidence; see
# VendorAllowlistSecurityAuditTests::test_unrelated_usb_device_and_
# unrelated_serial_path_now_fails_ancestry_binding,
# ::test_bluetooth_named_serial_path_now_fails_ancestry_binding,
# ::test_verified_ancestry_still_passes,
# ::test_ancestry_pointing_at_a_different_device_fails, and
# ::test_ambiguous_ancestry_with_duplicate_callout_device_fails.
#
# PHASE 3 (2026-09-17, same day): the hardened code path above was re-tested
# against real physical hardware — both a Prolific adapter (067b:2303) and an
# FTDI adapter (0403:6001) — through the actual guided admission flow
# (app/camera.py's enroll()/prepare(), not just offline fixtures).
# candidate_serial_ancestry_verified was true on every admission for both
# vendors, and the separate reconnect check (f100_reconnect.py::
# check_current(), untouched by this hardening) passed 7/7 across repeated
# disconnect/reconnect cycles for both vendors. See docs/VALIDATION.md for
# the full evidence. This closes the HARDEN half of the HARDEN_THEN_REMOVE
# verdict above.
#
# REMOVE decision (2026-09-17): deliberately NOT taken. PHASE 4 (re-running
# the vendor-gate-removed adversarial tests to justify dropping this
# allowlist) was considered and explicitly deferred, not because it would
# fail, but because there is no actual user need to accept vendor families
# beyond the two already in real use here (Prolific, FTDI) — widening
# eligibility further is out of this project's current scope regardless of
# what the ancestry hardening alone would technically allow. This allowlist
# stays as an independent, additive check alongside ancestry binding, not a
# stand-in for it and not something ancestry binding is meant to replace.
SUPPORTED_VENDOR_FAMILIES = frozenset({'0x067b', '0x0403'})


def is_supported_adapter(vendor_id, product_id):
    # product_id is accepted (and available at every call site) for forward
    # compatibility with a future per-product_id restriction, but is not
    # currently part of the eligibility test — see the policy comment above.
    del product_id
    return str(vendor_id).lower() in SUPPORTED_VENDOR_FAMILIES


_CHECK_LABELS = {
    'usb_ioreg': ('USB 장치', 'USB devices'),
    'usb_system_profiler': ('USB 보조 조회', 'USB cross-check'),
    'usb_crosscheck': ('USB 정보 대조', 'USB information cross-check'),
    'hid': ('입력 장치', 'input devices'),
    'disks': ('디스크 목록', 'disk list'),
    'interfaces': ('네트워크 목록', 'network interfaces'),
    'system_extensions': ('시스템 확장 목록', 'system extensions'),
    'serial_paths': ('통신 포트 목록', 'serial ports'),
}


class SnapshotProblem(ConnectionProblem):
    """Show only safe check names and statuses, never raw device data."""

    def __init__(self, before, after):
        self.failures = []
        for phase, snapshot in (('before', before), ('after', after)):
            if snapshot.get('snapshot_complete') is True:
                continue
            reported = set()
            commands = snapshot.get('commands')
            if isinstance(commands, dict):
                for name, status in commands.items():
                    if name not in _CHECK_LABELS or not isinstance(status, dict) or status.get('ok') is not False:
                        continue
                    code = status.get('exit_code')
                    code = code if type(code) is int else None
                    self.failures.append((phase, name, 'command', code))
                    reported.add(name)
            errors = snapshot.get('parse_errors')
            if isinstance(errors, list):
                for error in errors:
                    # The exception text can contain local paths or device names.
                    # Keep only its controlled check name, never its raw message.
                    name = error.split(':', 1)[0] if isinstance(error, str) else ''
                    if name in _CHECK_LABELS and name not in reported:
                        self.failures.append((phase, name, 'parse', None))
                        reported.add(name)
            if not reported:
                self.failures.append((phase, 'unknown', 'unknown', None))
        super().__init__(self.localized('ko'))

    def localized(self, language):
        english = language == 'en'
        heading = 'System connection information could not be checked.' if english else '시스템 연결 정보를 확인하지 못했습니다.'
        phase_names = {'before': 'Before connection' if english else '연결 전',
                       'after': 'After connection' if english else '연결 후'}
        kind_names = {'command': 'command failed' if english else '명령 실행 실패',
                      'parse': 'could not interpret result' if english else '결과 해석 실패',
                      'unknown': 'cause not recorded' if english else '원인 기록 없음'}
        lines = [heading]
        for phase, name, kind, code in self.failures:
            label = _CHECK_LABELS.get(name, ('기타 검사', 'other check'))[1 if english else 0]
            detail = kind_names[kind]
            if code is not None:
                detail += f' (exit {code})' if english else f' (종료 코드 {code})'
            lines.append(f'{phase_names[phase]}: {label} — {detail}')
        return '\n'.join(lines)


def sealed(value):
    value=dict(value)
    value.pop('self_sha256_without_this_field',None)
    value['self_sha256_without_this_field']=gate._canonical_hash(value)
    return value


def inspect(before, after):
    if not before.get('snapshot_complete') or not after.get('snapshot_complete'):
        raise SnapshotProblem(before, after)
    try:
        _,_,preview=gate.derive_candidate(before,after,None,None)
    except (ValueError, TypeError) as exc:
        raise ConnectionProblem('연결 정보가 불완전하거나 서로 맞지 않습니다. 다시 연결을 확인하세요.') from exc
    if preview['status']!='REVIEW_REQUIRED':
        logging.error('Cable inspection rejected: %s', json.dumps(preview, ensure_ascii=False))
        if not preview['new_usb_devices'] and not preview['new_serial_paths']:
            raise ConnectionProblem('새로 연결된 케이블을 찾지 못했습니다.\n처음 안내가 나올 때 케이블을 Mac에서도 빼고, 다음 안내가 나오면 USB 쪽을 다시 꽂아 주세요.\n카메라 설정이나 촬영기록은 바꾸지 않았습니다.')
        raise ConnectionProblem('연결 전후에 케이블 이외의 장치 변화가 있거나, 케이블을 찾지 못했습니다. 다른 USB 장치는 그대로 두고 다시 시도하세요.')
    device=preview['new_usb_devices'][0]
    paths=[x for x in preview['new_serial_paths'] if x.startswith('/dev/cu.')]
    if len(paths)!=1:
        raise ConnectionProblem('케이블의 통신 포트를 찾지 못했습니다. macOS에서 케이블이 인식됐는지 확인하세요.')
    policy,report,summary=gate.derive_candidate(before,after,device['vendor_id'].lower(),device['product_id'].lower())
    gate._bind_candidate_topology(summary)
    gate._bind_candidate_serial_ancestry(summary,after)
    if summary['status']!='REVIEW_REQUIRED':
        raise ConnectionProblem('장치 연결 경로를 확인하지 못했습니다.')
    return device,paths[0]


def prepare(root, session_id, before, after, *, user_confirmed=False, command="lq"):
    # Approval is an explicit UI decision, never inferred from an attached USB device.
    if user_confirmed is not True:
        raise ConnectionProblem('카메라 데이터 케이블 확인이 필요합니다.')
    if command not in ("lq", "maintenance"):
        raise ConnectionProblem("지원하지 않는 작업입니다.")
    before,after=sealed(before),sealed(after)
    device,port=inspect(before,after)
    Path(root).mkdir(parents=True,exist_ok=True)
    plan=orchestrator.create_plan(argparse.Namespace(root=Path(root),session_id=session_id,mode='mac-client',program=None,guest_com=None,serial_port=port,vm_pty=None,mac_command=command))
    session=plan.parent;path=session/'mac-admission'
    policy,report,summary=gate.derive_candidate(before,after,device['vendor_id'].lower(),device['product_id'].lower())
    gate._bind_candidate_topology(summary)
    gate._bind_candidate_serial_ancestry(summary,after)
    for name,value in [('before.json',before),('after.json',after),('candidate-policy.json',policy),('candidate-report.json',report),('discovery-summary.json',summary)]:
        gate._write_new(path/name,value)
    record=sealed(dict(schema=gate.SESSION_SCHEMA,generated_utc=gate._utc_now(),expected_vid=summary['expected_vid'],expected_pid=summary['expected_pid'],identity_check_only=False,required_candidate_topology='observed_baseline_relative_path',preauth_summary_binding=None,operator_assertions={'camera_powered_off_and_disconnected':True,'stable_baseline_confirmed':True},tool_opens_serial_or_controls_utm=False,safe_to_forward_automatically=False))
    gate._write_new(path/'session.json',record)
    gate.approve_candidate(argparse.Namespace(session=path,fingerprint=device['fingerprint_sha256'],serial_port=port,ack_device_label_physically_reviewed=True,ack_logical_check_not_badusb_proof=True))
    exception=sealed(dict(schema='f100-reviewed-cable-network-exception/0.1',integration_session_id=session_id,admission_session_path_sha256=gate._path_binding(path),scope='network-isolation-only',user_authorized=True,expected_vid=summary['expected_vid'],expected_pid=summary['expected_pid'],fingerprint_sha256=device['fingerprint_sha256'],serial_port=port,authorization_source='Guided UI: user confirmed the displayed device is their previously checked F100-compatible data cable, camera disconnected; authorized read with networking unchanged. No electrical or firmware authentication claimed.'))
    gate._write_new(path/'reviewed-cable-network-exception.json',exception)
    return session,port


def final_check(session,port,**collectors):
    return gate.gate_for_manual_forwarding(argparse.Namespace(session=Path(session)/'mac-admission',serial_port=port,max_age_seconds=900,use_reviewed_cable_network_exception=True),**collectors)
