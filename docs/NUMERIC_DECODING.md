# Default numeric decoding

Shutter uses signed code / 6 as Tv; aperture uses code / 6 as Av; EV fields use signed code / 6. Standard photographic nominal ladders provide display labels. ISO uses a nominal third-stop ladder with observed anchors 1=6, 17=250, 19=400. Focal-length labels at observed codes come from aligned camera records; interpolation within the observed 28–105 mm range uses 5 * 2^(code/24) and is marked as an estimate. Outside that range unsupported focal codes remain raw.

Bulb E1 and missing aperture 64 are observed sentinels. Unobserved shutter gap codes (including E0, 4F, 70, 71) remain hex rather than being treated as physical exposure times. This is intentionally narrower than external application tables.

No extracted application resources are bundled. Optional external TSV labels override built-in labels when present. Missing tables need no warning under default formula policy. Explicit warn/raw and strict policies retain their previous fallback behavior. Raw codes are always preserved. Source metadata distinguishes observed anchors, formulas/estimates, external tables and unknown codes.

Offline comparison against preserved 117-frame data: 1053/1053 compared values agree after normalizing EV sign formatting and UNKNOWN/F-- for absent aperture. This does not prove every possible code or lens. Public synthetic tests cover known anchors, all byte inputs, signed boundaries, unknowns, policy behavior and table precedence. No new camera I/O was performed for this change.
