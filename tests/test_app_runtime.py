import os
import sys
import tempfile
import unittest
from pathlib import Path
from types import ModuleType
from unittest.mock import patch

from app_runtime import load_backend


class BackendRevisionTests(unittest.TestCase):
    def setUp(self):
        self.directory = tempfile.TemporaryDirectory()
        self.addCleanup(self.directory.cleanup)
        self.root = Path(self.directory.name)
        for filename, source in {
            "__init__.py": '"""Synthetic backend."""\n',
            "profiles.py": "STATUS = 'old'\ndef status():\n    return STATUS\n",
            "data_quality.py": "from .profiles import status\n",
            "snapshot.py": "from .profiles import status\n",
        }.items():
            (self.root / filename).write_text(source, encoding="utf-8")

    def test_unchanged_sources_reuse_one_backend(self):
        first = load_backend(self.root)
        self.assertIs(load_backend(self.root), first)
        self.assertIs(first.data_quality.status, first.profiles.status)
        self.assertIs(first.snapshot.status, first.profiles.status)

    def test_source_change_invalidates_even_with_equal_size_and_timestamp(self):
        first = load_backend(self.root)
        path = self.root / "profiles.py"
        stat = path.stat()
        path.write_text(path.read_text().replace("'old'", "'new'"), encoding="utf-8")
        os.utime(path, ns=(stat.st_atime_ns, stat.st_mtime_ns))
        second = load_backend(self.root)
        self.assertNotEqual(first.revision, second.revision)
        self.assertEqual(second.profiles.status(), "new")
        self.assertEqual(second.data_quality.status(), "new")
        self.assertEqual(second.snapshot.status(), "new")
        self.assertEqual(first.profiles.status(), "old")
        self.assertEqual(first.snapshot.status(), "old")
        self.assertIn("STATUS = 'old'", first.profiles.__loader__.get_source(first.profiles.__name__))

    def test_cached_public_pipeline_modules_are_not_reused_or_modified(self):
        stale = ModuleType("pipeline.profiles")
        stale.STATUS = "stale deployed helper"
        with patch.dict(sys.modules, {"pipeline.profiles": stale}):
            backend = load_backend(self.root)
            self.assertIs(sys.modules["pipeline.profiles"], stale)
            self.assertEqual(backend.profiles.status(), "old")
            self.assertNotEqual(backend.profiles.__name__, "pipeline.profiles")
            self.assertEqual(backend.profiles.__package__, backend.snapshot.__package__)

    def test_new_source_failure_is_not_hidden_by_an_old_backend(self):
        first = load_backend(self.root)
        (self.root / "snapshot.py").write_text("raise ValueError('invalid new source')\n", encoding="utf-8")
        with self.assertRaisesRegex(ValueError, "invalid new source"):
            load_backend(self.root)
        self.assertEqual(first.snapshot.status(), "old")
        (self.root / "snapshot.py").write_text("from .profiles import status\nREPAIRED = True\n", encoding="utf-8")
        self.assertTrue(load_backend(self.root).snapshot.REPAIRED)

    def test_missing_package_is_an_explicit_error(self):
        (self.root / "__init__.py").unlink()
        with self.assertRaisesRegex(FileNotFoundError, "Backend package is missing"):
            load_backend(self.root)


if __name__ == "__main__":
    unittest.main()
