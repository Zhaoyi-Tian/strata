"""读取配置：config/default.toml（规律与玩法），以及它指向的世界观文件。"""

import tomllib
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]                  # strata/


def _merge(a: dict, b: dict) -> dict:
    return {**a, **{k: _merge(a[k], v) if isinstance(v, dict) and isinstance(a.get(k), dict) else v
                    for k, v in b.items()}}


def load(path: str | Path | None = None) -> dict:
    """path 里只写要改的项。返回的 cfg["view"] 是世界观。"""
    cfg = tomllib.loads((ROOT / "config" / "default.toml").read_text(encoding="utf-8"))
    if path:
        cfg = _merge(cfg, tomllib.loads(Path(path).read_text(encoding="utf-8")))
    cfg["view"] = tomllib.loads((ROOT / cfg["worldview"]).read_text(encoding="utf-8"))
    return cfg
