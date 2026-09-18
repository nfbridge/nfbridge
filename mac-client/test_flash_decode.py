#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-3.0-only
"""Flash field decode regression tests (2026-09-19 closure).

Real F100 hardware evidence corrected the flash_type and flash_sync
semantic labels in f100_readonly.py::decode_lq(). This module tests both
the synthetic bit-domain tables (section 6 of the closure spec) and a
minimal set of real captured LQ detailed records (Roll 47/48).

Real evidence provenance (not bundled here as raw capture; this project's
publication policy keeps private captures in the private research archive):

  - F100Capture live-com-observe session
    20260919-002722-CameraCompanion-COM3, camera-to-host.bin
    sha256 be8875574f1bec731a9d37b2d4179f163ae29eccff7b0973808025f9b024d853
    (session-manifest.json sha256
    4266958c61383db02589028c8f287c69c5cebb1e2484f9c8f10c142b470c0bcc)
  - Camera Companion DB export flashdata_Frames.csv (Roll 47)
    sha256 12814d21ae06505029ccd9ea2e46a7c14527f1f6891ca90d2b2ba6ce2bc5ce40
  - Camera Companion DB export flashdata2_Frames.csv (Roll 48)
    sha256 404e84017477e207c1569963173ffae06979a1bb47bdeca1faa0eed99708aea1

  Both hosted in the separate F100-Mac-Connection-Development project's
  dynamic-analysis/runs/2026-09-19-* directories (2026-09-19), not part of
  this repository. The 13-byte records below were extracted from that
  captured LQ payload and cross-checked field-by-field against Camera
  Companion's own decoded CSV/TXT export for the same two rolls.

Run: python3 -m unittest test_flash_decode -v
"""

import unittest

import f100_readonly as m


def _record(hex13, table_policy="raw"):
    """Wrap one 13-byte detailed record hex string into a minimal decodable
    single-frame, single-roll LQ payload and return the decoded frame."""
    rec = bytes.fromhex(hex13)
    assert len(rec) == 13
    payload = bytes([0x01]) + bytes.fromhex("F30001") + rec + bytes([0x0D, 0xFD])
    result = m.decode_lq(payload, table_policy=table_policy)
    return result["rolls"][0]["frames"][0]


class FlashTypeDomainTests(unittest.TestCase):
    """rec[4] & 0x03. Real anchors: 0=off (widely observed), 1=non_ttl
    (Roll 48 frames 1-5), 3=ttl (Roll 47/48). 2 is unobserved/reserved."""

    def test_flash_type_table(self):
        cases = {0x00: "off", 0x01: "non_ttl", 0x02: "unknown(0x02)", 0x03: "ttl"}
        for code, expected in cases.items():
            with self.subTest(code=hex(code)):
                frame = _record(f"01421a3c{code:02x}003c6a161a000000")
                self.assertEqual(frame["flash_type"], expected)
                self.assertEqual(frame["flash_flags_raw"], f"0x{code:02x}")


class MultipleExposureTests(unittest.TestCase):
    """rec[4] bit 0x10 is an independent flag, not part of the flash-type
    value; it must not be confused with flash type 2/3."""

    def test_multiple_exposure_combinations(self):
        cases = [
            (0x03, "ttl", False),
            (0x13, "ttl", True),
            (0x10, "off", True),
        ]
        for code, expected_type, expected_me in cases:
            with self.subTest(code=hex(code)):
                frame = _record(f"01421a3c{code:02x}003c6a161a000000")
                self.assertEqual(frame["flash_type"], expected_type)
                self.assertEqual(frame["multiple_exposure"], expected_me)


class FlashSyncDomainTests(unittest.TestCase):
    """(rec[12] >> 4) & 0x07. Real anchors: 0=normal, 1=slow, 2=rear,
    3=red_eye, 4=red_eye_slow (Roll 47/48). 5/6/7 are unobserved under
    normal user operation and stay semantic unknown; rec[12] bit 7 is
    outside this field and is not labeled."""

    def test_flash_sync_table(self):
        cases = {
            0: "normal",
            1: "slow",
            2: "rear",
            3: "red_eye",
            4: "red_eye_slow",
            5: "unknown(0x05)",
            6: "unknown(0x06)",
            7: "unknown(0x07)",
        }
        for sync_bits, expected in cases.items():
            mode_flags = sync_bits << 4
            with self.subTest(sync_bits=sync_bits):
                frame = _record(f"01421a3c03003c6a161a0000{mode_flags:02x}")
                self.assertEqual(frame["flash_sync"], expected)
                self.assertEqual(frame["mode_flags_raw"], f"0x{mode_flags:02x}")

    def test_flash_sync_ignores_bit7(self):
        # rec[12] bit 7 is not part of the sync field; setting it must not
        # change the decoded sync label.
        frame_bit7_clear = _record("01421a3c03003c6a161a000020")
        frame_bit7_set = _record("01421a3c03003c6a161a0000a0")
        self.assertEqual(frame_bit7_clear["flash_sync"], "rear")
        self.assertEqual(frame_bit7_set["flash_sync"], "rear")


