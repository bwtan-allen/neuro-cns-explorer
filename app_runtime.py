"""Load one coherent backend revision in a long-lived Streamlit process."""
import hashlib
import importlib
import importlib.abc
import importlib.util
import sys
import threading
from dataclasses import dataclass
from pathlib import Path
from types import ModuleType


@dataclass(frozen=True)
class Backend:
    revision: str
    data_quality: ModuleType
    profiles: ModuleType
    snapshot: ModuleType


class _BackendSources(importlib.abc.MetaPathFinder, importlib.abc.Loader):
    def __init__(self):
        self.revisions = {}

    def _locate(self, fullname):
        namespace, _, relative = fullname.partition(".")
        revision = self.revisions.get(namespace)
        if revision is None:
            return None
        root, sources = revision
        stem = relative.replace(".", "/")
        package = f"{stem}/__init__.py" if stem else "__init__.py"
        filename = package if package in sources else f"{stem}.py"
        if filename not in sources:
            raise ModuleNotFoundError(f"{fullname} is not part of this backend revision.")
        return root / filename, sources[filename], filename == package

    def find_spec(self, fullname, path=None, target=None):
        found = self._locate(fullname)
        if found is None:
            return None
        filename, _, is_package = found
        spec = importlib.util.spec_from_loader(fullname, self, is_package=is_package)
        spec.origin = str(filename)
        spec.has_location = True
        return spec

    def create_module(self, spec):
        return None

    def get_source(self, fullname):
        _, source, _ = self._locate(fullname)
        return importlib.util.decode_source(source)

    def exec_module(self, module):
        filename, source, is_package = self._locate(module.__name__)
        module.__file__ = str(filename)
        if is_package:
            module.__path__ = [str(filename.parent)]
        # Compile captured source, not timestamp-based .pyc files from a prior deployment.
        exec(compile(source, str(filename), "exec"), module.__dict__)


_sources = _BackendSources()
_backends = {}
_lock = threading.RLock()


def load_backend(package_dir=None):
    root = Path(package_dir) if package_dir is not None else Path(__file__).resolve().parent / "pipeline"
    root = root.resolve()
    sources = {path.relative_to(root).as_posix(): path.read_bytes() for path in sorted(root.rglob("*.py"))}
    if "__init__.py" not in sources:
        raise FileNotFoundError(f"Backend package is missing: {root}")
    digest = hashlib.sha256(str(root).encode("utf-8"))
    for filename, source in sources.items():
        digest.update(filename.encode("utf-8") + b"\0" + source + b"\0")
    revision = digest.hexdigest()
    namespace = f"_neuro_backend_{revision}"
    with _lock:
        if namespace not in _backends:
            if _sources not in sys.meta_path:
                sys.meta_path.insert(0, _sources)
            _sources.revisions[namespace] = (root, sources)
            # A private namespace keeps cached pipeline.* modules and active sessions untouched.
            backend = Backend(
                revision,
                importlib.import_module(f"{namespace}.data_quality"),
                importlib.import_module(f"{namespace}.profiles"),
                importlib.import_module(f"{namespace}.snapshot"),
            )
            _backends[namespace] = backend
        return _backends[namespace]
