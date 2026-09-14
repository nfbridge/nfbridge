# SPDX-License-Identifier: GPL-3.0-only
"""Native Tk workbench. Camera service is injected; no implicit live write access."""
import argparse
from datetime import datetime
import json
import logging
from pathlib import Path
import queue
import sys
import threading
import tkinter as tk
from tkinter import filedialog, messagebox, simpledialog, ttk
from tkinter.scrolledtext import ScrolledText
import uuid
import webbrowser

import library
import nfbridge
import report
import scans
import exports
import roll_templates
from tooltip import Tooltip
from i18n import Translator, EN, GENERIC_ERROR


class App:
    def __init__(self, root, home, *, camera_service=None, exiftool=None, demo=False, developer_scans=False):
        self.root = root
        self.home = Path(home)
        self.translator = Translator(self.home)
        self.t = self.translator.text
        self.messages = {}
        self.service = camera_service
        self.scan_enabled = developer_scans
        self.tooltips = {}
        self.exiftool = exiftool
        self.store = library.Library(self.home / 'library')
        self.events = queue.Queue()
        self.ui_requests = queue.Queue()
        self.busy = False
        self.mapping = None
        self.entries = []
        self.folder = None
        self.root.title('Neo Film Bridge')
        self.root.geometry('980x740')
        self.root.minsize(760, 580)
        self.root.protocol('WM_DELETE_WINDOW', self.close)
        outer = ttk.Frame(root, padding=22)
        outer.pack(fill='both', expand=True)
        ttk.Label(outer, text='Neo Film Bridge', font=('Helvetica', 24, 'bold')).pack(anchor='w')
        self.language_button = ttk.Button(outer, text='English', command=self.toggle_language)
        self.language_button.pack(anchor='e')
        self.status = tk.StringVar(value='개발 미리보기 · 카메라 연결 미구현 · 저장된 기록을 열어 볼 수 있습니다.')
        self.messages['status'] = (self.status.get(), {})
        if self.service is not None:
            self.messages['status'] = ('기록 설정이나 가져오기를 눌러 카메라를 연결하세요.', {})
            self.status.set(self.t('기록 설정이나 가져오기를 눌러 카메라를 연결하세요.'))
        ttk.Label(outer, textvariable=self.status, wraplength=900).pack(anchor='w', pady=(8, 16))
        if self.service is not None:
            ttk.Label(outer, text='처음 사용하시나요?\n촬영기록을 보려면 ‘가져오기’, 기록 기능을 켜거나 바꾸려면 ‘기록 설정’을 누르세요.\n어느 버튼을 눌러도 처음에는 케이블 연결 방법부터 안내합니다.', wraplength=900).pack(anchor='w', pady=(0, 12))
        buttons = ttk.Frame(outer)
        buttons.pack(fill='x')
        self.settings_button = ttk.Button(buttons, text='기록 설정', command=self.settings)
        self.settings_button.pack(side='left', padx=(0, 8))
        self.import_button = ttk.Button(buttons, text='가져오기', command=self.import_camera)
        self.import_button.pack(side='left', padx=(0, 8))
        if self.scan_enabled:
            ttk.Button(buttons, text='스캔에 붙이기', command=self.choose_folder).pack(side='left')
        if self.service is None:
            self.settings_button.state(['disabled'])
            self.import_button.state(['disabled'])
        self.progress = ttk.Progressbar(outer, mode='indeterminate')
        self.progress.pack(fill='x', pady=12)
        self.tabs = ttk.Notebook(outer)
        self.tabs.pack(fill='both', expand=True)
        rolls = ttk.Frame(self.tabs, padding=12)
        scan = ttk.Frame(self.tabs, padding=12)
        self.tabs.add(rolls, text='촬영기록')
        if self.scan_enabled:
            self.tabs.add(scan, text='스캔 대응 미리보기')
        self.rolls = ttk.Treeview(rolls, columns=('camera', 'number', 'frames', 'iso', 'date', 'state'), show='headings', height=3)
        self.rolls.configure(displaycolumns=('camera', 'frames', 'iso', 'date', 'state'))
        widths = {'camera': 235, 'number': 55, 'frames': 65, 'iso': 140, 'date': 125, 'state': 165}
        for key, label in [('camera', '보관함'), ('number', '롤'), ('frames', '컷 수'), ('iso', '롤 마지막 감도'), ('date', '가져온 날짜'), ('state', '버전')]:
            self.rolls.heading(key, text=label)
            self.rolls.column(key, width=widths[key], minwidth=widths[key])
        self.rolls.pack(fill='x')
        roll_scroll = ttk.Scrollbar(rolls, orient='horizontal', command=self.rolls.xview)
        roll_scroll.pack(fill='x')
        self.rolls.configure(xscrollcommand=roll_scroll.set)
        self.rolls.bind('<<TreeviewSelect>>', lambda event: self.invalidate())
        self.roll_details = tk.StringVar()
        ttk.Label(rolls, textvariable=self.roll_details).pack(anchor='w', pady=(8, 0))
        frame_area = ttk.Frame(rolls)
        frame_area.pack(fill='both', expand=True, pady=(10, 0))
        self.frame_columns = [(key, label) for key, label in report.COLUMNS if key not in ('roll', 'iso')]
        self.frames = ttk.Treeview(frame_area, columns=[key for key, _ in self.frame_columns], show='headings', height=7)
        for key, label in self.frame_columns:
            self.frames.heading(key, text=label)
            self.frames.column(key, width=165 if key == 'sync' else 95, minwidth=65, stretch=False)
        self.frames.grid(row=0, column=0, sticky='nsew')
        frame_y = ttk.Scrollbar(frame_area, orient='vertical', command=self.frames.yview)
        frame_y.grid(row=0, column=1, sticky='ns')
        self.frames.configure(yscrollcommand=frame_y.set)
        frame_x = ttk.Scrollbar(frame_area, orient='horizontal', command=self.frames.xview)
        frame_x.grid(row=1, column=0, sticky='ew')
        self.frames.configure(xscrollcommand=frame_x.set)
        frame_area.rowconfigure(0, weight=1)
        frame_area.columnconfigure(0, weight=1)
        self._frame_header_tip = ''
        self._frame_header_tooltip = Tooltip(self.frames, lambda: self._frame_header_tip)
        self.frames.bind('<Motion>', self.frame_header_motion, add='+')
        row = ttk.Frame(rolls)
        row.pack(fill='x', pady=(10, 0))
        ttk.Button(row, text='저장한 촬영기록 열기', command=self.open_json).pack(side='left')
        ttk.Button(row, text='촬영기록 저장…', command=self.export_selected).pack(side='left', padx=8)
        ttk.Button(row, text='문서 양식', command=self.document_settings).pack(side='left')
        ttk.Label(rolls, text='같은 번호의 다른 기록은 별도 버전으로 보관합니다.', wraplength=700).pack(anchor='w', pady=(6,0))
        self.drop_label = ttk.Label(scan, text='롤을 선택한 뒤 스캔 폴더를 여기에 놓으세요. JPEG / TIFF', padding=12)
        self.drop_label.pack(fill='x')
        if hasattr(self.drop_label, 'drop_target_register'):
            self.drop_label.drop_target_register('DND_Files')
            self.drop_label.dnd_bind('<<Drop>>', self.drop)
        controls = ttk.Frame(scan)
        controls.pack(fill='x', pady=8)
        self.reverse = tk.BooleanVar(value=False)
        ttk.Checkbutton(controls, text='순서 뒤집기', variable=self.reverse, command=self.preview).pack(side='left')
        ttk.Label(controls, text='시작 컷').pack(side='left', padx=(20, 5))
        self.start = tk.StringVar()
        self.start_box = ttk.Combobox(controls, textvariable=self.start, state='readonly', width=8)
        self.start_box.pack(side='left')
        self.start_box.bind('<<ComboboxSelected>>', lambda event: self.preview())
        ttk.Button(controls, text='폴더 선택', command=self.choose_folder).pack(side='left', padx=12)
        self.iso_unchanged = tk.BooleanVar(value=False)
        self.iso_checkbox = ttk.Checkbutton(scan, text='이 롤은 감도를 바꾸지 않았습니다 — ISO도 쓰기',
                                           variable=self.iso_unchanged, command=self.preview)
        self.iso_checkbox.pack(anchor='w')
        ttk.Label(scan, text='기본은 ISO를 쓰지 않습니다. 다중노출 값은 첫 노출 기준입니다.', wraplength=870).pack(anchor='w')
        self.preview_table = ttk.Treeview(scan, columns=('file', 'frame', 'tags'), show='headings')
        for key, title, width in [('file', '스캔 파일', 300), ('frame', '컷', 60), ('tags', '쓸 촬영값', 440)]:
            self.preview_table.heading(key, text=title)
            self.preview_table.column(key, width=width)
        self.preview_table.pack(fill='both', expand=True)
        scroll = ttk.Scrollbar(scan, orient='horizontal', command=self.preview_table.xview)
        scroll.pack(fill='x')
        self.preview_table.configure(xscrollcommand=scroll.set)
        self.mapping_text = tk.StringVar(value='아직 대응된 파일이 없습니다.')
        self.messages['mapping_text'] = (self.mapping_text.get(), {})
        ttk.Label(scan, textvariable=self.mapping_text, wraplength=870).pack(anchor='w', pady=8)
        self.write_button = ttk.Button(scan, text='확인한 파일에 쓰기', command=self.write)
        self.write_button.pack(anchor='e')
        self.write_button.state(['disabled'])
        menu = tk.Menu(root)
        help_menu = tk.Menu(menu, tearoff=False)
        help_menu.add_command(label='카메라 없이 예제 보기', command=self.load_demo)
        help_menu.add_command(label='케이블 다시 확인', command=lambda: self.service.reset(self) if self.service else None)
        menu.add_cascade(label='도움말', menu=help_menu)
        root.config(menu=menu)
        self.menu, self.help_menu = menu, help_menu
        self.localized_widgets = []
        def collect(widget):
            if 'text' in widget.keys() and str(widget.cget('text')) in EN:
                self.localized_widgets.append((widget, str(widget.cget('text'))))
            for child in widget.winfo_children():
                collect(child)
        collect(outer)
        self.heading_texts = [(table, col, table.heading(col, 'text'))
                              for table in (self.rolls, self.frames, self.preview_table) for col in table['columns']]
        self.refresh()
        self.retranslate()
        self.install_help(outer)
        self.root.after(50, self.poll)
        if demo:
            self.load_demo()

    def frame_header_motion(self, event):
        if self.frames.identify_region(event.x, event.y) != 'heading':
            self._frame_header_tooltip.hide()
            return
        column = self.frames.identify_column(event.x)
        key = column[1:] if column.startswith('#') else ''
        try:
            key = self.frame_columns[int(key) - 1][0]
        except (ValueError, IndexError):
            self._frame_header_tooltip.hide()
            return
        tips = {
            'sync': '일반은 선막, 후막은 셔터가 닫히기 직전 발광합니다.',
            'iso': '감도는 마지막 노출 컷 기준입니다.',
            'multiple': '다중노출은 첫 노출 값만 표시합니다.',
        }
        self._frame_header_tip = self.t(tips[key]) if key in tips else ''
        if self._frame_header_tip:
            self._frame_header_tooltip.schedule()
        else:
            self._frame_header_tooltip.hide()

    def message(self, variable, key, **values):
        self.messages[variable] = (key, values)
        getattr(self, variable).set(self.t(key, **values))

    def toggle_language(self):
        try:
            self.translator.set_language('en' if self.translator.language == 'ko' else 'ko')
        except OSError:
            logging.exception('Could not save language preference')
            self.error('언어 설정을 저장하지 못했습니다. 저장 위치의 권한을 확인하세요.')
            return
        self.retranslate()

    def retranslate(self):
        for tip in self.tooltips.values():
            tip.hide()
        for widget, key in self.localized_widgets:
            widget.configure(text=self.t(key))
        for table, col, key in self.heading_texts:
            table.heading(col, text=self.t(key))
        self.tabs.tab(0, text=self.t('촬영기록'))
        if self.scan_enabled:
            self.tabs.tab(1, text=self.t('스캔 대응 미리보기'))
        self.menu.entryconfigure(0, label=self.t('도움말'))
        self.help_menu.entryconfigure(0, label=self.t('카메라 없이 예제 보기'))
        self.help_menu.entryconfigure(1, label=self.t('케이블 다시 확인'))
        self.language_button.configure(text='한국어' if self.translator.language == 'en' else 'English')
        for variable, (key, values) in self.messages.items():
            getattr(self, variable).set(self.t(key, **values))
        # Update display cells in place: language switches must not change selection or matching.
        for index, entry in enumerate(self.entries):
            values = list(self.rolls.item(str(index), 'values'))
            if entry.get('source', {}).get('kind') == 'synthetic':
                values[0] = self.t('예제 · 실제 카메라 아님')
            values[-1] = self.relation_label(entry['relation'])
            self.rolls.item(str(index), values=values)
        if self.mapping is not None:
            self.show_mapping(self.mapping)
        self.show_frames()

    def install_help(self, parent):
        help_text = {'한국어': '화면 언어를 한국어와 영어로 바꿉니다.', 'English': '화면 언어를 한국어와 영어로 바꿉니다.', '기록 설정': '촬영정보 기록을 켜거나 끄고, 저장할 항목을 선택합니다. 설정을 바꾸기 전에 다시 확인합니다.', '가져오기': '카메라의 촬영기록을 읽어 선택한 폴더에 저장합니다. 카메라에 있는 기록은 지우지 않습니다.', '저장한 촬영기록 열기': '이 앱에서 저장한 shooting-data.json 파일을 엽니다. 카메라 없이도 이전 촬영기록을 볼 수 있습니다.', '촬영기록 저장…': '선택한 롤을 원하는 파일 형식으로 저장합니다. 저장 위치와 폴더 이름을 고를 수 있습니다.', '문서 양식': '저장할 촬영일지의 모양과 출력 문서의 언어를 고릅니다. 처음에는 기본 양식을 그대로 쓰셔도 됩니다.', '양식 파일 선택': '직접 만든 촬영일지 양식을 선택합니다. 처음이라면 ‘예제 양식 저장’으로 견본부터 받아 보세요.', '예제 양식 저장': '고쳐 쓸 수 있는 촬영일지 견본을 저장합니다. 글 편집기로 내용을 바꾼 뒤 개인 양식으로 선택하세요.', '미리보기': '선택한 양식으로 촬영일지가 어떻게 나오는지 봅니다. 아직 파일을 저장하지 않습니다.', '적용': '다음에 저장하는 문서부터 이 설정을 사용합니다. 이미 저장한 파일은 바꾸지 않습니다.', '취소': '이 창을 닫습니다. 이 창에서 고른 변경은 적용하지 않습니다.', '카메라 촬영기록 삭제…': '먼저 촬영기록을 Mac에 저장하고 확인한 뒤 삭제 여부를 묻습니다. 이 버튼만 눌러서는 지우지 않습니다.'}
        for child in parent.winfo_children():
            if isinstance(child, ttk.Button) and child not in self.tooltips:
                for key, text in help_text.items():
                    if str(child.cget('text')) in (key, self.t(key)):
                        self.tooltips[child] = Tooltip(child, lambda key=text: self.t(key))
                        break
            self.install_help(child)

    def relation_label(self, relation):
        return self.t({'new': '처음 가져옴', 'prefix_growth': '컷 추가됨', 'same_number_distinct': '같은 번호·다른 기록'}.get(relation, relation))

    def invalidate(self):
        self.show_frames()
        self.iso_unchanged.set(False)
        self.mapping = None
        self.write_button.state(['disabled'])
        if self.rolls.selection():
            numbers = [str(f['frame_number']) for f in self.selected()['roll']['frames']]
            self.start_box['values'] = numbers
            self.start.set(numbers[0] if numbers else '')
        if self.folder:
            self.preview()

    def selected(self):
        selection = self.rolls.selection()
        if not selection:
            raise ValueError('먼저 촬영기록에서 롤을 선택하세요.')
        return self.entries[int(selection[0])]

    def show_frames(self):
        self.frames.delete(*self.frames.get_children())
        self.roll_details.set('')
        if not self.rolls.selection():
            return
        self.roll_details.set(self.t('카메라 내부 기록 번호: {number}', number=self.selected()['roll']['roll_number']))
        data = {'rolls': [self.selected()['roll']]}
        for row in report.rows(data, self.translator.language):
            self.frames.insert('', 'end', values=[row[key] for key, _ in self.frame_columns])

    def refresh(self, selected_paths=None):
        self.entries = self.store.entries()
        self.rolls.delete(*self.rolls.get_children())
        for index, entry in enumerate(self.entries):
            roll = entry['roll']
            label = self.relation_label(entry['relation'])
            camera = self.t('예제 · 실제 카메라 아님') if entry.get('source', {}).get('kind') == 'synthetic' else entry['camera']
            self.rolls.insert('', 'end', iid=str(index), values=(camera, roll['roll_number'], len(roll['frames']), roll.get('film_speed', '?'), entry['imported'][:10], label))
        candidates = [(index, entry) for index, entry in enumerate(self.entries)
                      if not selected_paths or entry['_path'] in selected_paths]
        if not selected_paths:
            real = [(index, entry) for index, entry in candidates if entry.get('source', {}).get('kind') != 'synthetic']
            candidates = real or candidates
        if candidates:
            index, _ = max(candidates, key=lambda item: (item[1]['imported'], item[1]['roll']['roll_number']))
            self.rolls.selection_set(str(index))
            self.rolls.see(str(index))
        self.show_frames()

    def run(self, action, done):
        if self.busy:
            return
        self.busy = True
        self.progress.start()
        def work():
            try:
                self.events.put((done, action(), None))
            except Exception as exc:
                logging.exception('Background operation failed')
                self.events.put((done, None, exc))
        threading.Thread(target=work, daemon=True).start()

    def poll(self):
        try:
            callback, reply, finished = self.ui_requests.get_nowait()
            try:
                reply['value'] = callback()
            except BaseException as exc:
                reply['error'] = exc
            finally:
                finished.set()
        except queue.Empty:
            pass
        try:
            done, value, error = self.events.get_nowait()
            self.busy = False
            self.progress.stop()
            if error:
                self.error(error)
            else:
                done(value)
        except queue.Empty:
            pass
        self.root.after(50, self.poll)

    def call_main(self, callback):
        """Worker waits for a real main-thread dialog; no worker calls into Tk."""
        reply, finished = {}, threading.Event()
        self.ui_requests.put((callback, reply, finished))
        finished.wait()
        if 'error' in reply:
            raise reply['error']
        return reply.get('value')

    def error(self, text):
        messagebox.showerror(self.t('확인이 필요합니다'), self.translator.error(text), parent=self.root)

    def load_demo(self):
        if self.busy:
            return
        self.store.add(nfbridge.demo_data(), '예제 · 실제 카메라 아님')
        self.refresh()
        self.message('status', '합성 예제 1롤을 열었습니다. 실제 카메라의 기록은 아닙니다.')

    def open_json(self):
        if self.busy:
            return
        filename = filedialog.askopenfilename(title=self.t('저장한 촬영기록 열기'), filetypes=[(self.t('원본 데이터 파일'), '*.json')])
        if not filename:
            return
        camera = simpledialog.askstring(self.t('보관함'), self.t('같은 카메라의 기록에 사용할 보관함 이름'), initialvalue=self.t('내 F100'), parent=self.root)
        if not camera:
            return
        def load():
            data = json.loads(Path(filename).read_text(encoding='utf-8'))
            return self.store.add(data, camera)
        self.run(load, lambda result: self.refresh())

    def export_selected(self):
        if self.busy:
            return
        try:
            entry = self.selected()
            language, template = self.export_options()
            formats = self.choose_formats()
        except (ValueError, OSError) as exc:
            self.error(str(exc)); return
        if not formats:
            return
        target = self.choose_output_folder(entry['camera'])
        if target is None:
            return
        data = {'mode': entry['mode'], 'roll_count': 1, 'rolls': [entry['roll']], '_source': entry['source']}
        def save():
            try:
                return report.save(data, target, demo=entry['source'].get('kind') == 'synthetic', language=language, template=template, formats=formats)
            except FileExistsError as exc:
                raise ValueError('같은 이름의 폴더나 파일이 있습니다. 다른 이름을 정해 주세요. 기존 파일은 바꾸지 않습니다.') from exc
        def done(page):
            self.remember_output_folder(page.parent.parent)
            folder = page.parent if page.is_file() else page
            self.message('status', '파일을 저장했습니다. 저장 위치: {path}', path=str(folder))
            if page.is_file() and page.suffix.lower() == '.html':
                webbrowser.open(page.as_uri())
        self.run(save, done)

    def choose_formats(self):
        dialog = tk.Toplevel(self.root)
        dialog.title(self.t('저장할 형식 선택'))
        dialog.transient(self.root)
        dialog.grab_set()
        body = ttk.Frame(dialog, padding=18)
        body.pack(fill='both', expand=True)
        ttk.Label(body, text=self.t('저장할 파일을 골라 주세요.'), font=('TkDefaultFont', 12, 'bold')).pack(anchor='w')
        ttk.Label(body, text=self.t('원본 데이터 보관은 앱이 읽은 값을 그대로 남기며, 나중에 앱에서 기록을 다시 열 때 씁니다.'), wraplength=460).pack(anchor='w', pady=(6, 14))
        choices = [
            ('html', '보기 좋은 HTML 표', '브라우저에서 읽기 좋은 촬영정보 표입니다.', True),
            ('markdown', '촬영일지 Markdown', '글과 표로 된 롤별 촬영일지입니다.', True),
            ('json', '원본 데이터 보관', '앱이 읽은 원본값과 해석값을 그대로 보관합니다. 나중에 앱에서 다시 열 때 씁니다.', True),
            ('csv', '일반 CSV 표', 'Numbers·Excel에서 열어 편집할 수 있는 표입니다.', False),
            ('exif', 'EXIF 작업용 CSV', '스캔 파일에 촬영정보를 붙일 때 쓰는 작업용 표입니다.', False),
        ]
        variables = {}
        for key, label, description, default in choices:
            var = tk.BooleanVar(value=default)
            variables[key] = var
            ttk.Checkbutton(body, text=self.t(label), variable=var).pack(anchor='w', pady=2)
            ttk.Label(body, text=self.t(description), foreground='#596963', wraplength=460).pack(anchor='w', padx=(24, 0), pady=(0, 4))
        result = {'formats': None}
        buttons = ttk.Frame(body)
        buttons.pack(fill='x', pady=(16, 0))
        def accept():
            selected = {key for key, _, _, _ in choices if variables[key].get()}
            if not selected:
                messagebox.showwarning(self.t('확인이 필요합니다'), self.t('파일 형식을 하나 이상 선택하세요.'), parent=dialog)
                return
            result['formats'] = selected
            dialog.destroy()
        ttk.Button(buttons, text=self.t('선택한 형식으로 저장'), command=accept).pack(side='left')
        ttk.Button(buttons, text=self.t('취소'), command=dialog.destroy).pack(side='left', padx=8)
        self.install_help(body)
        dialog.protocol('WM_DELETE_WINDOW', dialog.destroy)
        self.root.wait_window(dialog)
        return result['formats']

    def remember_output_folder(self, parent):
        try:
            self.translator.update_preferences({'output_parent': str(parent)})
        except OSError:
            logging.exception('Could not remember export folder; exported files remain saved')

    def choose_output_folder(self, name):
        previous = self.translator.preferences().get('output_parent', '')
        options = {'initialdir': previous} if previous and Path(previous).is_dir() else {}
        directory = filedialog.askdirectory(title=self.t('촬영기록을 저장할 위치'), parent=self.root, **options)
        if not directory:
            return
        while True:
            name = simpledialog.askstring(self.t('저장 폴더 이름'),
                self.t('이 위치에 새 폴더를 만듭니다: {path}\n폴더 이름을 정해 주세요.', path=directory),
                initialvalue=name, parent=self.root)
            if name is None:
                return
            if not name.strip() or name in ('.', '..') or any(c in name for c in ('/', '\\', '\0', '\n', '\r')):
                self.error('폴더 이름에 / 또는 \\를 넣을 수 없습니다. 빈 이름이나 . 또는 ..도 사용할 수 없습니다.')
                continue
            target = Path(directory) / name
            if target.exists() or target.is_symlink():
                self.error('같은 이름의 폴더나 파일이 있습니다. 다른 이름을 정해 주세요. 기존 파일은 바꾸지 않습니다.')
                continue
            break
        return target

    def export_options(self, preferences=None):
        preferences = self.translator.preferences() if preferences is None else preferences
        language = preferences.get('export_language', 'ui')
        if language not in ('ko', 'en'):
            language = self.translator.language
        template = None
        if preferences.get('document_template_mode') == 'custom':
            path = preferences.get('document_template_path')
            if not path:
                raise ValueError('개인 양식 파일을 선택하세요.')
            template = roll_templates.read_template(path)
        return language, template

    def document_settings(self):
        if self.busy:
            return
        dialog = tk.Toplevel(self.root)
        dialog.title(self.t('문서 양식'))
        dialog.transient(self.root)
        dialog.grab_set()
        body = ttk.Frame(dialog, padding=20)
        body.pack(fill='both', expand=True)
        ttk.Label(body, text=self.t('기본 양식으로도 바로 사용할 수 있습니다. 문서 언어는 출력 파일의 언어를, 개인 양식은 Markdown 촬영일지의 모양을 바꿉니다. 카메라 설정과 이미 저장한 파일은 바꾸지 않습니다.'), wraplength=500).pack(anchor='w', pady=(0, 12))
        prefs = self.translator.preferences()
        language = tk.StringVar(value=prefs.get('export_language', 'ui'))
        mode = tk.StringVar(value=prefs.get('document_template_mode', 'builtin'))
        path = tk.StringVar(value=prefs.get('document_template_path', ''))
        ttk.Label(body, text=self.t('문서 언어')).pack(anchor='w')
        for value, label in [('ui', '화면 언어 따르기'), ('ko', '한국어'), ('en', 'English')]:
            ttk.Radiobutton(body, text=self.t(label), variable=language, value=value).pack(anchor='w')
        for value, label in [('builtin', '기본 양식'), ('custom', '개인 Markdown 양식')]:
            ttk.Radiobutton(body, text=self.t(label), variable=mode, value=value).pack(anchor='w', pady=4)
        ttk.Entry(body, textvariable=path, width=65, state='readonly').pack(fill='x')
        row = ttk.Frame(body)
        row.pack(fill='x', pady=10)
        def choose():
            name = filedialog.askopenfilename(parent=dialog, title=self.t('양식 파일 선택'), filetypes=[(self.t('Markdown 양식'), '*.md')])
            if name:
                try:
                    roll_templates.read_template(name)
                except (OSError, ValueError) as exc:
                    self.error(str(exc)); return
                path.set(name); mode.set('custom')
        def sample():
            name = filedialog.asksaveasfilename(parent=dialog, title=self.t('예제 양식 저장'), initialfile='my-roll-template.md', defaultextension='.md')
            if name:
                try:
                    with Path(name).open('x', encoding='utf-8') as handle:
                        handle.write(roll_templates.sample(self.translator.language if language.get() == 'ui' else language.get()))
                    messagebox.showinfo(self.t('문서 양식'), self.t('예제 양식을 저장했습니다. 편집한 뒤 개인 양식으로 선택하세요.'), parent=dialog)
                except (OSError, ValueError) as exc:
                    self.error(str(exc))
        ttk.Button(row, text=self.t('양식 파일 선택'), command=choose).pack(side='left')
        ttk.Button(row, text=self.t('예제 양식 저장'), command=sample).pack(side='left', padx=8)
        ttk.Label(body, text=self.t('개인 양식은 이 Mac에만 저장됩니다. 직접 쓰는 메모는 그대로 두세요.'), wraplength=500).pack(anchor='w')
        def selected_options():
            return {'export_language': language.get(), 'document_template_mode': mode.get(), 'document_template_path': path.get()}
        def preview():
            try:
                selected_language, template = self.export_options(selected_options())
                entry = self.selected() if self.rolls.selection() else {'roll': nfbridge.demo_data()['rolls'][0], 'mode': 'detailed'}
                imported = datetime.now().astimezone()
                meta = exports.roll_metadata(entry['roll'], {}, imported)
                content = exports.markdown(entry['roll'], entry['mode'], meta, imported, language=selected_language, template=template)
            except (OSError, ValueError) as exc:
                self.error(str(exc)); return
            view = tk.Toplevel(dialog)
            view.title(self.t('미리보기'))
            text = ScrolledText(view, width=95, height=30, wrap='word')
            text.pack(fill='both', expand=True)
            text.insert('1.0', content); text.configure(state='disabled')
        def apply():
            try:
                self.export_options(selected_options())
                self.translator.update_preferences(selected_options())
            except (OSError, ValueError) as exc:
                self.error(str(exc)); return
            dialog.destroy()
        bottom = ttk.Frame(body)
        bottom.pack(fill='x', pady=(14,0))
        ttk.Button(bottom, text=self.t('미리보기'), command=preview).pack(side='left')
        ttk.Button(bottom, text=self.t('취소'), command=dialog.destroy).pack(side='right')
        ttk.Button(bottom, text=self.t('적용'), command=apply).pack(side='right', padx=8)
        self.install_help(body)

    def settings(self):
        if self.service and not self.busy:
            self.service.settings(self)

    def import_camera(self):
        if self.service and not self.busy:
            self.service.read(self)

    def drop(self, event):
        paths = self.root.tk.splitlist(event.data)
        if len(paths) != 1:
            self.error('한 번에 스캔 폴더 하나를 놓으세요.'); return
        self.choose_folder(paths[0])

    def choose_folder(self, folder=None):
        if not self.scan_enabled:
            return
        if self.busy:
            return
        try:
            self.selected()
        except ValueError as exc:
            self.error(str(exc)); return
        folder = folder or filedialog.askdirectory(title=self.t('스캔 폴더 선택'))
        if folder:
            self.folder = folder
            self.tabs.select(1)
            self.preview()

    def preview(self):
        if not self.scan_enabled:
            return
        self.mapping = None
        self.write_button.state(['disabled'])
        if self.busy or not self.folder:
            return
        try:
            entry = self.selected()
            start = int(self.start.get()) if self.start.get() else None
            folder, reverse = self.folder, self.reverse.get()
            iso_confirmed = self.iso_unchanged.get() is True
            context = (entry['id'], folder, reverse, self.start.get(), iso_confirmed)
            def ready(mapping):
                current = (self.selected()['id'], self.folder, self.reverse.get(), self.start.get(), self.iso_unchanged.get())
                if current == context:
                    self.show_mapping(mapping)
                else:
                    self.message('mapping_text', '선택이 바뀌었습니다. 폴더를 다시 선택해 대응표를 갱신하세요.')
            self.run(lambda: scans.make_mapping(folder, entry['roll'], reverse=reverse, start=start,
                     metadata={'iso_unchanged_confirmed': iso_confirmed}), ready)
        except (ValueError, OSError) as exc:
            self.error(str(exc))

    def show_mapping(self, mapping):
        self.mapping = mapping
        self.preview_table.delete(*self.preview_table.get_children())
        for pair in mapping.pairs:
            values = dict(pair.tags)
            summary = ' · '.join(label + values[key] + suffix for key, label, suffix in (
                ('EXIF:ExposureTime', '', self.t('초')), ('EXIF:FNumber', 'f/', ''),
                ('EXIF:FocalLength', '', 'mm'), ('EXIF:ISO', 'ISO ', ''),
                ('EXIF:ExposureCompensation', self.t('보정 '), ' EV')) if key in values)
            self.preview_table.insert('', 'end', values=(pair.path.name, pair.frame_number, summary))
        self.message('mapping_text', '{matched}개 대응 · 제외 파일 {files}개 · 미대응 컷 {frames}개 · 지원 외 항목 {ignored}개', matched=len(mapping.pairs), files=len(mapping.unmatched_files), frames=len(mapping.unmatched_frames), ignored=len(mapping.ignored_files))
        if mapping.pairs and self.exiftool and not self.busy:
            self.write_button.state(['!disabled'])

    def write(self):
        if not self.scan_enabled:
            return
        if self.busy or self.mapping is None:
            return
        mapping = self.mapping
        excluded = '\n'.join(mapping.unmatched_files) or self.t('없음')
        question = self.t('{count}개 파일의 촬영정보를 바꿉니다. 기존 카메라/노출 태그도 변경됩니다.\n원본은 파일명_original로 보관합니다.\n제외 파일: {excluded}\n미대응 컷: {frames}\n계속할까요?', count=len(mapping.pairs), excluded=excluded, frames=mapping.unmatched_frames)
        if not messagebox.askyesno(self.t('스캔에 촬영정보 쓰기'), question, parent=self.root):
            return
        self.write_button.state(['disabled'])
        def done(results):
            self.home.mkdir(parents=True, exist_ok=True)
            path = self.home / ('exif-result-' + uuid.uuid4().hex + '.json')
            path.write_text(json.dumps(results, ensure_ascii=False, indent=2), encoding='utf-8')
            ok = sum(r['status'] == 'verified' for r in results)
            self.message('mapping_text', '{ok}/{total}개 검증 완료 · 결과 기록: {path}', ok=ok, total=len(results), path=path)
            if ok != len(results):
                failure = next((r['error'] for r in results if r.get('error')), GENERIC_ERROR)
                self.error(failure)
            self.mapping = None
            self.write_button.state(['disabled'])
        self.run(lambda: scans.write_mapping(mapping, self.exiftool, confirmed=True), done)

    def close(self):
        if self.busy:
            messagebox.showinfo(self.t('작업 중'), self.t('현재 작업이 끝난 뒤 닫아 주세요.'), parent=self.root)
            return
        self.root.destroy()


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--demo', action='store_true')
    parser.add_argument('--home', type=Path, default=Path.home() / 'Library/Application Support/Neo Film Bridge')
    parser.add_argument('--exiftool', type=Path, help='Reserved for development; scan writing is excluded from this release')
    parser.add_argument('--smoke-ms', type=int, default=0, help='Development GUI launch test only')
    args = parser.parse_args()
    logdir = Path.home() / 'Library/Logs/Neo Film Bridge'
    logdir.mkdir(parents=True, exist_ok=True)
    logging.basicConfig(filename=logdir / 'app.log', level=logging.INFO)
    try:
        from tkinterdnd2 import TkinterDnD
        root = TkinterDnD.Tk()
    except ImportError:
        root = tk.Tk()
    from camera import CameraService
    app = App(root, args.home, camera_service=CameraService(args.home), exiftool=args.exiftool, demo=args.demo)
    root.report_callback_exception = lambda kind, value, tb: (logging.error('GUI callback', exc_info=(kind, value, tb)), app.error(GENERIC_ERROR))
    if args.smoke_ms:
        root.after(args.smoke_ms, app.close)
    root.mainloop()


if __name__ == '__main__':
    main()
