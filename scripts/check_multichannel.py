# -*- coding: utf-8 -*-
"""多路调度自检（不需要 GPU / 不需要数据库）

验证三件事：
  1. 多路并发本身不改变事件语义（无乱序时，各路事件一致）
  2. 乱序会破坏事件（临界长度动作最脆弱）
  3. 保序缓冲能把事件恢复

用假推理器（按帧号给固定置信度）替代模型，只测调度与保序逻辑。
真实模型下的实测数字见 experiments/ascend_multichannel/README.md。

运行：python scripts/check_multichannel.py
"""
from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from app.modules.events.multichannel import ChannelFeed, events_for, run_channels  # noqa: E402

N_FRAMES = 60
HOT = (40, 41, 42)          # 恰好 k_in=3 帧的临界动作
CONF_HOT, CONF_COLD = 0.95, 0.02


def fake_infer(payloads) -> list[float]:
    """假推理：临界段（40~42 帧）有导丝，其余没有。载荷即帧号。"""
    return [CONF_HOT if int(p) in HOT else CONF_COLD for p in payloads]


def one_run(n_ch: int, reorder_p: float, buffer: bool) -> dict:
    feeds = [ChannelFeed(cid=i, payloads=list(range(N_FRAMES)),
                         fps=200.0,                # 自检用高帧率，跑得快
                         reorder_p=reorder_p, seed=100 + i)
             for i in range(n_ch)]
    return run_channels(feeds, fake_infer, batch=n_ch, paced=False, order_buffer=buffer)


def events_of(res: dict, cid: int) -> list[tuple[str, int]]:
    return [(e.code, e.frame) for e in events_for(res, cid, conf=0.5, frame_ms=5.0)]


def main() -> None:
    fails = []

    # 基准：无乱序、有保序
    base = one_run(4, 0.0, True)
    ref = events_of(base, 0)
    ok = all(events_of(base, c) == ref for c in range(4))
    print(f"[1] 4 路并发（无乱序）事件一致：{'PASS' if ok else 'FAIL'}  ref={ref}")
    if not ok:
        fails.append("并发不一致")

    # 乱序 + 无保序：应当出现不一致
    bad = one_run(4, 0.3, False)
    same_bad = sum(1 for c in range(4) if events_of(bad, c) == ref)
    print(f"[2] 乱序 p=0.3 无保序：{same_bad}/4 路仍正确（期望 < 4）")
    if same_bad >= 4:
        fails.append("乱序未能破坏事件（随机性不足，可增大 reorder_p 重试）")

    # 乱序 + 有保序：应全部恢复
    good = one_run(4, 0.3, True)
    same_good = sum(1 for c in range(4) if events_of(good, c) == ref)
    print(f"[3] 乱序 p=0.3 有保序：{same_good}/4 路正确（期望 4）")
    if same_good != 4:
        fails.append("保序未能完全恢复")

    print("\n结论：", "全部通过" if not fails else f"未通过 -> {fails}")
    sys.exit(0 if not fails else 1)


if __name__ == "__main__":
    main()
