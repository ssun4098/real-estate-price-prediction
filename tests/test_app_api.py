"""FastAPI layer smoke tests. Use SQLite in place of MySQL; skipped if FastAPI is not installed."""
import os
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

try:
    from fastapi.testclient import TestClient
    from app.settings import Settings
    from app.main import create_app
    HAVE_APP = True
except ImportError:  # legacy `python V6.py` installs do not include FastAPI
    HAVE_APP = False

from test_engine import fixture

KEY = 'KEY-ABC-123'


@unittest.skipUnless(HAVE_APP, 'fastapi/sqlalchemy not installed')
class AppApiTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.directory = tempfile.TemporaryDirectory()
        cls.env = {'DATABASE_URL': 'sqlite:///' + os.path.join(cls.directory.name, 't.db').replace('\\', '/'),
                   'MYSQL_PASSWORD': 'db-secret-pw', 'DATA_GO_KR_API_KEY': KEY}
        cls.saved = {k: os.environ.get(k) for k in cls.env}
        os.environ.update(cls.env)
        cls.client = TestClient(create_app(Settings.from_env()), base_url='http://127.0.0.1:4175')
        cls.client.__enter__()

    @classmethod
    def tearDownClass(cls):
        cls.client.__exit__(None, None, None)
        for key, value in cls.saved.items():
            os.environ.pop(key, None) if value is None else os.environ.__setitem__(key, value)
        cls.directory.cleanup()

    def test_host_and_origin_guard(self):
        self.assertEqual(self.client.get('/api/status', headers={'host': 'evil.com'}).status_code, 403)
        self.assertEqual(self.client.get('/api/status', headers={'origin': 'http://evil.com'}).status_code, 403)
        self.assertEqual(self.client.get('/api/status').status_code, 200)

    def test_model_absent_is_reported_not_fatal(self):
        self.assertEqual(self.client.get('/api/model/status').json()['state'], 'not_configured')
        response = self.client.post('/api/model/predict', json={'features': {'a': 1}})
        self.assertEqual((response.status_code, response.json()['error']['code']), (503, 'MODEL_NOT_READY'))

    def test_snapshot_roundtrip_and_key_rejection(self):
        analyzed = self.client.post('/api/analyze', json=fixture()).json()
        saved = self.client.post('/api/save', json=analyzed).json()
        self.assertIn(saved['id'], [i['id'] for i in self.client.get('/api/snapshots').json()['items']])
        self.assertEqual(self.client.get('/api/snapshots/' + saved['id']).status_code, 200)
        self.assertEqual(self.client.get('/api/snapshots/pf-missing').status_code, 404)
        rejected = self.client.post('/api/save', json={**analyzed, 'name': KEY})
        self.assertEqual(rejected.status_code, 400)
        self.assertNotIn(KEY, rejected.text)

    def test_portfolio_default_and_input_limits(self):
        analyzed = self.client.post('/api/analyze', json=fixture()).json()
        sample = self.client.post('/api/portfolio-samples', json={'snapshot': analyzed}).json()
        self.client.post('/api/portfolio-default', json={'id': sample['id']})
        self.assertEqual(self.client.get('/api/portfolio-default').json()['id'], sample['id'])
        self.assertEqual(self.client.post('/api/portfolio-default', json={'id': '../x'}).status_code, 400)
        self.assertEqual(self.client.post('/api/analyze', content='{}', headers={'content-type': 'text/plain'}).status_code, 415)
        self.assertEqual(self.client.post('/api/analyze', content='{"a": NaN}', headers={'content-type': 'application/json'}).status_code, 400)

    def test_dashboard_embeds_samples(self):
        page = self.client.get('/')
        self.assertEqual(page.status_code, 200)
        self.assertIn('window.__PF_PORTFOLIO__=', page.text)
        self.assertNotIn(KEY, page.text)


@unittest.skipUnless(HAVE_APP, 'fastapi/sqlalchemy not installed')
class ExistingDatabaseTests(unittest.TestCase):
    """이미 자료가 들어 있는 MySQL을 쓸 때: 앱이 남의 테이블을 건드리지 않는지."""

    def test_keeps_other_tables_and_stops_on_conflict(self):
        import sqlite3
        from app import db
        with tempfile.TemporaryDirectory() as directory:
            path = os.path.join(directory, 'existing.db')
            with sqlite3.connect(path) as con:
                con.execute('create table land_trades_10y (id int, price int)')
                con.execute('insert into land_trades_10y values (1, 100)')
            db.close(db.connect('sqlite:///' + path.replace('\\', '/'), 1))
            with sqlite3.connect(path) as con:
                self.assertEqual(con.execute('select * from land_trades_10y').fetchall(), [(1, 100)])
            con.close()

            conflict = os.path.join(directory, 'conflict.db')
            with sqlite3.connect(conflict) as con:
                con.execute('create table land_pages (x int)')
                con.execute('insert into land_pages values (7)')
            con.close()
            with self.assertRaises(RuntimeError):
                db.connect('sqlite:///' + conflict.replace('\\', '/'), 1)
            with sqlite3.connect(conflict) as con:
                self.assertEqual(con.execute('select * from land_pages').fetchall(), [(7,)])
            con.close()


if __name__ == '__main__':
    unittest.main()
