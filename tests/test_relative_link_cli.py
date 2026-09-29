"""Dispatch actual manifest patterns, then exercise the real plugin CLI.

Only Herdr process-info and desktop launching are replaced at their boundaries.
The caller's cwd deliberately differs from the pane's cwd.
"""
import json
import os
from pathlib import Path
import re
import subprocess
import sys
import tempfile
import unittest
from urllib.parse import quote

ROOT = Path(__file__).resolve().parents[1]
REPORTED_PATHS = (
    "workspaces/alice/temp/customs-warning-implementation/runtime-followup-report.md",
    "workspaces/main/temp/navigation-b/design-reference/merchant/01-a-bilduebersicht-desktop.png",
    "workspaces/main/temp/navigation-b/design-reference/merchant/02-b-fokus-navigation-desktop.png",
    "workspaces/main/temp/navigation-b/design-reference/merchant/03-c-verzeichnis-desktop.png",
)


def manifest_patterns(manifest):
    # Keep the suite Python 3.10-compatible, without a TOML dependency.
    # Manifests use one-line basic strings or literal strings for regexes.
    patterns = []
    for match in re.finditer(r'''(?m)^pattern = (["'])(.*?)\1$''', manifest.read_text()):
        value = json.loads(match.group(0).split(" = ", 1)[1]) if match[1] == '"' else match[2]
        patterns.append(re.compile(value))
    return patterns


class RelativeLinkManifestTests(unittest.TestCase):
    def test_both_manifests_route_reported_and_common_relative_links(self):
        for manifest in (ROOT / "herdr-plugin.toml", ROOT / "windows/herdr-plugin.toml"):
            for url in (*REPORTED_PATHS, "./report.md", "../images/chart.png", "README.md",
                        "docs/My%20Report.md#summary", "Pr%C3%BCfung.pdf", "docs/file.txt:12:4"):
                with self.subTest(manifest=manifest, url=url):
                    self.assertTrue(any(p.fullmatch(url) for p in manifest_patterns(manifest)), url)

    def test_web_other_schemes_network_and_anchor_only_links_are_not_intercepted(self):
        for manifest in (ROOT / "herdr-plugin.toml", ROOT / "windows/herdr-plugin.toml"):
            for url in ("https://example.org/report.md", "http://localhost:3000/a.png",
                        "mailto:someone@example.org", "vscode://file/tmp/report.md",
                        "javascript:alert(1)", "data:text/plain,a.png", "ssh://host/file.md",
                        "custom.scheme:123", "README.md:12",
                        "//server/share/report.md", r"\\server\share\report.md",
                        "#summary", "?page=report.md", "docs/file\n.md"):
                with self.subTest(manifest=manifest, url=url):
                    self.assertFalse(any(p.fullmatch(url) for p in manifest_patterns(manifest)), url)


