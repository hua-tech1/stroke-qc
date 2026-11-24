# -*- coding: utf-8 -*-
"""多路并发接入管线 · 可运行实现 + 两组干净测量

为什么需要它
------------
"昇腾 DVPP 多路"目前只停在 PPT 架构图上，代码里 `LiveStreamSource` 是抛异常的桩。
但多路管线的**软件部分**（路间调度、批处理、保序、事件级正确性）与硬件无关，
现在就能实现并测出真实数字。DVPP 只是把"解码"这一环换成专用单元，其余完全一致。

本实现：
    每路按帧率发帧(或全速排空) → 路间轮转调度 → 单卡批处理推理 → 逐路状态机 → 事件

两组测量（分开做，不混在一起）：
  capacity  全速排空，测「纯推理容量」：不同 batch 下的单帧耗时与可支撑路数。
            解码用"预加载到内存的帧"代替 DVPP 输出，排除磁盘 I/O。
  realtime  按 15fps 实时发帧，测「端到端时延」与「事件级正确性」：
            每路的入画/离画事件是否与"按帧序重排"的基准完全一致。

用法：
  python experiments/ascend_multichannel/pipeline.py --mode capacity
  python experiments/ascend_multichannel/pipeline.py --mode realtime --channels 2,4

边界（必须写进材料）
--------------------
- 解码环节用预加载内存帧代替 DVPP 硬解：本实验测的是**调度/推理/事件化**，
  不是 DVPP 吞吐；DVPP 容量另见 experiments/ascend/capacity_model.py（规格推算）。
- 本机 RTX 5060 + ultralytics Python 前端；昇腾上应走 ACL/ACLLite + 模型固化，
  单帧开销会不同，因此**不能把本机的时延数字直接搬成昇腾数字**。
"""

from __future__ import annotations

import argparse
import json
import queue
import re
import statistics
import sys
import threading
import time
from pathlib import Path

import cv2

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[1]
OUT = HERE / "out"
sys.path.insert(0, str(ROOT / "packages" / "efo"))

from efo import generate_events  # noqa: E402

VAL_DIR = Path(r"C:\Users\HUA\Desktop\project\data\guidewire_yolo\images\val")
FPS = 15.0
FRAME_MS = 1000.0 / FPS
CONF, K_IN, M_OUT = 0.5, 3, 5


# ---------------------------------------------------------------- 数据
def seq_of(stem: str) -> str:
    head, _, tail = stem.rpartition("_")
    if head and re.fullmatch(r"\d+", tail):
        return head
    m = re.fullmatch(r"(.+?)_navi(\d+)", stem)
    return m.group(1) if m else stem


def index_of(stem: str) -> int:
    m = re.search(r"(\d+)$", stem)
    return int(m.group(1)) if m else 0


def pick_sequences(n: int, max_frames: int) -> list[list[Path]]:
    groups: dict[str, list[Path]] = {}
    for p in sorted(VAL_DIR.glob("*.png")):
        groups.setdefault(seq_of(p.stem), []).append(p)
    if len(groups) < n:
        raise SystemExit(f"序列不足：需要 {n} 路，只有 {len(groups)} 路")
    order = sorted(groups.values(), key=len, reverse=True)
    return [sorted(g, key=lambda p: index_of(p.stem))[:max_frames] for g in order[:n]]


def preload(paths: list[Path]) -> list["cv2.Mat"]:
    imgs = []
    for p in paths:
        im = cv2.imread(str(p), cv2.IMREAD_COLOR)
        if im is not None:
            imgs.append(im)
    return imgs


