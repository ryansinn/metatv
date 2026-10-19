"""Tag confidence levels (DR-0006) — split out of channel_name_utils (ledger F30).
"""

from __future__ import annotations



# ── Confidence constants (DR-0006) ───────────────────────────────────────────── #
# Coarse, documented scale — tunable without changing the test assertions.
# "denoted"      = the facet the code explicitly means in IPTV convention (~0.9)
# "strong prior" = a real, plausible adjacent guess (~0.3)
# "weak prior"   = a real but low-probability adjacent guess (~0.15)
CONF_DENOTED: float = 0.9
CONF_STRONG_PRIOR: float = 0.3
CONF_WEAK_PRIOR: float = 0.15
