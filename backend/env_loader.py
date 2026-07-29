#!/usr/bin/env python3
"""Load env vars from start.sh into os.environ"""
import os

_path = "/www/wujing-api/start.sh"
if os.path.exists(_path):
    with open(_path) as _f:
        for _line in _f:
            _line = _line.strip()
            if _line.startswith("export "):
                _parts = _line[7:].split("=", 1)
                if len(_parts) == 2:
                    _k = _parts[0].strip()
                    _v = _parts[1].strip().strip("'\"")
                    if _k and _v:
                        os.environ.setdefault(_k, _v)
