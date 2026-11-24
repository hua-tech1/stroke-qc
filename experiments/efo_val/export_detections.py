# -*- coding: utf-8 -*-
"""把 1527 帧验证集导出成 EFO 数据契约（逐帧检测 + 逐帧真值）。

为什么需要它：experiments/efo 目前只跑在 114 + 294 帧两段演示序列上，
只有 2 个参照事件，不足以支撑统计结论（见 experiments/efo/README.md「如何接入 1527 帧验证集」）。
本脚本把真实验证集接进来：15 个序列 / 1527 帧 / 逐帧真值命中。

输出契约与 data/demo/json 完全一致，另加 gt_hit 字段（该帧标注里是否有导丝）：
  {"seq", "fps", "frame_ms", "frames":[{"frame","ts_ms","hit","boxes":[{"conf"}],"gt_hit"}]}

运行（需 CUDA 版 torch + ultralytics）：
  python experiments/efo_val/export_detections.py --weights <best.pt> --device 0
"""
from __future__ import annotations

import argparse
import json
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
DEFAULT_VAL = Path(r"C:\Users\HUA\Desktop\project\data\guidewire_yolo\images\val")
DEFAULT_LAB = Path(r"C:\Users\HUA\Desktop\project\data\guidewire_yolo\labels\val")
OUT = Path(__file__).resolve().parent / "out" / "detections"

FPS = 15.0                      # 与系统 config 一致；DSA 序列帧率假设
FRAME_MS = 1000.0 / FPS
# 低阈值导出：把逐帧置信度分布完整留下来，后续可在任意 conf 上重算事件
EXPORT_CONF = 0.01


def seq_of(stem: str) -> str:
    """2_navi00000000 -> '2'；4_ST0_SE10_000012 -> '4_ST0_SE10'。"""
    head, _, tail = stem.rpartition("_")
    if head and re.fullmatch(r"\d+", tail):
        return head
    m = re.fullmatch(r"(.+?)_navi(\d+)", stem)
    if m:
        return m.group(1)
    return stem


def frame_of(stem: str) -> int:
    m = re.search(r"(\d+)$", stem)
    return int(m.group(1)) if m else 0


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--weights", required=True)
    ap.add_argument("--val", default=str(DEFAULT_VAL))
    ap.add_argument("--labels", default=str(DEFAULT_LAB))
    ap.add_argument("--device", default="0")
    ap.add_argument("--imgsz", type=int, default=640)
    args = ap.parse_args()

    from ultralytics import YOLO

    val_dir, lab_dir = Path(args.val), Path(args.labels)
    img_files = sorted(val_dir.glob("*.png")) + sorted(val_dir.glob("*.jpg"))
    if not img_files:
        raise SystemExit(f"验证集为空：{val_dir}")

    groups: dict[str, list[tuple[int, Path]]] = {}
    for p in img_files:
        groups.setdefault(seq_of(p.stem), []).append((frame_of(p.stem), p))

    model = YOLO(args.weights)
    OUT.mkdir(parents=True, exist_ok=True)

    manifest = []
    for seq in sorted(groups):
        items = sorted(groups[seq], key=lambda x: x[0])
        frames = []
        for idx, (fno, img) in enumerate(items):
            res = model.predict(str(img), imgsz=args.imgsz, conf=EXPORT_CONF,
                                device=args.device, verbose=False)[0]
            confs = []
            if res.boxes is not None and len(res.boxes) > 0:
                confs = [round(float(c), 4) for c in res.boxes.conf.tolist()]
                confs.sort(reverse=True)
            lab = lab_dir / (img.stem + ".txt")
            gt_hit = False
            if lab.exists():
                txt = lab.read_text(encoding="utf-8", errors="ignore").strip()
                gt_hit = bool(txt)
            frames.append({
                "frame": fno,
                "ts_ms": round(idx * FRAME_MS, 2),   # 序列内偏移，与系统口径一致
                "hit": any(c >= 0.5 for c in confs),
                "boxes": [{"conf": c} for c in confs],
                "gt_hit": gt_hit,
            })
        rec = {"seq": seq, "fps": FPS, "frame_ms": round(FRAME_MS, 3),
               "frames": frames, "source": "val1527",
               "weights": Path(args.weights).name}
        (OUT / f"{seq}.json").write_text(
            json.dumps(rec, ensure_ascii=False), encoding="utf-8")
        gt_n = sum(1 for f in frames if f["gt_hit"])
        manifest.append({"seq": seq, "frames": len(frames), "gt_hit_frames": gt_n})
        print(f"  {seq:14s} frames={len(frames):4d} gt_hit={gt_n:4d}")

    (OUT / "_manifest.json").write_text(
        json.dumps({"sequences": manifest, "total_frames": sum(m["frames"] for m in manifest),
                    "fps": FPS, "export_conf": EXPORT_CONF},
                   ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"\n导出完成：{len(manifest)} 序列 / "
          f"{sum(m['frames'] for m in manifest)} 帧 -> {OUT}")


if __name__ == "__main__":
    main()
