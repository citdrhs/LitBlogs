"""Actual Compose interpolation of the public build/runtime prefix contract."""
import os
import shutil
import unittest
from unittest.mock import patch

from test_compose import ROOT, compose_config


@unittest.skipUnless(shutil.which('docker'), 'Docker Compose is required')
class PublicBuildContractTests(unittest.TestCase):
    def test_build_and_runtime_share_the_selected_public_prefix(self):
        for prefix in ('', '/dren'):
            with self.subTest(prefix=prefix), patch.dict(os.environ, {'LITBLOGS_BASE_PATH': prefix}):
                config = compose_config(ROOT / 'docker-compose.yml')
                for name in ('app', 'email', 'reconcile'):
                    service = config['services'][name]
                    self.assertEqual(service['environment'].get('LITBLOGS_BASE_PATH'), prefix)
                    self.assertEqual(service['build'].get('args', {}).get('VITE_APP_BASE_PATH'), prefix or '/')
                self.assertNotIn('LITBLOGS_BASE_PATH', config['services']['postgres']['environment'])


if __name__ == '__main__':
    unittest.main()
