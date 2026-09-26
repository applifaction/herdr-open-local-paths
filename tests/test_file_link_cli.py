"""Black-box checks of the same CLI entrypoint used by Herdr file-link clicks.

The desktop-opener boundary is replaced by the plugin's existing DRY_RUN mode.
No desktop application, shell command from a filename, or Herdr pane is launched.
"""
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]


@unittest.skipUnless(sys.platform.startswith("linux"), "native Linux desktop integration")
class FileLinkCliTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix="herdr-file-link-test-")
        self.addCleanup(self.temp.cleanup)
        self.directory = Path(self.temp.name)

    def open_url(self, url):
        env = {
            key: value for key, value in os.environ.items()
            if not key.startswith(("HERDR_", "LOCAL_PATH_ACTIONS_", "WSL_"))
        }
        env.update({
            "HERDR_PLUGIN_CLICKED_URL": url,
            "HERDR_PLUGIN_CONTEXT_JSON": json.dumps({"invocation_source": "link_click"}),
            "LOCAL_PATH_ACTIONS_DRY_RUN": "1",
        })
        return subprocess.run(
            [sys.executable, str(ROOT / "src/local_path_actions.py"), "open"],
            cwd=ROOT, env=env, capture_output=True, text=True, timeout=10,
        )

    def test_file_url_cannot_open_extensionless_executable(self):
        target = self.directory / "executable"
        target.write_text("not executed\n")
        target.chmod(0o700)
        result = self.open_url(target.as_uri())
        self.assertEqual(result.returncode, 2, result.stdout + result.stderr)
        self.assertIn("Executable files", result.stderr)
        self.assertEqual(result.stdout, "")

    def test_document_named_symlink_cannot_bypass_risky_target_extension(self):
        target = self.directory / "launcher.desktop"
        target.write_text("not executed\n")
        target.chmod(0o600)
        link = self.directory / "report.csv"
        link.symlink_to(target)
        result = self.open_url(link.as_uri())
        self.assertEqual(result.returncode, 2, result.stdout + result.stderr)
        self.assertIn(".desktop", result.stderr)
        self.assertEqual(result.stdout, "")

    def test_documents_reach_opener_as_one_exact_argument(self):
        for filename in ("report.csv", "Prüfung mit Leerzeichen.pdf", "Zubehör.xlsx", "x;$(touch OWNED).csv"):
            with self.subTest(filename=filename):
                target = self.directory / filename
                target.write_text("test document\n")
                target.chmod(0o600)
                result = self.open_url(target.as_uri())
                self.assertEqual(result.returncode, 0, result.stderr)
                self.assertEqual(json.loads(result.stdout), {"command": ["xdg-open", str(target)]})
        self.assertFalse((ROOT / "OWNED").exists())

    def test_localhost_file_uri_is_supported(self):
        target = self.directory / "report.csv"
        target.write_text("test document\n")
        result = self.open_url(target.as_uri().replace("file:///", "file://localhost/", 1))
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(json.loads(result.stdout)["command"], ["xdg-open", str(target)])

    def test_missing_file_and_remote_authorities_are_not_opened(self):
        target = self.directory / "report.csv"
        target.write_text("test document\n")
        for url in (
            (self.directory / "missing.csv").as_uri(),
            "file://remote.invalid" + str(target),
            "file://user@localhost" + str(target),
            "https://example.org/report.csv",
            "file:///tmp/invalid%00.csv",
        ):
            with self.subTest(url=url):
                result = self.open_url(url)
                self.assertEqual(result.returncode, 2, result.stdout + result.stderr)
                self.assertEqual(result.stdout, "")

    def test_risky_extensions_are_not_opened_even_without_executable_bit(self):
        for suffix in (".sh", ".desktop", ".EXE", ".AppImage", ".js"):
            with self.subTest(suffix=suffix):
                target = self.directory / ("danger" + suffix)
                target.write_text("not executed\n")
                target.chmod(0o600)
                result = self.open_url(target.as_uri())
                self.assertEqual(result.returncode, 2, result.stdout + result.stderr)
                self.assertEqual(result.stdout, "")

    def test_symlink_to_executable_is_not_opened(self):
        target = self.directory / "executable"
        target.write_text("not executed\n")
        target.chmod(0o700)
        link = self.directory / "report.txt"
        link.symlink_to(target)
        result = self.open_url(link.as_uri())
        self.assertEqual(result.returncode, 2, result.stdout + result.stderr)
        self.assertIn("Executable files", result.stderr)

    def test_symlink_to_regular_document_is_supported(self):
        target = self.directory / "report.pdf"
        target.write_text("test document\n")
        target.chmod(0o600)
        link = self.directory / "document.pdf"
        link.symlink_to(target)
        result = self.open_url(link.as_uri())
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(json.loads(result.stdout)["command"], ["xdg-open", str(link)])


if __name__ == "__main__":
    unittest.main()
