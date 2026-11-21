# -*- coding: utf-8 -*-
"""stdlib 测试运行器：`python tests/run.py`（不依赖 pytest）。

pytest 可用时也可直接 `pytest tests/`。
"""
import importlib
import pathlib
import sys

HERE = pathlib.Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parent))  # efo/ 根，使 `import efo` 可用
sys.path.insert(0, str(HERE))         # tests/，使 test_* 可导入

MODS = ["test_events", "test_metrics", "test_laws", "test_calibrate"]


def main() -> int:
    passed = failed = 0
    for name in MODS:
        m = importlib.import_module(name)
        for fn in sorted(dir(m)):
            if fn.startswith("test_"):
                try:
                    getattr(m, fn)()
                    passed += 1
                    print(f"PASS  {name}.{fn}")
                except Exception as e:  # noqa: BLE001
                    failed += 1
                    print(f"FAIL  {name}.{fn}: {type(e).__name__}: {e}")
    print(f"\n{passed} passed, {failed} failed")
    return 1 if failed else 0


if __name__ == "__main__":
    raise SystemExit(main())