# ---------------------------------------------------------------- 管线
class Channel:
    def __init__(self, cid: int, imgs: list, reorder_p: float, seed: int):
        self.cid = cid
        self.imgs = imgs
        self.q: queue.Queue = queue.Queue(maxsize=256)
        self.arrival: dict[int, float] = {}
        self.conf: dict[int, float] = {}
        self.recv_order: list[int] = []
        self.latencies: list[float] = []
        self.dropped = 0
        self.reorder_p = reorder_p
        self.seed = seed
        self.stop = threading.Event()

    def produce(self, paced: bool) -> None:
        import random
        rng = random.Random(self.seed)
        order = list(range(len(self.imgs)))
        if self.reorder_p > 0:                      # 模拟多路异步解码回传乱序
            for i in range(len(order) - 1):
                if rng.random() < self.reorder_p:
                    order[i], order[i + 1] = order[i + 1], order[i]
        t0 = time.perf_counter()
        for k, i in enumerate(order):
            if paced:
                target = t0 + k * (FRAME_MS / 1000.0)
                wait = target - time.perf_counter()
                if wait > 0:
                    time.sleep(wait)
            try:
                self.q.put_nowait((i, time.perf_counter()))
            except queue.Full:
                self.dropped += 1
        self.stop.set()


def run(model, chans: list[Channel], batch: int, paced: bool,
        imgsz: int, device: str, order_buffer: bool = True) -> dict:
    for ch in chans:
        threading.Thread(target=ch.produce, args=(paced,), daemon=True).start()

    busy_ms, sizes = [], []
    done = {c.cid: False for c in chans}
    while not all(done.values()):
        items = []
        for ch in chans:
            if len(items) >= batch:
                break
            try:
                idx, arrival = ch.q.get_nowait()
                items.append((ch, idx, arrival, ch.imgs[idx]))
            except queue.Empty:
                pass

        if not items:
            if all(c.stop.is_set() and c.q.empty() for c in chans):
                break
            time.sleep(0.0005)
            continue

        t0 = time.perf_counter()
        res = model.predict([it[3] for it in items], imgsz=imgsz, conf=0.01,
                            device=device, verbose=False)
        dt = (time.perf_counter() - t0) * 1000
        busy_ms.append(dt)
        sizes.append(len(items))

        now = time.perf_counter()
        for (ch, idx, arrival, _), r in zip(items, res):
            best = float(r.boxes.conf.max()) if (r.boxes is not None and len(r.boxes)) else 0.0
            ch.conf[idx] = best
            ch.recv_order.append(idx)
            if paced:
                ch.latencies.append((now - arrival) * 1000)

        for ch in chans:
            if ch.stop.is_set() and ch.q.empty():
                done[ch.cid] = True

    out = {}
    for ch in chans:
        ref_frames = [{"frame": i, "ts_ms": round(i * FRAME_MS, 2),
                       "boxes": [{"conf": ch.conf[i]}] if ch.conf.get(i, 0) > 0 else []}
                      for i in sorted(ch.conf)]
        ref_ev = [(e.code, e.frame) for e in
                  generate_events(ref_frames, conf=CONF, k_in=K_IN, m_out=M_OUT)]

        order = sorted(ch.conf) if order_buffer else ch.recv_order
        as_is = [{"frame": i, "ts_ms": round(i * FRAME_MS, 2),
                  "boxes": [{"conf": ch.conf[i]}] if ch.conf.get(i, 0) > 0 else []}
                 for i in order]
        act_ev = [(e.code, e.frame) for e in
                  generate_events(as_is, conf=CONF, k_in=K_IN, m_out=M_OUT)]

        lat = sorted(ch.latencies)
        out[ch.cid] = {
            "frames": len(ch.conf),
            "events_ref": len(ref_ev), "events_actual": len(act_ev),
            "events_identical": act_ev == ref_ev,
            "lat_p50": round(statistics.median(lat), 1) if lat else None,
            "lat_p95": round(lat[int(0.95 * (len(lat) - 1))], 1) if lat else None,
            "lat_p99": round(lat[int(0.99 * (len(lat) - 1))], 1) if lat else None,
            "dropped": ch.dropped,
        }
    return {
        "channels": len(chans),
        "infer_ms_per_batch": round(statistics.mean(busy_ms), 2) if busy_ms else None,
        "mean_batch": round(statistics.mean(sizes), 2) if sizes else None,
        "infer_ms_per_frame": round(statistics.mean(busy_ms) / statistics.mean(sizes), 2)
        if busy_ms else None,
        "per_channel": out,
    }


