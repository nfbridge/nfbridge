# SPDX-License-Identifier: GPL-3.0-only
"""GUI camera adapter. All I/O starts with a button, using existing validators."""
import argparse
import hashlib
import json
from pathlib import Path
import sys

import connection
import nfbridge
import report
import archive_check
from i18n import EN
import f100_readonly as ro
import f100_reconnect as reconnect
import f100_record_operations as operations
from f100_maintenance import read_state, save_new


class Cancelled(Exception):
    pass


class CameraBackend:
    def __init__(self, home, *, snapshot=None, network=None, platform=None):
        self.home = Path(home)
        self.snapshot = snapshot or connection.admission.collect_snapshot
        self.network = network or connection.gate.collect_network_gate
        self.platform = sys.platform if platform is None else platform
        self.registration = self.home / 'reviewed-cable.json'

    def require(self, prompt, action, details=None):
        if prompt(action, details or {}) is not True:
            raise Cancelled()

    def enroll(self, prompt):
        self.require(prompt, 'disconnect')
        before = self.snapshot()
        self.require(prompt, 'usb-only')
        after = self.snapshot()
        device, port = connection.inspect(before, after)
        if (device['vendor_id'].lower(), device['product_id'].lower()) != ('0x067b', '0x2303'):
            raise ValueError('이 안내는 실물 확인된 Prolific F100 데이터 케이블용입니다. 다른 케이블은 별도 검토가 필요합니다.')
        self.require(prompt, 'review-cable', {'port': port, 'device': device})
        session, port = connection.prepare(self.home / 'sessions', nfbridge.stamp(), before, after,
                                           user_confirmed=True)
        connection.final_check(session, port, snapshot_collector=self.snapshot, network_collector=self.network)
        # Registration preserves the complete, fresh inspection. No serial open here.
        reconnect.register(self.registration, session, user_confirmed=True, actor='user', channel='gui')

    def prepare(self, prompt, command, value=None):
        if self.platform != 'darwin':
            raise ValueError('실제 카메라 연결은 현재 macOS에서만 지원합니다. 예제 보기는 사용할 수 있습니다.')
        if ro.serial is None:
            raise ValueError('카메라 연결에 필요한 pyserial이 없습니다. 개발 실행 환경을 확인하세요.')
        if not self.registration.exists():
            self.enroll(prompt)
        reg, _ = reconnect.validate_registration(self.registration)
        self.require(prompt, 'connect-camera', {'port': reg['serial_port']})
        # Collect AFTER the user is ready: time spent in a dialog is not freshness.
        session = reconnect.prepare(self.home / 'sessions', nfbridge.stamp(), self.registration,
                                    self.snapshot(), self.network(), command=command, record_value=value)
        return session, reg['serial_port']

    def execute(self, session, port, command, prompt, *, archive_options=None):
        args = argparse.Namespace(orchestration_plan=session / 'orchestration-plan.json',
            admission_report=session / 'mac-admission/report.json',
            utm_forwarding_gate=session / 'mac-admission/utm-forwarding-gate.json',
            integration_session_id=session.name, max_binding_age_seconds=900, command=command)
        verified = ro._validate_cli_live_binding(args, port)
        integration = dict(verified.integration)
        folder = session / 'mac-client/capture'
        capture = ro.CaptureSession(folder, port=port, command=command,
            operation_scope=integration['operation_scope'], integration=integration, serial_config=ro.SERIAL_CONFIG)
        outcome, error = 'failure', None
        try:
            authorization = ro._issue_live_transport_authorization(port=port, capture=capture, verified_binding=verified)
            cls = operations.OperationLink if command in ('record-settings', 'erase-records') else ro.F100Link
            link = cls(port, capture=capture, live_authorization=authorization)
            if command in ('record-settings', 'erase-records'):
                archive = {}
                def verify_before_mutation():
                    if command == 'erase-records':
                        checked = archive_check.require(archive['directory'], archive['expected'])
                        capture.record('archive_rechecked_before_erase', **checked)
                    return dict(ro._validate_cli_live_binding(args, port).integration)
                link.verify_before_mutation = verify_before_mutation
                def confirm(action, details):
                    if action == 'erase-records':
                        # Make a directly viewable archive BEFORE asking to erase.
                        payload = (folder / 'backup-lq.bin').read_bytes()
                        if hashlib.sha256(payload).hexdigest() != details['backup_sha256']:
                            raise ro.ProtocolError('Backup read-back mismatch')
                        data = ro.decode_lq(payload)
                        data['_source'] = {'kind': 'camera_api_capture', 'payload_hex': payload.hex(),
                                           'sha256': details['backup_sha256']}
                        page = report.save(data, session / 'exports', **(archive_options or {}))
                        archive.update(directory=page.parent, expected=data)
                        checked = archive_check.require(page.parent, data)
                        details = dict(details, **checked)
                        capture.record('viewable_archive_verified', **checked)
                    return prompt(action, details)
                result = operations.run(link, folder, confirm, actor='user', channel='gui')
                outcome = 'success' if result['status'] in ('verified', 'unchanged') else 'interrupted'
            elif command == 'mq':
                result = {'settings': ro.decode_mq(link.request('MQ', expected_len=1).require_success())}
                outcome = 'success'
            elif command == 'lq':
                state = read_state(link)
                data = state['decoded']
                data['_source'] = {'kind': 'camera_api_capture', 'payload_hex': state['payload'].hex(),
                                  'sha256': hashlib.sha256(state['payload']).hexdigest()}
                save_new(session / 'shooting-data.json', json.dumps(data, ensure_ascii=False, indent=2).encode())
                result = {'data': data, 'settings': ro.decode_mq(bytes([state['mq']]))}
                outcome = 'success'
            else:
                raise ValueError('지원하지 않는 작업입니다.')
            result['session'] = str(session)
            return result
        except BaseException as exc:
            error = str(exc)
            raise
        finally:
            capture.finish(outcome, error)

    def read(self, prompt):
        session, port = self.prepare(prompt, 'lq')
        result = self.execute(session, port, 'lq', prompt)
        nfbridge.verify_capture(session / 'mac-client/capture')
        return result

    def settings(self, prompt, *, archive_options=None):
        session, port = self.prepare(prompt, 'mq')
        current = self.execute(session, port, 'mq', prompt)
        choice = prompt('choose-settings', current['settings'])
        if choice is None:
            raise Cancelled()
        if choice == 'erase':
            command, value = 'erase-records', None
        elif type(choice) is str and choice in ('01', '02', '03', '09', '0a', '0b'):
            command, value = 'record-settings', choice
        else:
            raise ValueError('지원하지 않는 작업입니다.')
        # Never edit/reuse the MQ plan. Bind the exact chosen operation anew.
        session, port = self.prepare(prompt, command, value)
        return self.execute(session, port, command, prompt, archive_options=archive_options)


