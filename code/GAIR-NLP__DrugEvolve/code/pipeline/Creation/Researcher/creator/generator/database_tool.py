"""Optional read-only database access, exposed only to the design agent."""
from __future__ import annotations

import json
import os
from pathlib import Path
from urllib.parse import urlencode, urljoin, urlsplit, unquote
from urllib.request import Request, build_opener, HTTPRedirectHandler
from urllib.error import HTTPError, URLError
from agents import function_tool

NAMES = {'chembl', 'bindingdb', 'string', 'drugbank', 'pubmed'}
MAX_BYTES = 40000

class NoRedirect(HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        return None


def load_config():
    path = os.getenv('DRUGEVOLVE_COGNITION_DATABASES', '').strip()
    if not path:
        return {}
    data = json.loads(Path(path).expanduser().read_text(encoding='utf-8'))
    databases = data.get('databases', {})
    if not isinstance(databases, dict) or set(databases) - NAMES:
        raise ValueError('Invalid cognition database configuration')
    for name, entry in databases.items():
        if not isinstance(entry, dict):
            raise ValueError(f'Invalid database entry: {name}')
        if entry.get('enabled'):
            base = urlsplit(entry.get('base_url', ''))
            if base.scheme != 'https' or not base.hostname or base.username or base.password or base.query or base.fragment:
                raise ValueError(f'{name}: base_url must be an HTTPS base URL without credentials or query')
            if entry.get('api_key_env') and not entry['api_key_env'].startswith('DRUGEVOLVE_'):
                raise ValueError(f'{name}: api_key_env must start with DRUGEVOLVE_')
    return databases


def query_database(database: str, path: str, params: dict[str, str]) -> str:
    databases = load_config()
    entry = databases.get(database, {})
    if not entry.get('enabled'):
        return 'Database is not enabled.'
    decoded = unquote(path)
    if (not path or path.startswith('/') or '\\' in decoded or any(s in {'.', '..'} for s in decoded.split('/'))
            or urlsplit(path).scheme or urlsplit(path).netloc or '?' in path or '#' in path):
        return 'Invalid relative API path.'
    if len(params) > 20 or any(len(str(k)) > 100 or len(str(v)) > 1000 for k, v in params.items()):
        return 'Query parameters exceed limits.'
    base = entry['base_url'].rstrip('/') + '/'
    url = urljoin(base, path)
    if not url.startswith(base):
        return 'Invalid relative API path.'
    if params:
        url += '?' + urlencode(params)
    headers = {'Accept': 'application/json, text/plain;q=0.9', 'User-Agent': 'DrugEvolve/0.1 (research)'}
    key_name = entry.get('api_key_env')
    if key_name:
        value = os.getenv(key_name, '')
        if not value:
            return f'Missing credential environment variable: {key_name}'
        headers[entry.get('auth_header', 'Authorization')] = entry.get('auth_prefix', 'Bearer ') + value
    try:
        with build_opener(NoRedirect()).open(Request(url, headers=headers), timeout=20) as response:
            body = response.read(MAX_BYTES + 1)
            truncated = len(body) > MAX_BYTES
            return json.dumps({'database': database, 'request_url': url, 'status': response.status,
                'content_type': response.headers.get('Content-Type', ''), 'truncated': truncated,
                'data': body[:MAX_BYTES].decode('utf-8', errors='replace')}, ensure_ascii=False)
    except HTTPError as exc:
        return f'{database} request failed: HTTP {exc.code} (redirects are disabled).'
    except (URLError, OSError, ValueError) as exc:
        return f'{database} request failed: {type(exc).__name__}'


@function_tool
def search_scientific_database(database: str, path: str, params_json: str) -> str:
    """GET data from an enabled database for research design. Use its official API documentation.

    Args:
        database: One of chembl, bindingdb, string, drugbank, pubmed.
        path: Relative endpoint path under the configured API base URL.
        params_json: JSON object of query parameters, without credentials, e.g. {"format":"json"}.
    """
    try:
        params = json.loads(params_json)
        if not isinstance(params, dict) or not all(isinstance(k, str) and isinstance(v, str) for k, v in params.items()):
            return 'Query parameters must be a JSON object of string keys and string values.'
        return query_database(database.lower(), path, params)
    except (ValueError, TypeError):
        return 'Invalid query parameter JSON.'
