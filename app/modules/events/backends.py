# -*- coding: utf-8 -*-
"""推理后端抽象：让"换后端"成为换一个类，而不是改调用点。

当前系统实际使用的是 **预生成结果**（`data/demo/json`），因为本机没有 DSA 设备；
`TorchBackend` 用于有 GPU 的机器上真跑模型；`AclBackend` 是昇腾入口的骨架，
**尚未在任何昇腾硬件上验证过**——材料中只能表述为"后端接口已预留"。

对齐关系（昇腾落地时要做的三件事）：
  1. 模型固化为 .om（ATC 或 MindSpore Lite），输入 shape 静态化
  2. 解码/缩放走 DVPP（VDEC + VPC），输出直接喂给模型输入
  3. 用 ACL 同步/异步接口替换 TorchBackend.infer 的实现
接口只有 infer_batch 一个方法，因此 3 是局部替换，不动调度与事件层。
"""
from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any, Iterable, Protocol, Sequence


class InferBackend(Protocol):
    name: str

    def infer_batch(self, payloads: Sequence[Any]) -> list[float]:
        """返回与输入一一对应的最大置信度。"""
        ...


class JsonBackend:
    """读预生成检测结果（系统默认通路）。

    payloads 为帧序号；结果取自 data/demo/json/<seq>.json 的 frames[].boxes。
    """

    name = "json"

    def __init__(self, seq: str, json_dir: Path):
        d = json.loads((Path(json_dir) / f"{seq}.json").read_text(encoding="utf-8"))
        self._frames = {f["frame"]: [b.get("conf", 0.0) for b in f.get("boxes", [])]
                        for f in d["frames"]}

    def infer_batch(self, payloads: Sequence[Any]) -> list[float]:
        out = []
        for p in payloads:
            confs = self._frames.get(int(p), [])
            out.append(max(confs) if confs else 0.0)
        return out


class TorchBackend:
    """ultralytics + torch（有 GPU 的机器上用）。惰性导入，缺依赖时给出明确指引。"""

    name = "torch"

    def __init__(self, weights: str | Path, device: str = "0", imgsz: int = 640):
        try:
            from ultralytics import YOLO
        except ImportError as e:  # pragma: no cover
            raise RuntimeError(
                "TorchBackend 需要 ultralytics：pip install ultralytics；"
                "无 GPU 环境请改用 JsonBackend") from e
        self._model = YOLO(str(weights))
        self._device, self._imgsz = device, imgsz

    def infer_batch(self, payloads: Sequence[Any]) -> list[float]:
        res = self._model.predict(list(payloads), imgsz=self._imgsz,
                                  conf=0.01, device=self._device, verbose=False)
        return [float(r.boxes.conf.max()) if (r.boxes is not None and len(r.boxes)) else 0.0
                for r in res]


class AclBackend:
    """昇腾 ACL 后端（骨架，未实现）。

    落地时要补的三步（都在这一个方法里，不影响调度与事件层）：
      1. pyACL 初始化 + 加载 .om 模型 + 申请输入/输出 dataset
      2. 输入来自 DVPP：VDEC 解出的 YUV 经 VPC 缩放到模型输入尺寸
      3. aclmdlExecute 后取输出，做 NMS，返回每帧最大置信度

    在此之前，`infer_batch` 会明确报错——**不要**在材料里声称已支持昇腾推理。
    """

    name = "acl"

    def __init__(self, om_path: str | Path | None = None, device_id: int = 0):
        self.om_path = om_path
        self.device_id = device_id

    def infer_batch(self, payloads: Sequence[Any]) -> list[float]:
        raise NotImplementedError(
            "AclBackend 尚未实现：需要 CANN 环境与 .om 模型。"
            "当前多路调度（app/modules/events/multichannel.py）已可用任意后端验证。")


_BACKENDS = {"json": JsonBackend, "torch": TorchBackend, "acl": AclBackend}


def get_backend(name: str | None = None, **kwargs) -> InferBackend:
    """按 INFER_BACKEND 环境变量或显式名称取后端；默认 json。"""
    key = (name or os.getenv("INFER_BACKEND") or "json").lower()
    if key not in _BACKENDS:
        raise ValueError(f"未知推理后端：{key}（可选 {', '.join(_BACKENDS)}）")
    return _BACKENDS[key](**kwargs)  # type: ignore[call-arg]
