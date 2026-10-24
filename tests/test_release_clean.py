from pathlib import Path
import sys
import tempfile
import unittest
from zipfile import ZipFile

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from scripts.check_release_clean import scan_targets


class ReleaseCleanTests(unittest.TestCase):
    def test_rejects_environments_and_runtime_directories(self):
        for folder in ('.venv', 'venv', 'backups', 'output', 'tmp'):
            with self.subTest(folder=folder), tempfile.TemporaryDirectory() as temp:
                root = Path(temp)
                target = root / 'SchoolManager' / folder
                target.mkdir(parents=True)
                (target / 'data.txt').write_text('local data', encoding='utf-8')
                self.assertTrue(scan_targets([root / 'SchoolManager']))

    def test_rejects_environment_inside_portable_zip(self):
        with tempfile.TemporaryDirectory() as temp:
            archive = Path(temp) / 'portable.zip'
            with ZipFile(archive, 'w') as zip_file:
                zip_file.writestr('SchoolManager/integrations/codex_mcp/.venv/pyvenv.cfg', 'home=Python')
            self.assertTrue(scan_targets([archive]))

    def test_standalone_mcp_sources_are_allowed(self):
        with tempfile.TemporaryDirectory() as temp:
            archive = Path(temp) / 'mcp.zip'
            with ZipFile(archive, 'w') as zip_file:
                zip_file.writestr('SchoolManager-Codex-MCP/integrations/codex_mcp/server.py', '# source only\n')
            self.assertEqual(scan_targets([archive]), [])
