#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-3.0-only
"""Neo Film Bridge guided terminal entry point."""
import argparse
import hashlib
import importlib.util
import json
import os
from pathlib import Path
import subprocess
import sys
import uuid
import webbrowser
from datetime import datetime

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/'mac-client'))
import f100_readonly as client
import report


def stamp():
    return datetime.now().strftime('%Y%m%d-%H%M%S')+'-'+uuid.uuid4().hex[:6]


def demo_data():
    # Synthetic camera-format records, chosen to make the UI readable.
    header=b'\x01\xf3\x00\x01'
    frames=bytes([1,0x34,0x16,0x3c,0,0x3c,0x6a,0x16,0x1a,0,4,0,4,
                  2,0x36,0x16,0x3c,0,0x3c,0x6a,0x16,0x1a,0,0xf4,0,4,
                  3,0xe1,0x38,0x50,0x10,0x3c,0x6a,0x16,0x1a,0,0,0,12])
    payload=header+frames+b'\x13\xfd'
    data=client.decode_lq(payload)
    data['_source']={'kind':'synthetic','payload_hex':payload.hex(),'sha256':hashlib.sha256(payload).hexdigest()}
    return data


def ask(message, input_fn=input):
    return input_fn(message+' [y/N]: ').strip().lower() in {'y','yes','예','네','ㅇ','ㅇㅇ'}


def pause(message):
    answer=input(message+'\n준비되면 Enter, 취소하려면 q: ').strip().lower()
    if answer=='q':raise KeyboardInterrupt


def ensure_serial(maintenance=False):
    if importlib.util.find_spec('serial') is not None:return
    print('처음 한 번만 카메라 연결 부품을 설치합니다. 인터넷 연결이 필요합니다.')
    if not ask('설치할까요?'):raise KeyboardInterrupt
    venv=ROOT/'.runtime'
    if sys.prefix==sys.base_prefix:
        subprocess.run([sys.executable,'-m','venv',str(venv)],check=True)
        python=venv/'bin/python3'
    else:python=Path(sys.executable)
    subprocess.run([str(python),'-m','pip','install','--require-hashes','-r',str(ROOT/'mac-client/requirements-live.txt')],check=True)
    # Reloading an imported transport module in-place would leave stale state.
    os.execv(str(python),[str(python),str(Path(__file__).resolve()),'--maintenance' if maintenance else '--live','--output',str(OUTPUT)])


def verify_capture(folder):
    manifest=json.loads((folder/'session-manifest.json').read_text())
    if manifest.get('outcome')!='success' or manifest.get('api_byte_reconstruction_complete') is not True:
        raise ValueError('읽기가 완료되지 않았습니다. 통신 기록은 보존했습니다.')
    for name in ['host_to_camera','camera_to_host','events']:
        f=folder/manifest[name+'_file']
        if f.parent!=folder or hashlib.sha256(f.read_bytes()).hexdigest()!=manifest[name+'_sha256']:
            raise ValueError('저장된 통신 기록의 무결성 확인에 실패했습니다.')


def read_camera(session,port,runner=subprocess.run):
    capture=session/'mac-client'/'capture'
    command=[sys.executable,str(ROOT/'mac-client/f100_readonly.py'),'--port',port,'--capture-dir',str(capture),'--integration-session-id',session.name,'--orchestration-plan',str(session/'orchestration-plan.json'),'--admission-report',str(session/'mac-admission/report.json'),'--utm-forwarding-gate',str(session/'mac-admission/utm-forwarding-gate.json'),'lq','--experimental-live']
    result=runner(command,capture_output=True,text=True,timeout=300)
    (session/'read-output.json').write_text(result.stdout,encoding='utf-8')
    (session/'read-diagnostics.txt').write_text(result.stderr,encoding='utf-8')
    if result.returncode:
        message='읽지 못했습니다. 카메라 전원과 케이블을 확인하고, Windows나 다른 연결 프로그램을 종료한 뒤 다시 시도하세요.'
        if 'No shooting data' in result.stderr or 'no shooting data' in result.stderr:message='저장된 촬영정보가 없습니다. 새 촬영정보를 기록하려면 카메라의 기록 설정이 켜져 있어야 합니다.'
        raise ValueError(message+'\n상세 기록: '+str(session))
    verify_capture(capture)
    data=json.loads(result.stdout)
    raw=(capture/'camera-to-host.bin').read_bytes()
    decoder=client.ResponseDecoder(maximum_length=65535)
    responses=decoder.feed(raw)
    if decoder.buffered or not responses or responses[-1].status!=0x61:
        raise ValueError('원본 촬영정보 프레임을 확인하지 못했습니다.')
    payload=responses[-1].data
    data['_source']={'kind':'camera_api_capture','payload_hex':payload.hex(),'sha256':hashlib.sha256(payload).hexdigest()}
    return data


