# -*- coding: utf-8 -*-
"""EFO 实验核心：事件保真（Event Fidelity Optimization）评价基础件

设计原则
--------
1. 只依赖标准库，不引入 numpy/pandas —— 评委与本机都要能一条命令跑起来。
2. 不复制状态机逻辑，直接 import 项目里的 `generate_events`，
   保证"实验里测的"与"系统里跑的"是同一份实现（否则结论不可信）。
3. 所有随机过程固定种子，报告里写回种子值。

术语
----
- 命中帧(hit frame)：某一帧检测到 conf >= CONF 的框
- 可见段(visible run)：真值上器械连续出现的帧区间 [a, b]
- 事件(event)：状态机输出的离散事件 device_visible_start / device_visible_end
- 事件级指标：以"事件"为评价单元，而非"帧"
"""
from __future__ import annotations

import json
import random
import statistics
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Iterable, Sequence

# 仓库根目录：experiments/efo/core.py -> 上溯三级
REPO_ROOT = Path(__file__).resolve().parents[2]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from app.core import config as C  # noqa: E402  必须在 REPO_ROOT 推导之后
from app.modules.events.state_machine import Event, generate_events, dwell_ms, is_open  # noqa: E402

DATA_DIR = REPO_ROOT / "data" / "demo" / "json"
OUT_DIR = Path(__file__).resolve().parent / "out"

START = C.EV_VISIBLE_START
END = C.EV_VISIBLE_END


# ---------------------------------------------------------------- 数据装载
def list_sequences() -> list[str]:
    """列出 data/demo/json 下所有可用序列。"""
    return sorted(p.stem for p in DATA_DIR.glob("*.json"))


def load_detection(seq: str) -> dict:
    """读取一段预生成检测结果（离线序列）。"""
    path = DATA_DIR / f"{seq}.json"
    if not path.exists():
        raise FileNotFoundError(f"序列不存在：{path}")
    return json.loads(path.read_text(encoding="utf-8"))


def hit_flags(det: dict) -> list[bool]:
    """把检测结果压成逐帧布尔命中序列（与状态机同口径）。"""
    return [bool(fr.get("hit")) for fr in det["frames"]]


# ---------------------------------------------------------------- 构造输入
def build_frames(hits: Sequence[bool], frame_ms: float,
                 conf_hit: float = 0.9, conf_miss: float = 0.1) -> list[dict]:
    """由布尔命中序列构造状态机输入。

    状态机只认 boxes[].conf 与 k 帧连续性，因此这里给命中帧一个高置信框、
    未命中帧一个低于阈值的框，等价于"检测器输出"。
    """
    frames = []
    for i, h in enumerate(hits):
        frames.append({
            "frame": i,
            "ts_ms": round(i * frame_ms, 2),
            "boxes": [{"conf": conf_hit if h else conf_miss}],
        })
    return frames


def build_frames_from_detection(det: dict, hits: Sequence[bool]) -> list[dict]:
    """保留原始 ts_ms，只替换命中状态（用于在真实序列上注入噪声）。"""
    frames = []
    for fr, h in zip(det["frames"], hits):
        boxes = fr.get("boxes") or []
        if h:
            # 命中：沿用原置信度；原来没有框则给一个保底高置信
            boxes = boxes or [{"conf": 0.9}]
        else:
            # 未命中：把所有框压到阈值以下（保留框但不可用，更接近真实误检）
            boxes = [dict(b, conf=0.1) for b in boxes]
        frames.append({"frame": fr["frame"], "ts_ms": fr["ts_ms"], "boxes": boxes})
    return frames


# ---------------------------------------------------------------- 状态机调用
def run_sm(frames: list[dict], conf: float | None = None,
           k_in: int | None = None, m_out: int | None = None) -> list[Event]:
    return generate_events(
        frames,
        conf=C.CONF if conf is None else conf,
        k_in=C.K_IN if k_in is None else k_in,
        m_out=C.M_OUT if m_out is None else m_out,
    )


def events_of(events: Iterable[Event], code: str) -> list[Event]:
    return [e for e in events if e.code == code]