class CameraService:
    def __init__(self, home, *, backend=None):
        self.backend = backend or CameraBackend(home)

    def launch(self, app, action, done, *, reading=False):
        def work():
            change_confirmed = False
            def prompt(name, details):
                nonlocal change_confirmed
                answer = app.call_main(lambda: self.prompt(app, name, details))
                if name in ('record-settings', 'erase-records') and answer is True:
                    change_confirmed = True
                return answer
            try:
                return action(prompt)
            except Cancelled:
                return {'status': 'cancelled'}
            except archive_check.ArchiveIncomplete as exc:
                details = exc.report
                app.call_main(lambda: self.prompt(app, 'archive-incomplete', details))
                return {'status': 'archive-blocked'}
            except Exception as exc:
                text = str(exc)
                if 'Unknown MQ bits' in text or 'empty memory' in text:
                    message = '카메라에 기록이 남아 있거나 설정 상태를 확인하지 못했습니다. 가져오기로 기록을 확인하세요. 설정은 바꾸지 않았습니다.'
                elif any(part in text for part in ('Reconnect', 'Registration', 'registration', 'Original inspection', 'stale', 'expired')):
                    message = '이전 케이블 확인과 현재 연결이 맞지 않습니다. 다른 USB 장치를 원래대로 연결하거나 도움말의 케이블 다시 확인을 사용하세요.'
                elif text in EN:
                    message = text
                else:
                    if change_confirmed:
                        message = '카메라에서 작업이 끝났는지 확인할 수 없습니다.\n설정 변경이나 삭제가 이미 됐을 수 있으니 같은 작업을 다시 누르지 마세요.\n카메라 전원과 케이블을 확인한 뒤, ‘가져오기’로 남아 있는 기록을 확인하세요. 앱이 같은 명령을 다시 보내지는 않습니다.'
                    elif reading:
                        message = '가져오기를 끝내지 못했습니다.\n카메라 전원과 케이블 연결을 확인한 뒤 ‘가져오기’를 다시 눌러 주세요.\n카메라의 설정이나 촬영기록은 바꾸지 않았습니다.'
                    else:
                        message = '카메라 상태를 확인하지 못했습니다.\n카메라 전원과 케이블 연결을 확인한 뒤 다시 시작해 주세요.\n설정이나 촬영기록은 바꾸지 않았습니다.'
                raise ValueError(message) from exc
        def ready(result):
            if result.get('status') == 'cancelled':
                app.message('status', '작업을 취소했습니다. 새 쓰기 명령은 보내지 않았습니다.')
            elif result.get('status') == 'archive-blocked':
                app.message('status', '보관 파일을 확인하지 못해 삭제를 중단했습니다. 카메라 기록은 지우지 않았습니다.')
            else:
                done(result)
        app.message('status', '카메라 연결을 확인하고 있습니다…')
        app.run(work, ready)

    def read(self, app):
        from tkinter import simpledialog
        name = simpledialog.askstring(app.t('보관함'), app.t('같은 카메라의 기록에 사용할 보관함 이름'),
                                      initialvalue=app.t('내 F100'), parent=app.root)
        if not name or not name.strip():
            return
        target = app.choose_output_folder(name)
        if target is None:
            return
        language, template = app.export_options()
        def action(prompt):
            result = self.backend.read(prompt)
            stored = app.store.add(result['data'], name)
            result['library_paths'] = [item['path'] for item in stored]
            report.save(result['data'], Path(result['session']) / 'exports', language=language, template=template)
            try:
                page = report.save(result['data'], target, language=language, template=template)
            except OSError as exc:
                app.call_main(lambda: app.refresh(selected_paths=result['library_paths']))
                raise ValueError('선택한 폴더에 저장하지 못했습니다. 기록은 앱 안에 보관돼 있습니다. ‘촬영기록 저장…’으로 다른 위치에 저장해 주세요.') from exc
            result['page'] = str(page)
            return result
        def done(result):
            app.refresh(selected_paths=result['library_paths'])
            app.invalidate()
            app.remember_output_folder(target.parent)
            data = result['data']
            app.message('status', '{rolls}롤 · {frames}컷을 Mac에 저장했습니다. 저장 위치: {path}',
                        rolls=len(data['rolls']), frames=sum(r['frame_count'] for r in data['rolls']), path=str(Path(result['page']).parent))
            if not data['rolls']:
                from tkinter import messagebox
                key = ('저장된 촬영기록이 없습니다. 기록 기능은 켜져 있습니다.' if result['settings']['record_shooting_data']
                       else '저장된 촬영기록이 없습니다. 기록 설정에서 기록 기능을 켜야 앞으로의 촬영이 기록됩니다.')
                messagebox.showinfo(app.t('촬영기록'), app.t(key), parent=app.root)
        self.launch(app, action, done, reading=True)

    def settings(self, app):
        language, template = app.export_options()
        def done(result):
            key = ('이미 같은 설정입니다. 변경하지 않았습니다.' if result['status'] == 'unchanged'
                   else '설정을 확인했습니다. 다음 필름을 넣고 첫 컷으로 진행하면 적용됩니다.'
                   if result.get('operation', {}).get('opcode') == 'NP'
                   else '카메라 기록을 지웠습니다. Mac에 보관한 기록은 남아 있습니다.')
            app.message('status', key)
        self.launch(app, lambda prompt: self.backend.settings(prompt, archive_options={'language': language, 'template': template}), done)

    def reset(self, app):
        from tkinter import messagebox
        if app.busy:
            return
        if messagebox.askyesno(app.t('케이블 다시 확인'), app.t('다음 연결에서 케이블을 처음부터 다시 확인할까요? 촬영기록과 이전 확인 기록은 지우지 않습니다.'), default='no', parent=app.root):
            path = self.backend.registration
            if path.exists():
                path.rename(path.with_name('reviewed-cable-' + nfbridge.stamp() + '.json'))
            app.message('status', '기록 설정이나 가져오기를 눌러 카메라를 연결하세요.')

    def prompt(self, app, action, details):
        from tkinter import messagebox
        if action == 'archive-incomplete':
            messagebox.showerror(app.t('삭제 중단'), app.t('현재 보관 폴더에서 {missing}/{total}롤의 저장을 확인하지 못했습니다.\n확인하지 못한 롤 번호: {numbers}\n폴더: {archive}\n\n미리 저장하지 않은 촬영기록은 복구할 수 없습니다. 삭제하지 않았습니다. 파일을 다시 저장하고 확인하세요.',
                missing=details['unverified_rolls'], total=details['total_rolls'],
                numbers=', '.join(str(x) for x in details['unverified_roll_numbers']) or app.t('없음'),
                archive=details['archive']), parent=app.root)
            return False
        if action == 'choose-settings':
            return self.settings_dialog(app, details)
        text = {
            'disconnect': '사용할 케이블을 확인하고 앱에 등록하겠습니다.\n\n1. 카메라 전원을 끄세요.\n2. 케이블을 카메라와 Mac 양쪽에서 빼세요.\n3. 다른 USB 장치와 허브는 그대로 두세요.\n\n케이블을 양쪽에서 모두 뺐나요?',
            'usb-only': '케이블의 USB 쪽만 Mac에 연결하세요. 카메라 쪽은 연결하지 마세요. 준비됐나요?',
            'review-cable': '이 장치가 직접 확인한 F100 데이터 케이블이 맞나요? 카메라는 아직 분리된 상태여야 합니다. Wi-Fi는 그대로 사용하며 이 케이블 확인을 다음 연결에도 사용합니다.\n포트: {port}',
            'connect-camera': '카메라가 분리돼 있다면 전원을 끈 상태에서 케이블을 연결한 뒤 전원을 켜세요. Windows VM과 다른 카메라 연결 프로그램은 종료하세요. 준비됐나요?\n포트: {port}',
            'counter-e': '카메라의 필름 카운터가 E인지 직접 확인하세요. 앱은 이 표시를 읽을 수 없습니다. 지금 E가 표시돼 있나요?',
            'record-settings': '선택한 설정으로 바꿀까요? 다음 필름을 넣고 첫 컷으로 진행하면 적용됩니다.\n선택: {setting}\n보관 위치: {backup}',
            'erase-records': 'Mac 저장 확인: {verified_rolls}/{total_rolls}롤 · {frames}컷\n보관 폴더: {archive}\n\n미리 저장하지 않은 촬영기록은 복구할 수 없습니다. 카메라의 촬영기록 {total_rolls}롤을 전부 삭제할까요?\n이 폴더의 기록은 Mac에서 볼 수 있지만 카메라에 다시 넣을 수는 없습니다. 필름의 사진은 지워지지 않습니다.',
        }[action]
        values = dict(details)
        if action == 'record-settings':
            values['setting'] = app.t(SETTING_LABELS[details['operation']['payload_hex']])
        if action == 'erase-records':
            values['frames'] = details['before']['frames']
            values['backup'] = details['archive']
            return self.confirm_erase(app, app.t(text, **values))
        return messagebox.askyesno(app.t('카메라 확인'), app.t(text, **values), default='no', parent=app.root) is True

    def confirm_erase(self, app, text):
        import tkinter as tk
        from tkinter import ttk
        dialog = tk.Toplevel(app.root)
        dialog.title(app.t('카메라 촬영기록 삭제…'))
        dialog.transient(app.root)
        dialog.grab_set()
        result = [False]
        def finish(confirmed=False):
            result[0] = confirmed
            dialog.destroy()
        dialog.protocol('WM_DELETE_WINDOW', finish)
        dialog.bind('<Escape>', lambda event: finish())
        body = ttk.Frame(dialog, padding=20)
        body.pack(fill='both', expand=True)
        ttk.Label(body, text=text, wraplength=540).pack(anchor='w')
        row = ttk.Frame(body)
        row.pack(fill='x', pady=(16, 0))
        cancel = ttk.Button(row, text=app.t('취소'), command=finish)
        cancel.pack(side='right')
        ttk.Button(row, text=app.t('카메라 기록 전부 삭제'), command=lambda: finish(True)).pack(side='left')
        cancel.focus_set()
        app.root.wait_window(dialog)
        return result[0]

    def settings_dialog(self, app, current):
        import tkinter as tk
        from tkinter import ttk
        dialog = tk.Toplevel(app.root)
        dialog.title(app.t('기록 설정'))
        dialog.transient(app.root)
        dialog.grab_set()
        body = ttk.Frame(dialog, padding=20)
        body.pack(fill='both', expand=True)
        raw = int(current['raw_hex'], 16) & 0x0b
        text = SETTING_LABELS.get(f'{raw:02x}', '현재 설정은 아래 선택지에 없습니다.')
        ttk.Label(body, text=app.t('현재 설정: {setting}', setting=app.t(text)), wraplength=540).pack(anchor='w')
        ttk.Label(body, text=app.t('Simple은 셔터·조리개·초점거리·플래시 등 기본 정보만, Detailed는 여기에 렌즈 정보·촬영 모드·측광·보정 등을 더 기록합니다.'), wraplength=540).pack(anchor='w', pady=8)
        ttk.Label(body, text=app.t('설정 변경은 기록이 비어 있고 카운터가 E일 때만 됩니다. 기록이 있다면 취소하거나 별도로 보관 후 삭제하세요.'), wraplength=540).pack(anchor='w', pady=10)
        choice = tk.StringVar(value=f'{raw:02x}' if f'{raw:02x}' in SETTING_LABELS else '')
        for value, label in SETTING_LABELS.items():
            ttk.Radiobutton(body, text=app.t(label), value=value, variable=choice).pack(anchor='w', pady=3)
        ttk.Label(body, text=app.t('덮어쓰기를 선택하면 새 롤 하나로 예전 여러 롤의 기록이 사라질 수 있습니다.'), wraplength=540).pack(anchor='w', pady=10)
        result = [None]
        def finish(value=None):
            result[0] = value
            dialog.destroy()
        ttk.Label(body, text=app.t('먼저 촬영기록을 Mac에 저장하고 확인합니다. 그다음 삭제 여부를 묻습니다. 확인하기 전에는 지우지 않습니다.'), wraplength=540).pack(anchor='w', pady=8)
        row = ttk.Frame(body)
        row.pack(fill='x')
        ttk.Button(row, text=app.t('카메라 촬영기록 삭제…'), command=lambda: finish('erase')).pack(side='left')
        ttk.Button(row, text=app.t('취소'), command=finish).pack(side='right')
        ttk.Button(row, text=app.t('선택한 설정 적용…'), command=lambda: finish(choice.get()) if choice.get() in SETTING_LABELS else None).pack(side='right', padx=8)
        dialog.protocol('WM_DELETE_WINDOW', finish)
        app.install_help(body)
        app.root.wait_window(dialog)
        return result[0]


SETTING_LABELS = {
    '02': '기록 켜기 · Simple · 가득 차면 촬영 중지',
    '03': '기록 켜기 · Simple · 가득 차면 오래된 기록 덮어쓰기',
    '0a': '기록 켜기 · Detailed · 가득 차면 촬영 중지',
    '0b': '기록 켜기 · Detailed · 가득 차면 오래된 기록 덮어쓰기',
    '01': '기록 끄기 · Simple · 덮어쓰기 설정',
    '09': '기록 끄기 · Detailed · 덮어쓰기 설정',
}
