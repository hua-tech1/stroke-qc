# -*- coding: utf-8 -*-
"""多路接入调度（生产侧实现）

与 `experiments/ascend_multichannel/pipeline.py` 是同一套调度语义，区别在于：
实验脚本负责**测量**（真实模型、真实帧、出报告），本模块负责**在系统里跑**，
推理后端由调用方注入（`infer_batch`），因此不依赖 torch / ultralytics / 昇腾。

语义（三句话）：
  1. 每路一个生产者，按帧率发帧；队列有界，满了计丢帧（背压，不静默丢弃）
  2. 路间轮转取帧凑批，一次前向处理一批 → 单卡服务多路
  3. 消费端可开保序缓冲：按 frame_idx 重排后再喂状态机

为什么需要保序：实测（4 路 / 乱序 p=0.3 / 90 帧）**无保序时 4 路只有 1 路事件正确，
有保序后 4/4 正确**。详见 experiments/ascend_multichannel/README.md。

边界：
  - 本模块不做解码。DVPP/VDEC 的角色由调用方在上游完成，本模块只吃"已解码的帧载荷"。
  - 不做限流与鉴权，属于接入层职责。
"""
from __future__ import annotations

import queue
import random
import statistics
import threading
import time
from dataclasses import dataclass, field
from typing import Any, Callable, Iterable, Sequence

from app.modules.events.state_machine import Event, generate_events


@dataclass
class ChannelFeed:
    """一路输入：载荷序列 + 帧率 + 可选乱序注入。"""

    cid: int
    payloads: Sequence[Any]
    fps: float = 15.0
    reorder_p: float = 0.0
    seed: int = 0
    queue_max: int = 256

    q: queue.Queue = field(default_factory=queue.Queue, repr=False)
    stop: threading.Event = field(default_factory=threading.Event, repr=False)
    dropped: int = 0

    def __post_init__(self) -> None:
        self.q = queue.Queue(maxsize=self.queue_max)
        self.stop = threading.Event()
        self.dropped = 0

    @property
    def frame_ms(self) -> float:
        return 1000.0 / self.fps

    def _order(self) -> list[int]:
        idx = list(range(len(self.payloads)))
        if self.reorder_p > 0:
            rng = random.Random(self.seed)
            for i in range(len(idx) - 1):
                if rng.random() < self.reorder_p:
                    idx[i], idx[i + 1] = idx[i + 1], idx[i]
        return idx

    def start(self, paced: bool = True) -> threading.Thread:
        t = threading.Thread(target=self._produce, args=(paced,), daemon=True)
        t.start()
        return t

    def _produce(self, paced: bool) -> None:
        t0 = time.perf_counter()
        try:
            for k, i in enumerate(self._order()):
                if paced:
                    wait = (t0 + k * self.frame_ms / 1000.0) - time.perf_counter()
                    if wait > 0:
                        time.sleep(wait)
                try:
                    self.q.put_nowait((i, time.perf_counter()))
                except queue.Full:
                    self.dropped += 1
        finally:
            self.stop.set()


def run_channels(
    feeds: Sequence[ChannelFeed],
    infer_batch: Callable[[list[Any]], Iterable[float]],
    *,
    batch: int | None = None,
    paced: bool = True,
    order_buffer: bool = True,
) -> dict:
    """跑完整条多路管线，返回每路的置信度序列、事件、时延与丢帧。

    infer_batch  接收一批载荷，返回与之一一对应的最大置信度
    batch        一批最多几帧，默认 = 路数（每路每批取 1 帧）
    paced        True 按帧率发帧（实时语义）；False 全速排空（测容量）
    order_buffer True 按 frame_idx 重排后再喂状态机
    """
    n = len(feeds)
    batch = batch or n
    for f in feeds:
        f.start(paced=paced)

    confs: dict[int, dict[int, float]] = {f.cid: {} for f in feeds}
    recv: dict[int, list[int]] = {f.cid: [] for f in feeds}
    arrival: dict[int, dict[int, float]] = {f.cid: {} for f in feeds}
    lat: dict[int, list[float]] = {f.cid: [] for f in feeds}
    busy_ms: list[float] = []
    sizes: list[int] = []
    done = {f.cid: False for f in feeds}

    while not all(done.values()):
        items = []
        for f in feeds:
            if len(items) >= batch:
                break
            try:
                idx, ts = f.q.get_nowait()
                items.append((f, idx, ts))
            except queue.Empty:
                pass

        if not items:
            if all(f.stop.is_set() and f.q.empty() for f in feeds):
                break
            time.sleep(0.0005)
            continue

        t0 = time.perf_counter()
        out = list(infer_batch([f.payloads[idx] for f, idx, _ in items]))
        if len(out) != len(items):
            raise ValueError(f"infer_batch 返回 {len(out)} 个结果，输入 {len(items)} 帧")
        busy_ms.append((time.perf_counter() - t0) * 1000)
        sizes.append(len(items))

        now = time.perf_counter()
        for (f, idx, ts), c in zip(items, out):
            confs[f.cid][idx] = float(c)
            recv[f.cid].append(idx)
            arrival[f.cid][idx] = ts
            if paced:
                lat[f.cid].append((now - ts) * 1000)

        for f in feeds:
            if f.stop.is_set() and f.q.empty():
                done[f.cid] = True

    per_channel = {}
    for f in feeds:
        order = sorted(confs[f.cid]) if order_buffer else recv[f.cid]
        lm = lat[f.cid]
        per_channel[f.cid] = {
            "confs": confs[f.cid],
            "order": order,
            "frames": len(order),
            "dropped": f.dropped,
            "lat_p50": round(statistics.median(lm), 1) if lm else None,
            "lat_p99": round(sorted(lm)[int(0.99 * (len(lm) - 1))], 1) if lm else None,
        }

    return {
        "channels": n,
        "batch": batch,
        "paced": paced,
        "order_buffer": order_buffer,
        "infer_ms_per_frame": round(statistics.mean(busy_ms) / statistics.mean(sizes), 2)
        if busy_ms else None,
        "per_channel": per_channel,
    }


def events_for(result: dict, cid: int, *,
               conf: float = 0.5, frame_ms: float = 1000.0 / 15.0,
               k_in: int = 3, m_out: int = 5) -> list[Event]:
    """把某一路的置信度序列喂给状态机，产出事件。"""
    pc = result["per_channel"][cid]
    confs = pc["confs"]
    frames = [{"frame": i, "ts_ms": round(i * frame_ms, 2),
               "boxes": [{"conf": confs[i]}] if confs.get(i, 0.0) > 0 else []}
              for i in pc["order"]]
    return generate_events(frames, conf=conf, k_in=k_in, m_out=m_out)
