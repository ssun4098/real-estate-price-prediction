"""저장 규칙 테스트 (분석 저장·샘플 선반·비밀값 차단). SQLite로 MySQL을 대신한다."""
import json
import os
import re
import sqlite3
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

try:
    from fastapi.testclient import TestClient
    from server.settings import Settings
    from server.main import create_app
    HAVE_APP = True
except ImportError:
    HAVE_APP = False

from server.domain.engine import analyze
from test_engine import fixture

SECRET = 'TEST_SECRET_NEVER_PUBLISH_847295'


def embedded(html, name):
    match = re.search(r'window\.' + re.escape(name) + r'=(.*?);(?:window\.|</script>)', html)
    return json.loads(match.group(1))


@unittest.skipUnless(HAVE_APP, 'fastapi/sqlalchemy not installed')
class StorageRuleTests(unittest.TestCase):
    """테스트마다 빈 DB와 빈 samples 폴더로 새 서버를 켠다."""

    def setUp(self):
        self.folder = tempfile.TemporaryDirectory()
        root = Path(self.folder.name)
        self.db_path = root / 'test.db'
        self.samples = root / 'samples'
        self.samples.mkdir()
        self.env = {'DATABASE_URL': 'sqlite:///' + self.db_path.as_posix(), 'MYSQL_PASSWORD': 'db-pw',
                    'SAMPLES_DIR': str(self.samples),
                    'VWORLD_API_KEY': SECRET, 'JUSO_API_KEY': SECRET, 'DATA_GO_KR_API_KEY': SECRET}
        self.saved_env = {k: os.environ.get(k) for k in self.env}
        os.environ.update(self.env)

    def tearDown(self):
        for key, value in self.saved_env.items():
            os.environ.pop(key, None) if value is None else os.environ.__setitem__(key, value)
        self.folder.cleanup()

    def client(self):
        return TestClient(create_app(Settings.from_env()), base_url='http://127.0.0.1:4175')

    def save_sample(self, client, name='현재 27필지 분석', display=None):
        body = {'name': name, 'snapshot': analyze(fixture(), partial=True), 'displayState': display or {
            'address': '경기도 안산시 상록구 장상동',
            'survey': {'status': 'partial', 'rows': [{'type': 'school', 'lon': 126.8, 'lat': 37.3}]}}}
        response = client.post('/api/portfolio-samples', json=body)
        self.assertEqual(response.status_code, 200, response.text)
        return response.json()

    def test_default_is_explicit_and_not_replaced_by_save_or_listing_order(self):
        with self.client() as client:
            first = self.save_sample(client)
            self.assertIsNone(client.get('/api/portfolio-default').json()['id'])
            client.post('/api/portfolio-default', json={'id': first['id']})
            self.save_sample(client, '추가 저장')
            listing = client.get('/api/portfolio-samples').json()
            self.assertEqual(listing['defaultId'], first['id'])
            self.assertEqual([row['id'] for row in listing['items'] if row['isDefault']], [first['id']])
            self.assertEqual(client.post('/api/portfolio-default', json={'id': '../V5.html'}).status_code, 400)
        with self.client() as restarted:  # 다시 켜도 그대로
            page = restarted.get('/').text
            self.assertEqual(embedded(page, '__PF_DEFAULT_SAMPLE_ID__'), first['id'])
            self.assertEqual(embedded(page, '__PF_SNAPSHOT__'), first['snapshot'])
            self.assertEqual(len(embedded(page, '__PF_PORTFOLIO__')), 2)

    def test_bundled_capture_is_not_recalculated_and_default_can_move(self):
        with self.client() as client:
            item = self.save_sample(client)
        item = {k: v for k, v in item.items() if k not in ('fileName', 'storage')}
        (self.samples / (item['id'] + '.json')).write_text(json.dumps(item, ensure_ascii=False), 'utf-8')
        (self.samples / 'default.json').write_text(json.dumps({'id': item['id']}), 'utf-8')
        self.db_path.unlink()  # 빈 DB: samples 폴더의 기본 제공본만 있는 상태
        with patch('server.features.portfolio.validate_snapshot', side_effect=AssertionError('frozen capture recalculated')):
            with self.client() as client:
                restored = client.get('/api/portfolio-samples/' + item['id']).json()
                self.assertEqual(client.get('/api/portfolio-default').json()['id'], item['id'])
        self.assertEqual(restored['snapshot'], item['snapshot'])
        self.assertEqual(restored['displayState'], item['displayState'])
        with self.client() as client:
            another = self.save_sample(client, '실제 사용자가 저장한 분석')
            self.assertEqual(client.get('/api/portfolio-default').json()['id'], item['id'])
            client.post('/api/portfolio-default', json={'id': another['id']})
        with self.client() as restarted:
            self.assertEqual(restarted.get('/api/portfolio-default').json()['id'], another['id'])
            self.assertEqual(len(restarted.get('/api/portfolio-samples').json()['items']), 2)

    def test_missing_default_does_not_silently_choose_a_new_sample(self):
        with self.client() as client:
            item = self.save_sample(client)
            client.post('/api/portfolio-default', json={'id': item['id']})
            with sqlite3.connect(self.db_path) as con:
                con.execute('delete from portfolio_samples where id = ?', (item['id'],))
            con.close()
            self.save_sample(client, '다른 분석')
            self.assertIsNone(client.get('/api/portfolio-default').json()['id'])

    def test_view_and_map_roundtrip_with_validation_and_explicit_fields(self):
        with self.client() as client:
            saved = self.save_sample(client, display={
                'viewState': {'main': 'finance', 'tab': 'parcels', 'unknown': 'drop'},
                'mapView': {'lon': 126.87536, 'lat': 37.35761, 'z': 18, 'unknown': 'drop'}})
            restored = client.get('/api/portfolio-samples/' + saved['id']).json()['displayState']
            self.assertEqual(restored['viewState'], {'main': 'finance', 'tab': 'parcels'})
            self.assertEqual(restored['mapView'], {'lon': 126.87536, 'lat': 37.35761, 'z': 18})
            invalid = [
                {'viewState': {'main': 'settings', 'tab': 'parcels'}},
                {'viewState': {'main': 'survey', 'tab': 'arbitrary'}},
                {'mapView': {'lon': '126.8', 'lat': 37.3, 'z': 18}},
                {'mapView': {'lon': True, 'lat': 37.3, 'z': 18}},
                {'mapView': {'lon': 181, 'lat': 37.3, 'z': 18}},
                {'mapView': {'lon': 126.8, 'lat': 90, 'z': 18}},
                {'mapView': {'lon': 126.8, 'lat': 37.3, 'z': 23}},
            ]
            snapshot = analyze(fixture(), partial=True)
            for display in invalid:
                with self.subTest(display=display):
                    response = client.post('/api/portfolio-samples', json={'snapshot': snapshot, 'displayState': display})
                    self.assertEqual(response.status_code, 400)
            self.assertEqual(len(client.get('/api/portfolio-samples').json()['items']), 1)

    def test_http_never_exposes_keys_or_serves_env_file(self):
        with self.client() as client:
            status = client.get('/api/status')
            self.assertNotIn(SECRET, status.text)
            self.assertEqual(status.json()['apiStatus']['vworld'], '준비')
            self.assertNotIn(SECRET, client.get('/').text)
            for path in ['/.env', '/server/env.py', '/server/settings.py']:
                response = client.get(path)
                self.assertEqual(response.status_code, 404)
                self.assertNotIn(SECRET, response.text)
            self.assertEqual(client.get('/api/status', headers={'origin': 'https://example.com'}).status_code, 403)


if __name__ == '__main__':
    unittest.main()
