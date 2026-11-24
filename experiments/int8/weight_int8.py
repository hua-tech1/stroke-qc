# -*- coding: utf-8 -*-
"""INT8 权重量化对照（per-channel 对称 fake-quant，激活保持 FP32）

背景：材料里「量化感知重标定」目前只有合成示例（3 帧 conf 0.60→0.48），
被问到「真实量化会这样吗」时没有实物。本脚本给出一个**真实的权重量化对照**。

做的是什么（要精确表述，不能含糊）：
  ✅ 真实：把每个 Conv2d 的权重按 per-channel 对称 INT8 量化（scale = max|w|/127，
     四舍五入到整数格点后反量化），这是标准 PTQ 的第一步，数值是真量化。
  ❌ 不是：完整 INT8 推理。激活仍是 FP32，没有激活校准、没有 INT8 算子。
     完整 INT8 需要 AMCT / onnxruntime（本机 pip 受限装不上）。

预期结论（先写下来，跑完对照）：
  权重量化对 YOLOv8n 通常近无损；若事件级几乎不变，则说明「量化崩坏」的
  真实触发点是**置信度分布漂移跨越判定阈值**，而不是权重误差本身 ——
  这恰好是 recalibrate_after_quant 要处理的情形，也是该结论的诚实边界。

运行（需 CUDA 版 torch + ultralytics）：
  python experiments/int8/weight_int8.py --weights <best.pt>
"""
from __future__ import annotations

import argparse
import copy
import json
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
DEFAULT_VAL = Path(r"C:\Users\HUA\Desktop\project\data\guidewire_yolo\images\val")
OUT = Path(__file__).resolve().parent / "out" / "detections_int8w"
FPS = 15.0
FRAME_MS = 1000.0 / FPS
EXPORT_CONF = 0.01
QMAX = 127


def seq_of(stem: str) -> str:
    head, _, tail = stem.rpartition("_")
    if head and re.fullmatch(r"\d+", tail):
        return head
    m = re.fullmatch(r"(.+?)_navi(\d+)", stem)
    return m.group(1) if m else stem


def frame_of(stem: str) -> int:
    m = re.search(r"(\d+)$", stem)
    return int(m.group(1)) if m else 0


def quantize_weights(model, per_channel: bool = True) -> dict:
    """把 Conv2d 权重做 per-channel 对称 INT8 量化（反量化回 FP32 存放）。"""
    import torch

    n_tensors, n_params, errs = 0, 0, []
    for name, mod in model.named_modules():
        if isinstance(mod, torch.nn.Conv2d) and mod.weight is not None:
            w = mod.weight.data
            if per_channel:
                # 每输出通道独立 scale
                shape = (w.shape[0],) + (1,) * (w.dim() - 1)
                s = w.abs().amax(dim=tuple(range(1, w.dim())), keepdim=True) / QMAX
            else:
                s = w.abs().amax() / QMAX
            s = torch.clamp(s, min=1e-12)
            wq = torch.clamp(torch.round(w / s), -QMAX, QMAX) * s
            errs.append((wq - w).abs().max().item())
            mod.weight.data = wq
            n_tensors += 1
            n_params += w.numel()
    return {"conv_tensors": n_tensors, "params": n_params,
            "max_abs_err": round(max(errs) if errs else 0.0, 8),
            "per_channel": per_channel}


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--weights", required=True)
    ap.add_argument("--val", default=str(DEFAULT_VAL))
    ap.add_argument("--device", default="0")
    ap.add_argument("--imgsz", type=int, default=640)
    args = ap.parse_args()

    import torch
    from ultralytics import YOLO

    model = YOLO(args.weights)
    net = model.model
    net.eval()
    before = copy.deepcopy(net.state_dict())
    info = quantize_weights(net, per_channel=True)

    # 自检：确认权重确实被改过
    changed = sum(1 for k, v in net.state_dict().items()
                  if k in before and not torch.equal(v, before[k]))
    info["tensors_changed"] = changed
    print(f"量化完成：{info['conv_tensors']} 个 Conv2d，"
          f"{info['params']:,} 参数，最大绝对误差 {info['max_abs_err']}，"
          f"实际变更张量 {changed}")

    val_dir = Path(args.val)
    imgs = sorted(val_dir.glob("*.png")) + sorted(val_dir.glob("*.jpg"))
    groups: dict[str, list[tuple[int, Path]]] = {}
    for p in imgs:
        groups.setdefault(seq_of(p.stem), []).append((frame_of(p.stem), p))

    OUT.mkdir(parents=True, exist_ok=True)
    for seq in sorted(groups):
        items = sorted(groups[seq], key=lambda x: x[0])
        frames = []
        for idx, (fno, img) in enumerate(items):
            res = model.predict(str(img), imgsz=args.imgsz, conf=EXPORT_CONF,
                                device=args.device, verbose=False)[0]
            confs = []
            if res.boxes is not None and len(res.boxes) > 0:
                confs = sorted([round(float(c), 4) for c in res.boxes.conf.tolist()],
                               reverse=True)
            frames.append({"frame": fno, "ts_ms": round(idx * FRAME_MS, 2),
                           "hit": any(c >= 0.5 for c in confs),
                           "boxes": [{"conf": c} for c in confs]})
        rec = {"seq": seq, "fps": FPS, "frame_ms": round(FRAME_MS, 3),
               "frames": frames, "source": "val1527_int8w",
               "quantization": "per-channel symmetric INT8 weights (fake-quant), activations FP32"}
        (OUT / f"{seq}.json").write_text(json.dumps(rec, ensure_ascii=False), encoding="utf-8")
        print(f"  {seq:14s} frames={len(frames)}")

    (Path(__file__).resolve().parent / "out" / "quant_info.json").write_text(
        json.dumps(info, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"\n输出：{OUT}")
    print("下一步：python experiments/efo_val/run_val_experiment.py "
          f"--dir {OUT} --tag _int8w")


if __name__ == "__main__":
    main()