def live(maintenance=False):
    if sys.platform!='darwin':raise ValueError('실제 카메라 연결은 현재 macOS에서만 지원합니다. 예제 보기는 사용할 수 있습니다.')
    ensure_serial(maintenance)
    import connection
    print('\n카메라 연결 · Nikon F100\nF100용 데이터 케이블을 사용하세요. 셔터 릴리즈 케이블은 사용할 수 없습니다.')
    pause('카메라를 끄고 카메라 쪽 케이블과 USB 쪽을 분리하세요. 허브와 다른 USB 장치는 그대로 두세요.')
    print('연결 전 상태 확인 중…',flush=True)
    before=connection.admission.collect_snapshot()
    pause('케이블/어댑터의 USB 쪽을 Mac에 연결하세요. macOS가 액세서리 연결 허용을 물으면 먼저 허용하세요. USB 장치 연결이 완료된 것을 확인한 다음에만 계속 진행하세요. 카메라 쪽은 아직 연결하지 마세요.')
    print('케이블 확인 중…',flush=True)
    after=connection.admission.collect_snapshot()
    device,port=connection.inspect(before,after)
    print('찾은 케이블: '+device.get('manufacturer','')+' '+device.get('_name',''))
    ids=device['vendor_id'].lower()+':'+device['product_id'].lower()
    print('USB ID: '+ids+' · '+port)
    if not connection.is_supported_adapter(device['vendor_id'],device['product_id']):
        raise ValueError('이 어댑터는 아직 안내 모드에서 실물 검증하지 않았습니다. 개발용 CLI에서 별도 검증이 필요합니다.')
    scope='백업 후 삭제·Detailed 전환을 준비합니다. 실제 변경은 별도로 확인합니다.' if maintenance else '촬영정보만 읽습니다.'
    if not ask('이 장치가 사용하실 검수된 F100 데이터 케이블이 맞나요? Wi-Fi는 유지합니다. '+scope):
        raise KeyboardInterrupt
    session,port=connection.prepare(OUTPUT/'sessions',stamp(),before,after,user_confirmed=True,command="maintenance" if maintenance else "lq")
    connection.final_check(session,port)
    pause('F100의 전원이 꺼진 상태에서 카메라에 10핀 케이블을 연결하세요. 그다음 F100의 전원을 켜세요. F100의 전원이 켜진 것을 확인한 다음에만 계속 진행하세요. Windows VM과 다른 카메라 연결 프로그램은 종료해 주세요.')
    if maintenance:
        command=[sys.executable,str(ROOT/'mac-client/f100_maintenance.py'),'--port',port,'--capture-dir',str(session/'mac-client/capture'),'--integration-session-id',session.name,'--orchestration-plan',str(session/'orchestration-plan.json'),'--admission-report',str(session/'mac-admission/report.json'),'--utm-forwarding-gate',str(session/'mac-admission/utm-forwarding-gate.json'),'--execute-erase-and-detailed']
        subprocess.run(command,check=True)
        result=json.loads((session/'mac-client/capture/result.json').read_text())
        print('작업 결과: '+result['status']+' · 백업/캡처: '+str(session/'mac-client/capture'))
        return None,session
    print('촬영정보를 읽고 있습니다. 잠시 쉬던 카메라에는 한 번 더 요청할 수 있습니다…',flush=True)
    data=read_camera(session,port)
    return data,session/'report'


