"""Test helpers shared by the suite.

modules_patched(mapping): put fake modules into sys.modules for a block and put back ONLY those names afterwards.

Why not mock.patch.dict(sys.modules, ...)? On exit it clears sys.modules and restores a snapshot, which evicts every module first imported inside the
block. On a Mac the code under test imports the real PyObjC (`import objc`) inside such a block; the eviction removes it, the next `import objc` runs the
C extension again, and PyObjC refuses: "RuntimeError: Reload of objc._objc detected, this is not supported". Native extensions cannot be re-imported."""
import contextlib, sys

_MISSING = object()


@contextlib.contextmanager
def modules_patched(mapping):
    saved = {k: sys.modules.get(k, _MISSING) for k in mapping}
    sys.modules.update(mapping)
    try:
        yield
    finally:
        for k, v in saved.items():
            if v is _MISSING:
                sys.modules.pop(k, None)
            else:
                sys.modules[k] = v
