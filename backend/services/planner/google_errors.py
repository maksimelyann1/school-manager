"""Technical diagnostics without response bodies, URLs or credentials."""
from pathlib import Path
import traceback

import httpx


def safe_google_error(error):
    status = getattr(error, 'status_code', None) or getattr(error, 'status', 0)
    if isinstance(error, httpx.HTTPStatusError):
        status = error.response.status_code
    causes, seen = [], set()
    current = error
    while current is not None and id(current) not in seen and len(causes) < 6:
        seen.add(id(current))
        name = f'{type(current).__module__}.{type(current).__name__}'
        codes = [f'{key}={value}' for key in ('errno', 'winerror', 'verify_code')
                 if isinstance(value := getattr(current, key, None), int)]
        causes.append(name + (f' ({", ".join(codes)})' if codes else ''))
        current = current.__cause__ or current.__context__
    frames = traceback.extract_tb(error.__traceback__)[-4:]
    location = ' > '.join(f'{Path(frame.filename).name}:{frame.lineno}:{frame.name}' for frame in frames)
    return f'{" <- ".join(causes)}, HTTP {status or 0}' + (f'; {location}' if location else '')