@unittest.skipUnless(sys.platform.startswith("linux"), "native Linux CLI boundary")
class RelativeLinkCliTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix="herdr-relative-links-")
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.pane = self.root / "pane"
        self.pane.mkdir()
        self.workspace = self.root / "workspace"
        self.workspace.mkdir()
        self.herdr = self.root / "herdr"
        self.herdr.write_text(
            "#!" + sys.executable + "\n"
            "import json, os, sys\n"
            "assert sys.argv[1:] == ['pane', 'process-info', '--pane', 'test:pane']\n"
            "mode = os.environ.get('TEST_LOCALITY', 'local')\n"
            "if mode == 'unknown': sys.exit(1)\n"
            "argv = ['ssh', 'host'] if mode == 'remote' else ['pi']\n"
            "print(json.dumps({'result': {'process_info': {'foreground_processes': "
            "[{'name': argv[0], 'argv': argv}]}}}))\n"
        )
        self.herdr.chmod(0o700)

    def document(self, relative, base=None):
        target = (base or self.pane) / relative
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text("fixture only\n")
        target.chmod(0o600)
        return target

    def open_link(self, url, *, locality="local", pane_cwd=True, workspace_cwd=True, dispatch=True):
        if dispatch:
            self.assertTrue(any(p.fullmatch(url) for p in manifest_patterns(ROOT / "herdr-plugin.toml")),
                            "No registered manifest handler for " + url)
        env = {key: value for key, value in os.environ.items()
               if not key.startswith(("HERDR_", "LOCAL_PATH_ACTIONS_", "WSL_"))}
        context = {"invocation_source": "link_click", "focused_pane_id": "test:pane"}
        if pane_cwd:
            context["focused_pane_cwd"] = str(self.pane)
        if workspace_cwd:
            context["workspace_cwd"] = str(self.workspace)
        env.update({
            "HERDR_PLUGIN_CLICKED_URL": url,
            "HERDR_PLUGIN_CONTEXT_JSON": json.dumps(context),
            "HERDR_BIN_PATH": str(self.herdr),
            "LOCAL_PATH_ACTIONS_DRY_RUN": "1",
            "TEST_LOCALITY": locality,
        })
        return subprocess.run([sys.executable, str(ROOT / "src/local_path_actions.py"), "open"],
                              cwd=ROOT, env=env, capture_output=True, text=True, timeout=10)

    def assert_opened(self, result, target):
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertEqual(json.loads(result.stdout), {"command": ["xdg-open", str(target)]})

    def test_all_four_reported_links_use_pane_not_plugin_or_workspace_cwd(self):
        for relative in REPORTED_PATHS:
            with self.subTest(relative=relative):
                target = self.document(relative)
                self.document(relative, self.workspace)
                self.assert_opened(self.open_link(relative), target)

    def test_dot_parent_and_bare_filename_links(self):
        target = self.document("report.md")
        for url in ("./report.md", "../pane/report.md", "report.md"):
            with self.subTest(url=url):
                self.assert_opened(self.open_link(url), target)

    def test_workspace_is_fallback_only_when_pane_cwd_is_missing(self):
        target = self.document("report.md", self.workspace)
        self.assert_opened(self.open_link("report.md", pane_cwd=False), target)

    def test_does_not_guess_another_base_when_pane_file_is_missing(self):
        self.document("report.md", self.workspace)
        result = self.open_link("report.md")
        self.assertEqual(result.returncode, 2, result.stdout + result.stderr)
        self.assertIn("does not exist", result.stderr)
        self.assertEqual(result.stdout, "")

    def test_missing_cwd_unknown_locality_and_remote_panes_refuse_relative_links(self):
        self.document("docs/report.md")
        for options in ({"pane_cwd": False, "workspace_cwd": False},
                        {"locality": "unknown"}, {"locality": "remote"}):
            with self.subTest(options=options):
                result = self.open_link("docs/report.md", **options)
                self.assertEqual(result.returncode, 2, result.stdout + result.stderr)
                self.assertEqual(result.stdout, "")

    def test_clicked_url_decodes_once_and_ignores_query_and_fragment(self):
        for name in ("Prüfung mit Leerzeichen.md", "hash#query?.md", "100%20literal.md",
                     "semi;.md", "report.md;", "[report].md", "x;$(touch OWNED).md"):
            with self.subTest(name=name):
                target = self.document("docs/" + name)
                url = "docs/" + quote(name) + "?download=1#summary"
                self.assert_opened(self.open_link(url), target)
        self.assertFalse((ROOT / "OWNED").exists())

    def test_encoded_bare_filenames_do_not_use_terminal_text_heuristics(self):
        for name in ("Prüfung.pdf", "[report].md", "100%20literal.md", "hash#query?.md"):
            with self.subTest(name=name):
                target = self.document(name)
                self.assert_opened(self.open_link(quote(name)), target)

    def test_decoded_controls_and_absolute_network_or_scheme_paths_are_refused(self):
        for url in ("docs/a%00.md", "docs/a%0a.md", "docs/a%1b.md", "docs/a%7f.md",
                    "%2Fetc/passwd", "%2F%2Fserver/share/report.md", "%5C%5Cserver/share/report.md",
                    "https%3A/example.org/report.md", "%43%3A/report.md"):
            with self.subTest(url=url):
                result = self.open_link(url, dispatch=False)
                self.assertEqual(result.returncode, 2, result.stdout + result.stderr)
                self.assertEqual(result.stdout, "")

    def test_risky_files_executables_and_symlink_targets_remain_blocked(self):
        risky = self.document("docs/launcher.desktop")
        executable = self.document("docs/tool")
        executable.chmod(0o700)
        (self.pane / "docs/report.md").symlink_to(risky)
        for url in ("docs/launcher.desktop", "docs/launcher%2Edesktop", "docs/tool", "docs/report.md"):
            with self.subTest(url=url):
                result = self.open_link(url)
                self.assertEqual(result.returncode, 2, result.stdout + result.stderr)
                self.assertEqual(result.stdout, "")


if __name__ == "__main__":
    unittest.main()
