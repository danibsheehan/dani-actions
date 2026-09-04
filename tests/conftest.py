from __future__ import annotations

import importlib.util
import sys
from pathlib import Path
from types import ModuleType

REPO_ROOT = Path(__file__).parent.parent


def load_module(rel_path: str) -> ModuleType:
    """Load a script from a hyphenated .github/actions/<name>/ dir as a module.

    Those directory names aren't valid Python package paths, so they can't be
    imported normally -- load directly from the file instead.
    """
    path = REPO_ROOT / rel_path
    module_name = path.stem
    spec = importlib.util.spec_from_file_location(module_name, path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[module_name] = module
    spec.loader.exec_module(module)
    return module