def show(data,destination,demo=False,open_browser=True,metadata=None):
    page=report.save(data,destination,demo=demo,metadata=metadata,sections=EXPORT_SECTIONS,vault=EXPORT_VAULT if not demo else None)
    count=sum(r.get('frame_count',0) for r in data.get('rolls',[]))
    print('\n'+('예제 준비 완료' if demo else '읽기 완료')+f" · {data.get('roll_count',0)}롤 / {count}컷")
    print('보고서: '+str(page))
    print('같은 폴더에 선택한 형식의 촬영기록을 저장했습니다.')
    if open_browser:webbrowser.open(page.as_uri())
    return page



def ask_roll_metadata(data):
    answer={}
    for roll in data.get('rolls',[]):
        value=input('롤 '+str(roll['roll_number'])+' · 차수 / 필름코드 / 촬영일(YYYY-MM-DD) / 필름명 — Enter로 건너뛰기: ').strip()
        if not value:continue
        parts=[x.strip() for x in value.split('/',3)]
        fields=dict(zip(['order','film_code','date','film'],parts))
        answer[str(roll['roll_number'])]=fields
    return answer

OUTPUT=ROOT/'user-data'
EXPORT_SECTIONS=False
EXPORT_VAULT=None


def main():
    global OUTPUT, EXPORT_SECTIONS, EXPORT_VAULT
    parser=argparse.ArgumentParser(description='Neo Film Bridge 안내 모드')
    group=parser.add_mutually_exclusive_group()
    group.add_argument('--demo',action='store_true');group.add_argument('--live',action='store_true');group.add_argument('--maintenance',action='store_true')
    parser.add_argument('--no-open',action='store_true');parser.add_argument('--output',type=Path,default=OUTPUT)
    parser.add_argument('--roll-sections',action='store_true')
    parser.add_argument('--vault',type=Path)
    parser.add_argument('--metadata',type=Path,help='롤 번호별 선택 입력 JSON')
    args=parser.parse_args();OUTPUT=args.output.expanduser().resolve()
    EXPORT_SECTIONS=args.roll_sections;EXPORT_VAULT=args.vault
    try:
        settings_path=OUTPUT/'export-settings.json'
        if args.vault:
            selected=args.vault.expanduser().resolve(strict=True)
            if not selected.is_dir():raise ValueError('볼트 폴더가 아닙니다.')
            OUTPUT.mkdir(parents=True,exist_ok=True)
            settings_path.write_text(json.dumps({'vault':str(selected)},ensure_ascii=False)+'\n')
            EXPORT_VAULT=selected
        elif settings_path.exists():
            EXPORT_VAULT=json.loads(settings_path.read_text()).get('vault')
        supplied=json.loads(args.metadata.read_text()) if args.metadata else None
        if args.demo:
            show(demo_data(),OUTPUT/('demo-'+stamp()),demo=True,open_browser=not args.no_open);return 0
        if args.maintenance:
            live(maintenance=True);return 0
        if args.live:
            data,path=live();show(data,path,open_browser=not args.no_open,metadata=supplied or ask_roll_metadata(data));return 0
        while True:
            print('\nNeo Film Bridge · 사용자 흐름 개발판\n\n  1. 카메라에서 촬영정보 가져오기\n  2. 카메라 없이 예제 보기\n  3. 백업 후 카메라 기록 삭제·Detailed 전환 (개발 시험 기능)\n  0. 종료\n')
            choice=input('번호를 입력하세요: ').strip()
            if choice=='0':return 0
            if choice=='2':show(demo_data(),OUTPUT/('demo-'+stamp()),demo=True)
            elif choice=='3':live(maintenance=True)
            elif choice=='1':
                data,path=live();show(data,path,metadata=supplied or ask_roll_metadata(data))
            else:print('0, 1, 2, 3 중에서 골라 주세요.')
    except (KeyboardInterrupt,EOFError):
        print('\n취소했습니다. 이미 저장한 기록은 그대로 남습니다.');return 130
    except (ValueError,OSError,subprocess.SubprocessError) as exc:
        print('\n진행하지 못했습니다: '+str(exc),file=sys.stderr);return 1

if __name__=='__main__':raise SystemExit(main())
