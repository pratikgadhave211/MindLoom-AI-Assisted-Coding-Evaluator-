import json
import os
import re
from pathlib import Path
from urllib.parse import unquote, urlsplit

from dotenv import dotenv_values


def log_event(name, data):
    # Logs include prompt and workspace content. Hide configured credentials.
    values = dotenv_values(Path(__file__).resolve().parents[2] / '.env', interpolate=False)
    values.update({key: value for key, value in os.environ.items()
                   if key in values or any(part in key.upper() for part in ('KEY', 'TOKEN', 'PASSWORD'))})
    text = json.dumps(data, ensure_ascii=True, default=str)
    for key, value in values.items():
        if value and any(part in key.upper() for part in ('KEY', 'TOKEN', 'PASSWORD')) and len(value) >= 8:
            text = text.replace(value, '[redacted]')
    database_url = values.get('CHECKPOINT_DATABASE_URL') or ''
    password = urlsplit(database_url).password
    if password:
        for value in (password, unquote(password)):
            if len(value) >= 8:
                text = text.replace(value, '[redacted]')
    text = re.sub(r'\b(?:sk-or-v1-|lsv2_|apikey_)[A-Za-z0-9_-]+', '[redacted]', text)
    print(f'[agent] {name}: {text}', flush=True)


def log_error(name, error):
    # Do not print raw SDK exceptions: they can include authentication headers.
    details = {'type': type(error).__name__, 'status_code': getattr(error, 'status_code', None)}
    body = getattr(error, 'body', None)
    try:
        body = json.loads(body) if isinstance(body, str) else body
        if isinstance(body, dict) and isinstance(body.get('error'), dict):
            item = body['error']
            metadata = item.get('metadata') or {}
            details.update({'message': item.get('message'), 'code': item.get('code'),
                            'provider': metadata.get('provider_name')})
            raw = metadata.get('raw')
            raw = json.loads(raw) if isinstance(raw, str) else raw
            if isinstance(raw, dict):
                details['provider_message'] = raw.get('msg') or raw.get('message')
    except (ValueError, TypeError, AttributeError):
        pass
    log_event(name, details)
