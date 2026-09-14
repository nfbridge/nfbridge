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


def sealed(value):
    value=dict(value)
    value.pop('self_sha256_without_this_field',None)
    value['self_sha256_without_this_field']=gate._canonical_hash(value)
    return value


def inspect(before, after):
    if not before.get('snapshot_complete') or not after.get('snapshot_complete'):
        raise ConnectionProblem('연결 정보를 모두 가져오지 못했습니다. 상세 USB 조회 권한을 확인하세요.')
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
