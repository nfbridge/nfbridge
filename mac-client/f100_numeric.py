# SPDX-License-Identifier: GPL-3.0-only
"""Capture-derived numeric decoding with standard photographic nominal labels.

No external application tables are loaded here. Raw codes remain in the caller.
Formula extrapolations are identified separately from camera-observed anchors.
"""

_F_THIRDS = ['1', '1.1', '1.2', '1.4', '1.6', '1.8', '2', '2.2', '2.5', '2.8', '3.2', '3.5', '4', '4.5', '5', '5.6', '6.3', '7.1', '8', '9', '10', '11', '13', '14', '16', '18', '20', '22', '25', '29', '32', '36', '40', '45', '51', '57', '64']
_T_THIRDS = ['30"', '25"', '20"', '15"', '13"', '10"', '8"', '6"', '5"', '4"', '3"', '2.5"', '2"', '1.6"', '1.3"', '1"', '1.3', '1.6', '2', '2.5', '3', '4', '5', '6', '8', '10', '13', '15', '20', '25', '30', '40', '50', '60', '80', '100', '125', '160', '200', '250', '320', '400', '500', '640', '800', '1000', '1250', '1600', '2000', '2500', '3200', '4000', '5000', '6400', '8000']
_ISO_LADDER = ['6', '8', '10', '12', '16', '20', '25', '32', '40', '50', '64', '80', '100', '125', '160', '200', '250', '320', '400', '500', '640', '800', '1000', '1250', '1600', '2000', '2500', '3200', '4000', '5000', '6400']

_FOCAL_OBSERVED = {60:28, 66:34, 73:40, 75:44, 78:48, 80:50, 86:60, 90:66, 95:78, 101:92, 106:105}
_OBSERVED = {
    "shutter": {0x0e,0x20,0x22,0x24,0x26,0x34,0x36,0x3c,0x42,0x48,0x4e,0xe1,0xe2},
    "aperture": {0x0a,0x0c,0x16,0x18,0x19,0x1a,0x1c,0x28,0x2a,0x2e,0x30,0x36,0x38,0x3a,0x64},
}

def signed(code):
    return code - 256 if code >= 128 else code


def display(kind, code):
    """Return (label, provenance). Unsupported/special codes stay explicit."""
    unknown = (f"0x{code:02x}", "unknown")
    if kind == "shutter":
        if code == 0xe1:
            return "BULB", "camera_observed"
        # The gap contains special encodings: never extrapolate an exposure time.
        if not (0 <= code <= 0x4e or 0xe2 <= code <= 0xff):
            return unknown
        v = signed(code)
        if v % 2 == 0:
            label = _T_THIRDS[v // 2 + 15]
            if not label.endswith('"'):
                label = "1/" + label
        else:
            seconds = 2 ** (-v / 6)
            label = f'{seconds:.2g}"' if seconds >= 1 else f"1/{1/seconds:.3g}"
    elif kind == "aperture":
        if code == 0x64:
            return "F--", "camera_observed"
        if not 0 <= code <= 72:
            return unknown
        label = _F_THIRDS[code // 2] if code % 2 == 0 else f"{2 ** (code / 12):.1f}"
    elif kind == "focal_length":
        if code == 0:
            return "-", "camera_observed"
        if code in _FOCAL_OBSERVED:
            return str(_FOCAL_OBSERVED[code]), "camera_observed"
        # No arbitrary extrapolation beyond the observed lens range.
        if not 60 <= code <= 106:
            return unknown
        return str(round(5 * 2 ** (code / 24))), "formula_estimate"
    elif kind == "ev":
        v = signed(code) / 6
        return ("0.0" if v == 0 else f"{v:+.1f}"), "capture_derived_formula"
    elif kind == "iso":
        if not 1 <= code <= len(_ISO_LADDER):
            return unknown
        return _ISO_LADDER[code-1], "camera_observed" if code in {1,17,19} else "nominal_ladder"
    else:
        return unknown
    return label, "camera_observed" if code in _OBSERVED[kind] else "formula_estimate"
