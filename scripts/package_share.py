"""Allowlist-based ZIP export. Never archive the entire working directory."""
from __future__ import annotations
import argparse
import hashlib
import json
import os
from pathlib import Path
import re
import sys
from urllib.parse import quote, quote_plus
import zipfile

ROOT = Path(__file__).resolve().parents[1]
ROOT_FILES = {'V6.py', 'V6.html', 'README.md', 'requirements.txt', '.env.example', '.gitignore'}
FRONT_FILES = {'AGENTS.md', 'index.html', 'package.json', 'package-lock.json',
               'protected-runtime.json', 'vite.config.js', '.openai/hosting.json'}
BLOCKED_PARTS = {'node_modules', '__pycache__', '.git', '.venv', 'runtime',
                 'dist', '.data-app-offline', '.pytest_cache', '.vite'}
BLOCKED_SUFFIXES = {'.bin', '.key', '.pem', '.p12', '.pfx', '.log', '.db',
                    '.sqlite', '.sqlite3', '.pyc', '.pyo', '.zip'}


def allowed(relative):
    if relative in ROOT_FILES:
        return True
    p = Path(relative)
    if p.suffix.lower() in BLOCKED_SUFFIXES or any(part in BLOCKED_PARTS for part in p.parts):
        return False
    if any(part.startswith('.env') or 'credentials' in part.lower() for part in p.parts):
        return False
    if len(p.parts) == 2 and p.parts[0] in ('backend', 'tests', 'scripts'):
        return p.suffix == '.py'
    if relative == 'web/V6.template.html':
        return True
    if len(p.parts) == 2 and p.parts[0] == 'samples':
        return p.name == 'default.json' or (p.name.startswith('pf-sample-') and p.suffix == '.json')
    if p.parts[0] == 'frontend':
        local = '/'.join(p.parts[1:])
        if local in FRONT_FILES:
            return True
        if len(p.parts) == 2 and p.name.startswith('test-') and p.suffix in ('.mjs', '.json'):
            return True
        if len(p.parts) > 2 and p.parts[1] in ('src', 'scripts', 'docs', 'tests'):
            return p.suffix in ('.js', '.jsx', '.mjs', '.ts', '.tsx', '.css', '.json', '.md',
                                '.svg', '.png', '.jpg', '.jpeg', '.webp', '.woff', '.woff2')
    return False


def known_secret_forms():
    sys.path.insert(0, str(ROOT / 'backend'))
    from pf_config import KEY_FIELDS, load_environment
    from_file = {}
    load_environment(ROOT / '.env', from_file)
    values = {source.get(var, '').strip() for source in (os.environ, from_file)
              for _, var, _ in KEY_FIELDS} - {''}
    forms = set()
    from urllib.parse import unquote
    for raw in values:
        for value in (raw, unquote(raw)):
            forms.update(v.encode('utf-8') for v in (value, quote(value, safe=''), quote_plus(value)))
    return forms


def build(output):
    # No local filesystem path or credential is written into the manifest.
    output = Path(output).resolve()
    if output.exists():
        raise ValueError('ZIP이 이미 있습니다. --output으로 새 이름을 지정하세요.')
    files = []
    secrets = known_secret_forms()
    for path in sorted(ROOT.rglob('*')):
        relative = path.relative_to(ROOT).as_posix()
        if not path.is_file() or not allowed(relative):
            continue
        if path.is_symlink() or not path.resolve().is_relative_to(ROOT):
            raise ValueError('연결된 외부 파일은 포함할 수 없습니다: ' + relative)
        data = path.read_bytes()
        if any(secret in data for secret in secrets):
            raise ValueError('인증키가 포함된 파일이 있어 중단했습니다: ' + relative)
        if re.search(rb'-----BEGIN (?:RSA |EC |OPENSSH )?PRIVATE KEY-----', data):
            raise ValueError('개인키가 포함된 파일이 있어 중단했습니다: ' + relative)
        files.append((relative, data))
    required = ROOT_FILES | {'backend/pf_config.py', 'backend/pf_server.py',
                             'web/V6.template.html', 'samples/default.json'}
    if not required.issubset({name for name, _ in files}):
        raise ValueError('필수 프로젝트 파일이 누락되었습니다.')
    checksums = {name: hashlib.sha256(data).hexdigest() for name, data in files}
    manifest = json.dumps({'format': 1, 'files': checksums}, ensure_ascii=False, indent=2).encode('utf-8')
    temporary = output.with_name(output.name + '.tmp')
    try:
        with zipfile.ZipFile(temporary, 'x', compression=zipfile.ZIP_DEFLATED, compresslevel=9) as archive:
            for name, data in files:
                archive.writestr('V6_team_share/' + name, data)
            archive.writestr('V6_team_share/CHECKSUMS.json', manifest)
        temporary.replace(output)
    finally:
        temporary.unlink(missing_ok=True)
    return len(files) + 1


def main():
    parser = argparse.ArgumentParser(description='환경변수·개인 실행 결과를 제외한 공유 ZIP 생성')
    parser.add_argument('--output', type=Path, default=ROOT.parent / 'V6_team_share.zip')
    args = parser.parse_args()
    try:
        count = build(args.output)
    except (ValueError, OSError) as exc:
        # Configuration/validation errors do not include secret values.
        raise SystemExit(str(exc)) from None
    print(f'공유 ZIP 생성 완료: {args.output.name} ({count}개 파일)')


if __name__ == '__main__':
    main()
