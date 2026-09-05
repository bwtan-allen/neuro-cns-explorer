"""Exercise the entrypoint's backend imports in a fresh deployment process."""
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


class StartupTests(unittest.TestCase):
    def test_entrypoint_imports_without_an_existing_module_cache(self):
        script = """
import ast
import sys
from pathlib import Path

root = Path(sys.argv[1])
sys.path.insert(0, str(root))
tree = ast.parse((root / "streamlit_app.py").read_text(encoding="utf-8"))
imports = [
    node for node in tree.body
    if isinstance(node, ast.ImportFrom) and (node.module or "").startswith("pipeline.")
]
assert imports, "No application backend imports were found."
exec(compile(ast.Module(body=imports, type_ignores=[]), "streamlit_app.py", "exec"))
import pipeline.profiles
assert Path(pipeline.profiles.__file__).resolve() == root / "pipeline" / "profiles.py"
"""
        with tempfile.TemporaryDirectory() as directory:
            result = subprocess.run(
                [sys.executable, "-I", "-c", script, str(ROOT)],
                cwd=directory, capture_output=True, text=True,
            )
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)


if __name__ == "__main__":
    unittest.main()
