from pathlib import Path
import sys
import tempfile
import tomllib
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[3]))
from integrations.codex_mcp.configure import configure

TEST_TMP = Path(__file__).resolve().parents[3] / "tmp/mcp-unit-tests"
TEST_TMP.mkdir(parents=True, exist_ok=True)


class ConfigureTests(unittest.TestCase):
    def test_only_school_manager_timeouts_change_and_second_run_is_identical(self):
        original = '''model = "example"
[mcp_servers.other]
command = "other"
tool_timeout_sec = 15
[mcp_servers.school_manager]
command = 'D:\\MCP\\python.exe'
args = ['D:\\MCP\\server.py']
startup_timeout_sec = 5
tool_timeout_sec = 60
[mcp_servers.school_manager.env]
PYTHONUTF8 = "1"
[projects.'D:\\school']
trust_level = "trusted"
'''
        with tempfile.TemporaryDirectory(dir=TEST_TMP) as folder:
            path = Path(folder) / "config.toml"
            path.write_text(original, encoding="utf-8-sig")
            before = tomllib.loads(original)
            configure(path)
            content = path.read_bytes()
            after = tomllib.loads(content.decode("utf-8"))
            school = after["mcp_servers"]["school_manager"]
            self.assertEqual((school.pop("startup_timeout_sec"), school.pop("tool_timeout_sec")), (20, 360))
            before["mcp_servers"]["school_manager"].pop("startup_timeout_sec")
            before["mcp_servers"]["school_manager"].pop("tool_timeout_sec")
            self.assertEqual(after, before)
            configure(path)
            self.assertEqual(path.read_bytes(), content)

    def test_missing_registration_never_changes_config(self):
        with tempfile.TemporaryDirectory(dir=TEST_TMP) as folder:
            path = Path(folder) / "config.toml"
            path.write_text('model = "example"\n', encoding="utf-8")
            before = path.read_bytes()
            with self.assertRaises(RuntimeError):
                configure(path)
            self.assertEqual(path.read_bytes(), before)

    def test_empty_final_section_without_newline_is_valid(self):
        with tempfile.TemporaryDirectory(dir=TEST_TMP) as folder:
            path = Path(folder) / "config.toml"
            path.write_text("[mcp_servers.school_manager]", encoding="utf-8")
            configure(path)
            result = tomllib.loads(path.read_text(encoding="utf-8"))
            self.assertEqual(result["mcp_servers"]["school_manager"]["tool_timeout_sec"], 360)


if __name__ == "__main__":
    unittest.main()
