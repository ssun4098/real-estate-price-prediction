#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""개발사업성 분석 V6 — team edition. Run: python V6.py"""
from pathlib import Path
import json
import sys

ROOT = Path(__file__).resolve().parent

def main():
    if sys.version_info < (3, 11):
        raise SystemExit('Python 3.11 이상이 필요합니다. Python 3.12 또는 3.13을 권장합니다.')
    sys.path.insert(0, str(ROOT / 'backend'))
    from pf_config import ConfigurationError, load_environment
    from pf_server import main as serve
    try:
        load_environment(ROOT / '.env')
        portfolio = [json.loads(path.read_text('utf-8'))
                     for path in sorted((ROOT / 'samples').glob('pf-sample-*.json'))]
        default_id = json.loads((ROOT / 'samples/default.json').read_text('utf-8'))['id']
        serve(html_template=(ROOT / 'web/V6.template.html').read_text('utf-8'),
              output_dir=ROOT / 'runtime/outputs',
              bundled_portfolio=portfolio, bundled_default_id=default_id)
    except ConfigurationError as exc:
        raise SystemExit(str(exc)) from None

if __name__ == '__main__':
    main()
