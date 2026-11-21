# -*- coding: utf-8 -*-
"""生成占位帧图片（data/demo/frames/）。

真实 DSA 导丝影像为授权数据、不入库；这里按检测 JSON 的 total_frames 生成
暗色占位帧，使术中监控页可渲染、帧条/事件流/自检卡/量化面板可演示。
检测框由前端 SVG 叠加，不依赖图片内容。
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

from PIL import Image

ROOT = Path(__file__).resolve().parents[1]
JSON_DIR = ROOT / "data" / "demo" / "json"
FRAME_DIR = ROOT / "data" / "demo" / "frames"
SIZE = (512, 512)


def main() -> int:
    n_total = 0
    for jf in sorted(JSON_DIR.glob("*.json")):
        det = json.loads(jf.read_text(encoding="utf-8"))
        seq = det["seq"]
        total = det["total_frames"]
        seq_dir = FRAME_DIR / seq
        seq_dir.mkdir(parents=True, exist_ok=True)
        for i in range(total):
            p = seq_dir / f"{i:04d}.jpg"
            if not p.exists():
                # 暗色占位（接近透视背景的深灰），不包含任何真实解剖信息
                Image.new("RGB", SIZE, (26, 26, 28)).save(p, "JPEG", quality=85)
        n_total += total
        print(f"  {seq}: {total} 帧 -> {seq_dir}")
    print(f"共生成 {n_total} 帧占位图 -> {FRAME_DIR}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
