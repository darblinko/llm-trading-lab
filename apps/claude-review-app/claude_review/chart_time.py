"""Chart time convention shared by every payload builder.

Lightweight Charts renders Unix seconds as UTC. The app shows US/Eastern
wall-clock time, so every timestamp is converted to ET, stripped of its zone,
and encoded as if that wall-clock time were UTC.
"""

from datetime import datetime

import pandas as pd

ET_ZONE = "America/New_York"


def to_chart_time(value: datetime | pd.Timestamp | str) -> int:
    """Return ET wall-clock seconds for an aware timestamp, naive ET timestamp, or ISO string."""
    stamp = pd.Timestamp(value)
    if stamp.tzinfo is not None:
        stamp = stamp.tz_convert(ET_ZONE).tz_localize(None)
    return int(stamp.tz_localize("UTC").timestamp())
