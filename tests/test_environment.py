from pathlib import Path
import tempfile
import unittest

from server.env import ConfigurationError, load_environment, read_keys


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


if __name__ == '__main__':
    unittest.main()
