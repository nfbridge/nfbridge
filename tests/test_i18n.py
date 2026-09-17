# SPDX-License-Identifier: GPL-3.0-only
import ast
import json
from pathlib import Path
import string
import sys
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'app'))
from i18n import EN, GENERIC_ERROR, Translator


class Languages(unittest.TestCase):
    def test_switch_persists_without_losing_other_preferences(self):
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / 'preferences.json'
            path.write_text(json.dumps({'last_export': '/example/folder'}))
            t = Translator(folder)
            self.assertEqual(t.text('기록 설정'), '기록 설정')
            t.set_language('en')
            self.assertEqual(Translator(folder).text('기록 설정'), 'Recording settings')
            self.assertEqual(json.loads(path.read_text())['last_export'], '/example/folder')
            t.set_language('ko')
            self.assertEqual(Translator(folder).language, 'ko')

    def test_bad_preferences_use_korean_and_invalid_language_is_rejected(self):
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / 'preferences.json'
            for value in ['{broken', '[]', '{"language":"unknown"}']:
                path.write_text(value)
                t = Translator(folder)
                self.assertEqual(t.language, 'ko')
                with self.assertRaises(ValueError):
                    t.set_language('fr')
                self.assertEqual(path.read_text(), value)

    def test_translation_placeholders_are_identical(self):
        formatter = string.Formatter()
        for ko, en in EN.items():
            fields = lambda text: {name for _, name, _, _ in formatter.parse(text) if name is not None}
            self.assertEqual(fields(ko), fields(en), ko)
            self.assertTrue(en.strip())

    def test_gui_and_backend_korean_strings_have_translations(self):
        for name in ('gui.py', 'scans.py', 'library.py', 'camera.py'):
            tree = ast.parse((ROOT / 'app' / name).read_text())
            for node in ast.walk(tree):
                if isinstance(node, ast.Constant) and isinstance(node.value, str):
                    if any('\uac00' <= c <= '\ud7a3' for c in node.value) and node.value != '한국어':
                        self.assertIn(node.value, EN, (name, node.lineno, node.value))

    def test_usb_first_connect_guidance_orders_macos_allow_before_yes(self):
        import ast
        tree = ast.parse((ROOT / 'app' / 'camera.py').read_text())
        strings = [n.value for n in ast.walk(tree) if isinstance(n, ast.Constant) and isinstance(n.value, str)]
        ko = next(s for s in strings if s.startswith('케이블/어댑터의 USB 쪽을 Mac에 연결하세요.'))
        self.assertIn('macOS가 액세서리 연결 허용을 물으면 먼저 허용하세요', ko)
        self.assertIn('확인한 다음에만', ko)
        self.assertLess(ko.index('먼저 허용'), ko.index('‘예’를 누르세요'))
        self.assertIn('카메라 쪽은 아직 연결하지 마세요', ko)
        en = EN[ko]
        self.assertIn('allow it first', en)
        self.assertIn('Only click Yes here after you confirm', en)
        self.assertLess(en.index('allow it first'), en.index('Only click Yes'))
        self.assertIn('camera end disconnected', en)

    def test_camera_power_on_guidance_orders_power_on_before_yes(self):
        import ast
        tree = ast.parse((ROOT / 'app' / 'camera.py').read_text())
        strings = [n.value for n in ast.walk(tree) if isinstance(n, ast.Constant) and isinstance(n.value, str)]
        ko = next(s for s in strings if s.startswith('F100의 전원이 꺼진 상태에서'))
        self.assertLess(ko.index('전원이 꺼진 상태에서 카메라에 케이블을 연결'), ko.index('F100의 전원을 켜세요'))
        self.assertLess(ko.index('F100의 전원을 켜세요'), ko.index('켜진 것을 확인한 다음에만'))
        self.assertIn('‘예’를 누르세요', ko)
        en = EN[ko]
        self.assertLess(en.index('powered off, connect the cable'), en.index('Then turn the F100 on'))
        self.assertLess(en.index('Then turn the F100 on'), en.index('Only click Yes here after you confirm'))

    def test_errors_and_dynamic_results_keep_user_data_exact(self):
        with tempfile.TemporaryDirectory() as folder:
            t = Translator(folder)
            t.set_language('en')
            filename = '사용자 {사진}.tif_original'
            message = '이전에 남겨둔 수정 전 사진이 있습니다. 기존 폴더는 보관하고, 작업할 JPEG/TIFF만 새 폴더로 복사해 선택하세요: ' + filename
            self.assertTrue(t.error(message).endswith(filename))
            self.assertEqual(t.error('Traceback internal secret'), EN[GENERIC_ERROR])
            key = '{ok}/{total}개 검증 완료 · 결과 기록: {path}'
            self.assertIn(filename, t.text(key, ok=2, total=3, path=filename))


if __name__ == '__main__':
    unittest.main()
