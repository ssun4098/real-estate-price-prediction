"""전체 테스트 실행: python tests/run_tests.py  (외부 API·인증키·MySQL 없이 동작)"""
from pathlib import Path
import sys
import unittest

root = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(root), str(root / 'tests')]  # server 패키지, 테스트끼리 import(test_engine 등)
suite = unittest.defaultTestLoader.discover(str(root / 'tests'), pattern='test_*.py')
result = unittest.TextTestRunner(verbosity=1).run(suite)
raise SystemExit(0 if result.wasSuccessful() else 1)
