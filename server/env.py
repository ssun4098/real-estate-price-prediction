"""Environment-only configuration. Never discover another user's credential files."""
from __future__ import annotations
import os
from pathlib import Path
from urllib.parse import unquote

KEY_FIELDS = (
    ('vworld', 'VWORLD_API_KEY', '브이월드'),
    ('dataGoKr', 'DATA_GO_KR_API_KEY', '공공데이터포털'),
    ('juso', 'JUSO_API_KEY', '주소기반산업지원서비스'),
    ('vworldGeocoder', 'VWORLD_GEOCODER_API_KEY', '브이월드 Geocoder'),
    ('vworldSearch', 'VWORLD_SEARCH_API_KEY', '브이월드 Search'),
    ('kosis', 'KOSIS_API_KEY', 'KOSIS (선택)'),
    ('sgisId', 'SGIS_CONSUMER_KEY', 'SGIS ID (선택)'),
    ('sgisSecret', 'SGIS_CONSUMER_SECRET', 'SGIS 비밀값 (선택)'),
)
# FastAPI 서버(server/settings.py)가 쓰는 변수. 이 목록에 없는 이름이 .env에 있으면 오타로 보고 거부한다.
APP_NAMES = frozenset({'MYSQL_CONTAINER', 'MYSQL_NETWORK', 'MYSQL_HOST', 'MYSQL_PORT', 'MYSQL_USER', 'MYSQL_PASSWORD', 'MYSQL_DATABASE',
                       'DATABASE_URL', 'DB_CONNECT_RETRIES', 'PUBLIC_PORT', 'ALLOWED_HOSTS', 'ENABLE_DOCS',
                       'MODEL_ENTRYPOINT', 'MODEL_DIR', 'TEMPLATE_PATH', 'SAMPLES_DIR'})
ALLOWED_NAMES = frozenset(field[1] for field in KEY_FIELDS) | {'VWORLD_DOMAIN'} | APP_NAMES

class ConfigurationError(ValueError):
    """Messages contain field names/line numbers only, never supplied values."""

def load_environment(path: Path, environ=None):
    """Read only this .env; existing process variables win (even if empty).

    NAME=value, optional matching quotes and full-line comments are supported.
    No shell evaluation, interpolation, multiline values or inline comments.
    Parse everything before applying changes so a bad line cannot half-load.
    """
    env = os.environ if environ is None else environ
    path = Path(path)
    if not path.is_file():
        return
    if path.stat().st_size > 65536:
        raise ConfigurationError('.env 파일은 64KB 이하여야 합니다.')
    try:
        source = path.read_text(encoding='utf-8-sig')
    except (OSError, UnicodeError):
        raise ConfigurationError('.env 파일을 UTF-8 형식으로 저장하세요.') from None
    parsed = {}
    for number, line in enumerate(source.splitlines(), 1):
        line = line.strip()
        if not line or line.startswith('#'):
            continue
        if '=' not in line:
            raise ConfigurationError(f'.env {number}행: NAME=value 형식이 필요합니다.')
        name, value = (part.strip() for part in line.split('=', 1))
        if name not in ALLOWED_NAMES or name in parsed:
            raise ConfigurationError(f'.env {number}행: 지원하지 않거나 중복된 변수입니다.')
        if value.startswith(('"', "'")):
            if len(value) < 2 or value[-1] != value[0]:
                raise ConfigurationError(f'.env {number}행: 따옴표가 닫히지 않았습니다.')
            value = value[1:-1]
        if len(value) > 8192 or any(ord(char) < 32 for char in value):
            raise ConfigurationError(f'.env {number}행: 값의 형식이 올바르지 않습니다.')
        parsed[name] = value
    for name, value in parsed.items():
        env.setdefault(name, value)

def read_keys(environ=None):
    env = os.environ if environ is None else environ
    result = {}
    for name, variable, _ in KEY_FIELDS:
        value = env.get(variable, '').strip()
        if name == 'dataGoKr':
            value = unquote(value)  # Accept Encoding/Decoding key; decode once.
        if len(value) > 8192 or any(ord(char) < 32 for char in value):
            raise ConfigurationError(variable + ': 값의 형식이 올바르지 않습니다.')
        result[name] = value
    # One VWorld key may cover these services if its permissions allow it.
    result['vworldGeocoder'] = result['vworldGeocoder'] or result['vworld']
    result['vworldSearch'] = result['vworldSearch'] or result['vworld']
    return result
