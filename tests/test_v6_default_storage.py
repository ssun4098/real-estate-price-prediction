"""V6 samples keep a stable default and cannot overwrite the V5 deliverables."""
import json
from pathlib import Path
import re
import tempfile
import threading
from types import SimpleNamespace
import unittest
import urllib.error
import urllib.request
from unittest.mock import patch

from pf_engine import analyze
from pf_server import LocalServer, PortfolioStore, SnapshotStore, render_html
from test_engine import fixture


TEMPLATE = '<html><head><!--PF_SNAPSHOT--></head><body>V6</body></html>'


def embedded(html, name):
    match = re.search(r'window\.' + re.escape(name) + r'=(.*?);(?:window\.|</script>)', html)
    return json.loads(match.group(1))


class V6DefaultStorageTests(unittest.TestCase):
    def sample(self, store, name='현재 27필지 분석'):
        snapshot = analyze(fixture(), partial=True)
        return store.save({'name': name, 'snapshot': snapshot, 'displayState': {
            'address': '경기도 안산시 상록구 장상동',
            'survey': {'status': 'partial', 'rows': [{'type': 'school', 'lon': 126.8, 'lat': 37.3}]}}})

    def test_default_is_explicit_and_not_replaced_by_save_or_listing_order(self):
        with tempfile.TemporaryDirectory() as directory:
            store = PortfolioStore(directory)
            first = self.sample(store)
            self.assertIsNone(store.default_id())
            store.set_default(first['id'])
            second = self.sample(store, '추가 저장')
            self.assertEqual(store.default_id(), first['id'])
            self.assertEqual([row['id'] for row in store.list() if row['isDefault']], [first['id']])
            restarted = PortfolioStore(directory)
            self.assertEqual(restarted.default_id(), first['id'])
            delivered = render_html(TEMPLATE, snapshot=second['snapshot'], portfolio=restarted.entries(), default_sample_id=restarted.default_id())
            self.assertEqual(embedded(delivered, '__PF_DEFAULT_SAMPLE_ID__'), first['id'])
            self.assertEqual(embedded(delivered, '__PF_SNAPSHOT__'), first['snapshot'])
            self.assertEqual(len(embedded(delivered, '__PF_PORTFOLIO__')), 2)
            with self.assertRaises(ValueError):
                store.set_default('../V5.html')
            self.assertEqual(store.default_id(), first['id'])

    def test_v5_output_files_and_library_remain_untouched(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / 'V5.html').write_text('previous V5 page', encoding='utf-8')
            (root / 'V5.py').write_text('previous V5 server', encoding='utf-8')
            old_library = root / 'pf-study-v5-portfolio'
            old_library.mkdir()
            old_capture = old_library / ('pf-sample-' + 'b' * 32 + '.json')
            old_capture.write_text('{"saved":"V5"}', encoding='utf-8')
            old_input = root / 'pf-study-v5-pf-prior.json'
            old_input.write_text('{"saved":"V5 input"}', encoding='utf-8')
            originals = {p: p.read_bytes() for p in (root / 'V5.html', root / 'V5.py', old_capture, old_input)}
            store = SnapshotStore(directory, TEMPLATE)
            store.initialize()
            sample = self.sample(store.portfolio)
            store.portfolio.set_default(sample['id'])
            result = store.save(sample['snapshot'])
            self.assertEqual(result['htmlFileName'], 'V6.html')
            self.assertTrue(result['fileName'].startswith('pf-study-v6-pf-'))
            self.assertEqual(len(store.list()), 1)
            self.assertEqual(len(store.portfolio.list()), 1)
            self.assertEqual(embedded((root / 'V6.html').read_text(encoding='utf-8'), '__PF_DEFAULT_SAMPLE_ID__'), sample['id'])
            for path, content in originals.items():
                self.assertEqual(path.read_bytes(), content)

    def test_bundled_v1_capture_is_available_without_external_files(self):
        with tempfile.TemporaryDirectory() as origin, tempfile.TemporaryDirectory() as copy:
            item = self.sample(PortfolioStore(origin))
            with patch('pf_server.validate_snapshot', side_effect=AssertionError('frozen capture recalculated')):
                store = SnapshotStore(copy, TEMPLATE, bundled_portfolio=[item], bundled_default_id=item['id'])
                store.initialize()
                restored = store.portfolio.read(item['id'])
            self.assertEqual(restored['snapshot'], item['snapshot'])
            self.assertEqual(restored['displayState'], item['displayState'])
            self.assertEqual(store.portfolio.default_id(), item['id'])
            self.assertFalse((Path(copy) / 'pf-study-v6-portfolio').exists())
            another = self.sample(store.portfolio, '실제 사용자가 저장한 분석')
            self.assertEqual(store.portfolio.default_id(), item['id'])
            store.portfolio.set_default(another['id'])
            restarted = PortfolioStore(copy, bundled_entries=[item], bundled_default_id=item['id'])
            self.assertEqual(restarted.default_id(), another['id'])
            self.assertEqual(len(restarted.list()), 2)

    def test_missing_default_does_not_silently_choose_a_new_sample(self):
        with tempfile.TemporaryDirectory() as directory:
            store = PortfolioStore(directory)
            item = self.sample(store)
            store.set_default(item['id'])
            store.path(item['id']).unlink()
            self.sample(store, '다른 분석')
            self.assertIsNone(store.default_id())

    def test_view_and_map_roundtrip_with_validation_and_explicit_fields(self):
        with tempfile.TemporaryDirectory() as directory:
            store = PortfolioStore(directory)
            body = {'snapshot': analyze(fixture(), partial=True), 'displayState': {
                'viewState': {'main': 'finance', 'tab': 'parcels', 'unknown': 'drop'},
                'mapView': {'lon': 126.87536, 'lat': 37.35761, 'z': 18, 'unknown': 'drop'}}}
            saved = store.save(body)
            restored = store.read(saved['id'])['displayState']
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
                {'mapView': {'lon': 126.8, 'lat': 37.3, 'z': float('nan')}},
            ]
            for display in invalid:
                with self.subTest(display=display), self.assertRaises(ValueError):
                    store.save({**body, 'displayState': display})
            self.assertEqual(len(store.list()), 1)

    def test_default_api_updates_saved_html_and_startup_response(self):
        with tempfile.TemporaryDirectory() as directory:
            store = SnapshotStore(directory, TEMPLATE)
            store.initialize()
            server = LocalServer(0, SimpleNamespace(keys={}), store)
            thread = threading.Thread(target=server.serve_forever, daemon=True)
            thread.start()
            base = f'http://127.0.0.1:{server.server_port}'
            item = self.sample(server.portfolio)
            try:
                request = urllib.request.Request(base + '/api/portfolio-default', data=json.dumps({'id': item['id']}).encode(), headers={'Content-Type': 'application/json'})
                with urllib.request.urlopen(request) as response:
                    self.assertEqual(json.load(response), {'id': item['id']})
                with urllib.request.urlopen(base + '/api/portfolio-samples') as response:
                    listing = json.load(response)
                    self.assertEqual(listing['defaultId'], item['id'])
                    self.assertTrue(listing['items'][0]['isDefault'])
                with urllib.request.urlopen(base + '/') as response:
                    self.assertEqual(embedded(response.read().decode('utf-8'), '__PF_SNAPSHOT__'), item['snapshot'])
                saved_html = (Path(directory) / 'V6.html').read_text(encoding='utf-8')
                self.assertEqual(embedded(saved_html, '__PF_DEFAULT_SAMPLE_ID__'), item['id'])
                with urllib.request.urlopen(base + '/api/portfolio-default') as response:
                    self.assertEqual(json.load(response)['id'], item['id'])
            finally:
                server.shutdown()
                server.server_close()
                thread.join(timeout=2)


if __name__ == '__main__':
    unittest.main()
