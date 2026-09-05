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
import sys
from pathlib import Path

root = Path(sys.argv[1])
sys.path.insert(0, str(root))
from app_runtime import load_backend
backend = load_backend()
assert Path(backend.profiles.__file__).resolve() == root / "pipeline" / "profiles.py"
assert callable(backend.profiles.contribution_evidence)
assert callable(backend.data_quality.validate_snapshot)
assert callable(backend.snapshot.project_snapshot)
assert backend.data_quality.research_context is backend.profiles.research_context
assert backend.snapshot.research_context is backend.profiles.research_context
"""
        with tempfile.TemporaryDirectory() as directory:
            result = subprocess.run(
                [sys.executable, "-I", "-c", script, str(ROOT)],
                cwd=directory, capture_output=True, text=True,
            )
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)


if __name__ == "__main__":
    unittest.main()
