# -*- coding: utf-8 -*-
"""采集抽象层（R13）

目的：把"影像从哪来"与"怎么推理"解耦。
现在只实现 FileSequenceSource；DICOM 与实时流留桩，接口先定死。

边界：桩就是桩，界面与材料只能说"预留"，不能说"已对接"。
"""
from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass
from pathlib import Path
from typing import Iterator, Optional


@dataclass(frozen=True)
class Frame:
    """统一帧结构，推理层只认这个，不关心来源。"""
    seq: str
    index: int
    ts_ms: float
    path: Optional[Path] = None
    ts_source: str = "sequence_index"   # device_clock / wall_clock / sequence_index / simulated


class FrameSource(ABC):
    """采集端口。"""

    name: str = "abstract"

    @abstractmethod
    def frames(self) -> Iterator[Frame]:
        ...

    def meta(self) -> dict:
        return {"source": self.name}


class FileSequenceSource(FrameSource):
    """离线图片序列（当前唯一实现）。

    时间来源：sequence_index（帧号 × 帧间隔），不是设备时间。
    """

    name = "file_sequence"

    def __init__(self, seq: str, root: Path, fps: float):
        self.seq = seq
        self.root = Path(root) / seq
        self.frame_ms = 1000.0 / fps
        if not self.root.is_dir():
            raise FileNotFoundError(f"序列目录不存在：{self.root}")
        self._files = sorted(self.root.glob("*.jpg")) or sorted(self.root.glob("*.png"))

    def frames(self) -> Iterator[Frame]:
        for i, p in enumerate(self._files):
            yield Frame(seq=self.seq, index=i, ts_ms=round(i * self.frame_ms, 2),
                        path=p, ts_source="sequence_index")

    def meta(self) -> dict:
        return {"source": self.name, "seq": self.seq,
                "total_frames": len(self._files),
                "frame_ms": round(self.frame_ms, 3),
                "ts_source": "sequence_index"}


class DicomSeriesSource(FrameSource):
    """DICOM 序列（桩）。

    真实实现应：查询 PACS → 取帧 → 用 AcquisitionDateTime 作 device_clock。
    """

    name = "dicom_series"

    def __init__(self, *_, **__):
        raise NotImplementedError(
            "DICOM 通路尚未实现：仅预留接口，材料中不得声称已对接 PACS")

    def frames(self) -> Iterator[Frame]:
        raise NotImplementedError


class LiveStreamSource(FrameSource):
    """实时视频流（桩）。

    真实实现应：SDI/采集卡 → RTSP → 逐帧回调，用采集卡打点作 wall_clock。
    这是唯一能支撑"术中实时预警"的通路（延迟 <100ms）。
    """

    name = "live_stream"

    def __init__(self, *_, **__):
        raise NotImplementedError(
            "实时通路尚未实现：仅预留接口，材料中不得声称已接入 DSA 视频")

    def frames(self) -> Iterator[Frame]:
        raise NotImplementedError
