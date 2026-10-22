import json
from pathlib import Path
import tempfile
import threading
import unittest
import urllib.error
import urllib.request

from pf_api import Collector
from pf_config import ConfigurationError, load_environment, read_keys
from pf_server import LocalServer, SnapshotStore


class EnvironmentTests(unittest.TestCase):
    def load(self, text, env=None):
        env = {} if env is None else env
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / '.env'
            path.write_text(text, encoding='utf-8-sig')
            load_environment(path, env)
        return env

    def test_process_env_wins_including_empty_value(self):
        env = self.load('VWORLD_API_KEY=file-value\nJUSO_API_KEY=file-value',
                        {'VWORLD_API_KEY': 'process-value', 'JUSO_API_KEY': ''})
        self.assertEqual(env['VWORLD_API_KEY'], 'process-value')
        self.assertEqual(env['JUSO_API_KEY'], '')

    def test_portal_key_decoded_once_without_converting_plus_to_space(self):
        encoded = read_keys({'DATA_GO_KR_API_KEY': 'TEST%2BKEY%2F%3D'})
        raw = read_keys({'DATA_GO_KR_API_KEY': 'TEST+KEY/='})
        self.assertEqual(encoded['dataGoKr'], raw['dataGoKr'])
        self.assertEqual(raw['dataGoKr'], 'TEST+KEY/=')

    def test_vworld_shared_key_and_optional_overrides(self):
        keys = read_keys({'VWORLD_API_KEY': 'BASE_TEST', 'VWORLD_SEARCH_API_KEY': 'SEARCH_TEST'})
        self.assertEqual(keys['vworldGeocoder'], 'BASE_TEST')
        self.assertEqual(keys['vworldSearch'], 'SEARCH_TEST')
        self.assertFalse(read_keys({})['vworld'])

    def test_bom_quotes_comments_and_no_shell_evaluation(self):
        env = self.load('# comment\n\nJUSO_API_KEY="literal$(command)#abc=="\n')
        self.assertEqual(env['JUSO_API_KEY'], 'literal$(command)#abc==')

    def test_malformed_configuration_is_atomic_and_never_prints_values(self):
        for content in ['VWORLD_API_KEY=DO_NOT_PRINT\nINVALID=DO_NOT_PRINT',
                        'JUSO_API_KEY="DO_NOT_PRINT',
                        'JUSO_API_KEY=first\nJUSO_API_KEY=DO_NOT_PRINT',
                        'DATA_GO_KR_API_KEY=DO_NOT_PRINT\x00']:
            env = {}
            with self.assertRaises(ConfigurationError) as error:
                self.load(content, env)
            self.assertNotIn('DO_NOT_PRINT', str(error.exception))
            self.assertEqual(env, {})
        with self.assertRaises(ConfigurationError) as error:
            read_keys({'DATA_GO_KR_API_KEY': 'DO_NOT_PRINT%0A'})
        self.assertNotIn('DO_NOT_PRINT', str(error.exception))

    def test_http_never_exposes_keys_or_serves_env_file(self):
        # Dummy values only; no external API call is performed by this test.
        secret = 'TEST_SECRET_NEVER_PUBLISH_847295'
        keys = read_keys({'VWORLD_API_KEY': secret, 'JUSO_API_KEY': secret,
                          'DATA_GO_KR_API_KEY': secret})
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder)
            (path / '.env').write_text('VWORLD_API_KEY=' + secret, encoding='utf-8')
            store = SnapshotStore(path, '<html><head></head><body>Demo</body></html>', keys.values())
            store.initialize()
            server = LocalServer(0, Collector(keys), store)
            thread = threading.Thread(target=server.serve_forever, daemon=True)
            thread.start()
            base = f'http://127.0.0.1:{server.server_port}'
            try:
                with urllib.request.urlopen(base + '/api/status') as response:
                    data = response.read().decode()
                self.assertNotIn(secret, data)
                self.assertEqual(json.loads(data)['apiStatus']['vworld'], '준비')
                with urllib.request.urlopen(base + '/') as response:
                    self.assertNotIn(secret, response.read().decode())
                for request_path in ['/.env', '/backend/pf_config.py', '/../.env']:
                    with self.assertRaises(urllib.error.HTTPError) as error:
                        urllib.request.urlopen(base + request_path)
                    self.assertEqual(error.exception.code, 404)
                    self.assertNotIn(secret, error.exception.read().decode())
                req = urllib.request.Request(base + '/api/status', headers={'Origin': 'https://example.com'})
                with self.assertRaises(urllib.error.HTTPError) as error:
                    urllib.request.urlopen(req)
                self.assertEqual(error.exception.code, 403)
            finally:
                server.shutdown()
                server.server_close()
                thread.join(timeout=5)


if __name__ == '__main__':
    unittest.main()