# ---------------------------------------------------------------- 主流程
def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--weights", default=r"C:\Users\HUA\Desktop\project\runs\baseline\weights\best.pt")
    ap.add_argument("--mode", default="capacity", choices=["capacity", "realtime"])
    ap.add_argument("--channels", default="1,2,4,8")
    ap.add_argument("--frames", type=int, default=80)
    ap.add_argument("--imgsz", type=int, default=640)
    ap.add_argument("--device", default="0")
    ap.add_argument("--reorder-p", type=float, default=0.0)
    ap.add_argument("--buffer", default="on", choices=["on", "off"])
    ap.add_argument("--seed", type=int, default=42)
    args = ap.parse_args()

    from ultralytics import YOLO
    model = YOLO(args.weights)
    OUT.mkdir(parents=True, exist_ok=True)

    # 预热：排除首次前向的算子初始化与显存分配
    warm = preload(pick_sequences(1, 4)[0])
    for _ in range(5):
        model.predict(warm, imgsz=args.imgsz, conf=0.01, device=args.device, verbose=False)
    print("预热完成")

    ns = [int(x) for x in args.channels.split(",")]
    rows = []
    if args.mode == "capacity":
        for n in ns:
            chans = [Channel(i, preload(pick_sequences(n, args.frames)[i]), 0.0, args.seed + i)
                     for i in range(n)]
            r = run(model, chans, batch=n, paced=False, imgsz=args.imgsz, device=args.device)
            cap_fps = 1000.0 / r["infer_ms_per_frame"]
            row = {"channels": n, "batch": n, "frames_per_channel": args.frames,
                   "infer_ms_per_frame": r["infer_ms_per_frame"],
                   "mean_batch": r["mean_batch"],
                   "capacity_fps": round(cap_fps, 1),
                   "max_channels_at_15fps": round(cap_fps / FPS, 1),
                   "util_at_this_n": round(100.0 * (n * FPS) / cap_fps, 1)}
            rows.append(row)
            print(f"batch={n:2d} 单帧等效={row['infer_ms_per_frame']:6.2f}ms  "
                  f"容量={row['capacity_fps']:7.1f} fps  "
                  f"可支撑={row['max_channels_at_15fps']:5.1f} 路  "
                  f"{n}路负载={row['util_at_this_n']}%")
        (OUT / "capacity.json").write_text(json.dumps(rows, ensure_ascii=False, indent=2),
                                           encoding="utf-8")
        print(f"\n输出：{OUT / 'capacity.json'}")

    else:
        for n in ns:
            chans = [Channel(i, preload(pick_sequences(n, args.frames)[i]), args.reorder_p,
                             args.seed + i) for i in range(n)]
            r = run(model, chans, batch=n, paced=True, imgsz=args.imgsz,
                    device=args.device, order_buffer=(args.buffer == "on"))
            pc = r["per_channel"]
            ok = sum(1 for v in pc.values() if v["events_identical"])
            drops = sum(v["dropped"] for v in pc.values())
            p99 = max((v["lat_p99"] or 0) for v in pc.values())
            rows.append({"channels": n, "frames_per_channel": args.frames,
                         "reorder_p": args.reorder_p,
                         "lat_p99_max": p99, "drops": drops,
                         "events_identical": f"{ok}/{n}", "detail": pc})
            print(f"N={n}  最差 p99={p99:7.1f}ms  掉帧={drops:3d}  "
                  f"事件与基准一致={ok}/{n}")
        tag = "reorder" if args.reorder_p > 0 else "realtime"
        (OUT / f"{tag}.json").write_text(json.dumps(rows, ensure_ascii=False, indent=2),
                                         encoding="utf-8")
        print(f"\n输出：{OUT / f'{tag}.json'}")


if __name__ == "__main__":
    main()