class FlashCompensationTests(unittest.TestCase):
    """rec[11], shares the existing generic 'ev' decode domain with
    manual_ev_diff/exposure_comp. No new decode path; this only confirms
    the real-hardware anchors match the existing signed(code)/6 formula."""

    def test_flash_comp_anchors(self):
        cases = {0x00: "0.0", 0x06: "+1.0", 0xFA: "-1.0"}
        for code, expected in cases.items():
            with self.subTest(code=hex(code)):
                frame = _record(f"01421a3c03003c6a161a00{code:02x}04", table_policy="formula")
                self.assertEqual(frame["flash_comp"], expected)
                self.assertEqual(frame["flash_comp_raw"], f"0x{code:02x}")


class RawPreservationTests(unittest.TestCase):
    def test_raw_preserved_for_known_and_unknown_flash_type(self):
        for code in (0x00, 0x02, 0x03):
            frame = _record(f"01421a3c{code:02x}003c6a161a000000")
            self.assertEqual(frame["flash_flags_raw"], f"0x{code:02x}")

    def test_raw_preserved_for_known_and_unknown_flash_sync(self):
        for sync_bits in (0, 5, 4):
            mode_flags = sync_bits << 4
            frame = _record(f"01421a3c03003c6a161a0000{mode_flags:02x}")
            self.assertEqual(frame["mode_flags_raw"], f"0x{mode_flags:02x}")


class RealRecordRegressionTests(unittest.TestCase):
    """Actual 13-byte records captured from Roll 47/48 (see module
    docstring for source evidence). Expected values were independently
    cross-checked against Camera Companion's own decoded CSV/TXT export
    for the same frames, not derived from this decoder."""

    ROLL_47 = "002f"
    ROLL_48 = "0030"

    def _real_frame(self, roll_hex, rec_hex):
        rec = bytes.fromhex(rec_hex)
        payload = bytes([0x01]) + bytes.fromhex("F3" + roll_hex) + rec + bytes([0x0D, 0xFD])
        result = m.decode_lq(payload, table_policy="raw")
        return result["rolls"][0]["frames"][0]

    def test_roll47_frame1_off_normal(self):
        f = self._real_frame(self.ROLL_47, "012a163c003c6a161ae0000004")
        self.assertEqual(f["flash_type"], "off")
        self.assertEqual(f["flash_sync"], "normal")
        self.assertFalse(f["multiple_exposure"])

    def test_roll47_frame2_ttl_normal(self):
        f = self._real_frame(self.ROLL_47, "022a163c033c6a161add000004")
        self.assertEqual(f["flash_type"], "ttl")
        self.assertEqual(f["flash_sync"], "normal")

    def test_roll47_frame3_flash_comp_plus_one(self):
        f = self._real_frame(self.ROLL_47, "032a163c033c6a161ade000604")
        self.assertEqual(f["flash_type"], "ttl")
        self.assertEqual(f["flash_comp_raw"], "0x06")

    def test_roll47_frame4_flash_comp_minus_one(self):
        f = self._real_frame(self.ROLL_47, "042a163c033c6a161ade00fa04")
        self.assertEqual(f["flash_type"], "ttl")
        self.assertEqual(f["flash_comp_raw"], "0xfa")

    def test_roll47_frame6_rear(self):
        f = self._real_frame(self.ROLL_47, "062a163c033c6a161add000624")
        self.assertEqual(f["flash_type"], "ttl")
        self.assertEqual(f["flash_sync"], "rear")

    def test_roll47_frame8_slow(self):
        f = self._real_frame(self.ROLL_47, "08041a3c033c6a161a00000018")
        self.assertEqual(f["flash_type"], "ttl")
        self.assertEqual(f["flash_sync"], "slow")

    def test_roll47_frame9_red_eye_slow(self):
        f = self._real_frame(self.ROLL_47, "09041a3c033c6a161a00000048")
        self.assertEqual(f["flash_type"], "ttl")
        self.assertEqual(f["flash_sync"], "red_eye_slow")

    def test_roll47_frame10_multiple_exposure_on(self):
        f = self._real_frame(self.ROLL_47, "0a241a3c133c6a161ae1000008")
        self.assertEqual(f["flash_type"], "ttl")
        self.assertTrue(f["multiple_exposure"])

    def test_roll47_frame11_off_multiple_exposure_on(self):
        f = self._real_frame(self.ROLL_47, "0b041a3c103c6a161a00000008")
        self.assertEqual(f["flash_type"], "off")
        self.assertTrue(f["multiple_exposure"])

    def test_roll48_frame1_non_ttl_normal(self):
        f = self._real_frame(self.ROLL_48, "01241a3c013c6a161ae2000008")
        self.assertEqual(f["flash_type"], "non_ttl")
        self.assertEqual(f["flash_sync"], "normal")

    def test_roll48_frame2_non_ttl_red_eye(self):
        f = self._real_frame(self.ROLL_48, "02241a3c013c6a161adf000038")
        self.assertEqual(f["flash_type"], "non_ttl")
        self.assertEqual(f["flash_sync"], "red_eye")

    def test_roll48_frame6_ttl_normal(self):
        f = self._real_frame(self.ROLL_48, "06241a3c033c6a161ae3000008")
        self.assertEqual(f["flash_type"], "ttl")
        self.assertEqual(f["flash_sync"], "normal")


if __name__ == "__main__":
    unittest.main()