# ---------------------------------------------------------------- 指标
def merge_runs(flags: Sequence[bool]) -> list[tuple[int, int]]:
    """把布尔序列合并成 True 的连续区间 [start, end]（闭区间，帧号）。"""
    runs, start = [], None
    for i, f in enumerate(flags):
        if f and start is None:
            start = i
        elif not f and start is not None:
            runs.append((start, i - 1))
            start = None
    if start is not None:
        runs.append((start, len(flags) - 1))
    return runs


@dataclass
class MatchResult:
    tp: int
    fp: int
    fn: int

    @property
    def precision(self) -> float:
        return self.tp / (self.tp + self.fp) if (self.tp + self.fp) else 0.0

    @property
    def recall(self) -> float:
        return self.tp / (self.tp + self.fn) if (self.tp + self.fn) else 0.0

    @property
    def f1(self) -> float:
        p, r = self.precision, self.recall
        return 2 * p * r / (p + r) if (p + r) else 0.0


def match_pairs(ref: Sequence[Event], test: Sequence[Event],
                tol_frames: int = 2) -> tuple[list[tuple[Event, Event]], int, int]:
    """按事件类型 + 帧号容差做贪心最近匹配。

    ref 为参照（真值/干净运行），test 为待评。一对一匹配，不重复使用。
    返回 (匹配对列表, 误报数 fp, 漏报数 fn)。
    """
    ref_pool = list(ref)
    used = [False] * len(ref_pool)
    pairs: list[tuple[Event, Event]] = []
    for t in test:
        best_i, best_d = -1, None
        for i, r in enumerate(ref_pool):
            if used[i] or r.code != t.code:
                continue
            d = abs(r.frame - t.frame)
            if d <= tol_frames and (best_d is None or d < best_d):
                best_i, best_d = i, d
        if best_i >= 0:
            used[best_i] = True
            pairs.append((ref_pool[best_i], t))
    return pairs, len(test) - len(pairs), sum(1 for u in used if not u)


def match_events(ref: Sequence[Event], test: Sequence[Event],
                 tol_frames: int = 2) -> MatchResult:
    pairs, fp, fn = match_pairs(ref, test, tol_frames)
    return MatchResult(tp=len(pairs), fp=fp, fn=fn)


def detection_rate(trials: Iterable[list[Event]]) -> float:
    """一批试次中，"至少出现一次入画事件"的比例。"""
    n, k = 0, 0
    for evs in trials:
        n += 1
        if events_of(evs, START):
            k += 1
    return k / n if n else 0.0


def wilson_ci(k: int, n: int, z: float = 1.96) -> tuple[float, float]:
    """Wilson 置信区间：网评里报"0.950 [0.93, 0.97]"比裸点估计可信。"""
    if n == 0:
        return (0.0, 0.0)
    p = k / n
    denom = 1 + z * z / n
    centre = (p + z * z / (2 * n)) / denom
    half = z * ((p * (1 - p) / n + z * z / (4 * n * n)) ** 0.5) / denom
    return (max(0.0, centre - half), min(1.0, centre + half))


# ---------------------------------------------------------------- 输出
def write_outputs(name: str, payload: dict, tables: list[str]) -> Path:
    """把结构化结果写 JSON，把可读表格写 Markdown。"""
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    (OUT_DIR / f"{name}.json").write_text(
        json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    md = f"# {name}\n\n" + "\n\n".join(tables) + "\n"
    path = OUT_DIR / f"{name}.md"
    path.write_text(md, encoding="utf-8")
    return path


def md_table(header: Sequence[str], rows: Sequence[Sequence[object]]) -> str:
    out = ["| " + " | ".join(header) + " |",
           "|" + "|".join(["---"] * len(header)) + "|"]
    for r in rows:
        out.append("| " + " | ".join(str(c) for c in r) + " |")
    return "\n".join(out)


def rng(seed: int) -> random.Random:
    return random.Random(seed)


def mean(xs: Sequence[float]) -> float:
    return statistics.fmean(xs) if xs else float("nan")


def pct(xs: Sequence[float], q: float) -> float:
    if not xs:
        return float("nan")
    s = sorted(xs)
    idx = min(len(s) - 1, max(0, int(round(q * (len(s) - 1)))))
    return s[idx]
