"""Private regular expressions for parsing server output."""

from __future__ import annotations

import re

SERVER_READY_RE: re.Pattern[str] = re.compile(
    r'^server\s+"(?P<name>[^"]+)"\s+=\s+'
    r'(?P<host>[\d.]+):(?P<port>\d+)\s+'
    r'\(password\s+"(?P<password>[^"]+)"\)'
)
