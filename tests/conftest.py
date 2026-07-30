# .claude/skill-loop/tests/conftest.py
"""Test isolation for the skill loop.

Caught live, not by the suite: the first real `curator.py --dry-run` against the
production skills dir found the run log already holding ten events nobody ran --
four curator records dated 2026-07-15 (the tests' frozen NOW, manifest_count 1)
and six learn records 300ms apart. Any test that calls `main()` without
redirecting `log_target` writes to the user's REAL ~/.claude/skill-loop.jsonl,
which is precisely the artifact you consult to find out what the loop actually
did. A diagnostic log that tests can forge is worse than no log.

So isolation is autouse and not the individual test's job to remember.
"""
import sys, pathlib
import pytest

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1] / "scripts"))

import runlog as _runlog  # noqa: E402

# Captured before the autouse fixture can replace it, for the handful of tests
# whose subject IS the path resolution.
_ORIGINAL_LOG_PATH = _runlog.log_path


@pytest.fixture
def unpatched_log_path():
    """The real `runlog.log_path`, escaping the isolation fixture below.

    It still reads `load_config` and `Path.home` off the module at call time, so
    monkeypatching those in a test works exactly as it did before isolation.
    """
    return _ORIGINAL_LOG_PATH


@pytest.fixture(autouse=True)
def isolated_run_log(tmp_path, monkeypatch):
    """Point every module's run log at a per-test file.

    Applied before the test body, so a test that redirects `log_target` itself
    still wins — this is a floor, not a ceiling.
    """
    log = tmp_path / "isolated-skill-loop.jsonl"
    import runlog
    monkeypatch.setattr(runlog, "log_path", lambda: log)
    for name in ("curator", "learn", "usage"):
        try:
            mod = __import__(name)
        except ImportError:
            continue
        if hasattr(mod, "log_target"):
            monkeypatch.setattr(mod, "log_target", lambda log=log: log)
    return log
