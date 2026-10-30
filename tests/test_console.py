"""새 분석 콘솔(/console) 경로 테스트. 기존 화면(/)과 별개이며 기존 API는 그대로 쓴다.

SQLite 로 앱을 띄워 화면 파일 제공, 허용되지 않는 파일 차단, 예측 차트용 API 두 개를 확인한다.
"""
import os
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

try:
    from fastapi.testclient import TestClient
    from server.settings import Settings
    from server.main import create_app
    HAVE_APP = True
except ImportError:
    HAVE_APP = False

INPUTS = Path(__file__).resolve().parents[1] / "data" / "models" / "inputs"


@unittest.skipUnless(HAVE_APP, 'fastapi/sqlalchemy not installed')
class ConsoleRouteTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.directory = tempfile.TemporaryDirectory()
        cls.env = {'DATABASE_URL': 'sqlite:///' + os.path.join(cls.directory.name, 't.db').replace('\\', '/'),
                   'MYSQL_PASSWORD': 'db-secret-pw', 'DAILY_LOAD': 'off'}
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

    def test_page_and_built_files_are_served(self):
        page = self.client.get('/console')
        self.assertEqual(page.status_code, 200)
        self.assertIn('사업성 분석 콘솔', page.text)
        self.assertIn('/console/build/console.js', page.text)
        js = self.client.get('/console/build/console.js')
        self.assertEqual(js.status_code, 200)
        self.assertIn('javascript', js.headers['content-type'])
        self.assertEqual(self.client.get('/console/build/console.css').status_code, 200)

    def test_existing_dashboard_is_unchanged(self):
        self.assertEqual(self.client.get('/').status_code, 200)

    def test_only_listed_folders_and_file_types(self):
        for path in ('/console/src/main.js', '/console/build.mjs', '/console/build/../src/main.js',
                     '/console/build/%2e%2e/build.mjs', '/console/dist/console.js', '/console/vendor/leaflet/LICENSE.txt', '/console/build/nothing.js'):
            with self.subTest(path=path):
                self.assertEqual(self.client.get(path).status_code, 404)

    @unittest.skipUnless((INPUTS / 'group_history.csv.gz').is_file(), 'model inputs not present')
    def test_land_history_returns_monthly_points(self):
        response = self.client.get('/api/console/land-history', params={'keys': '41271|전|녹지지역,41271|대|일반주거지역', 'start': '2024-01'})
        self.assertEqual(response.status_code, 200)
        series = response.json()['series']
        self.assertEqual([s['key'] for s in series], ['41271|전|녹지지역', '41271|대|일반주거지역'])
        points = series[0]['points']
        self.assertTrue(points)
        self.assertTrue(all(p[0] >= '2024-01' for p in points))
        self.assertEqual(points, sorted(points))
        month, unit, count = points[0]
        self.assertGreater(unit, 0)
        self.assertGreaterEqual(count, 1)

    def test_land_history_rejects_bad_keys(self):
        for keys in ('', 'bad', '4127|전|녹지지역', ','.join(f'41271|전|그룹{i}' for i in range(13))):
            with self.subTest(keys=keys):
                self.assertEqual(self.client.get('/api/console/land-history', params={'keys': keys}).status_code, 400)

    @unittest.skipUnless((INPUTS / 'macro_region_month.csv').is_file(), 'model inputs not present')
    def test_region_indicators(self):
        data = self.client.get('/api/console/region-indicators', params={'sgg': '41271'}).json()
        self.assertEqual(data['regionKey'], '경기|안산시|상록구')
        self.assertTrue(data['landChange'] and data['cofix'])
        self.assertEqual(self.client.get('/api/console/region-indicators', params={'sgg': '4127'}).status_code, 400)


if __name__ == '__main__':
    unittest.main()
