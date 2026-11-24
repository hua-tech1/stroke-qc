# -*- coding: utf-8 -*-
"""昇腾边缘部署 · 容量模型（可验算，非实测）

目的：回答一个答辩必被问的问题——「导管室 2~4 台 DSA 同时开台，一块边缘卡够不够？」
方法：把公开规格与项目自身参数代入，算解码余量、推理余量、内存与带宽占用。

规格来源（华为官方文档，2026-11 核对）：
  Atlas 200I A2 加速模块 基本规格
  https://www.hiascend.com/doc_center/source/zh/Atlas%20200I%20A2/23.0.RC3/intro/userguide/userguide_013.html
    - 20TOPS 12GB/8GB/4GB：H.264/H.265 硬解 40 路 1080P@30fps；FP16 10 TFLOPS；INT8 20 TOPS
    - 8TOPS 4GB：H.264/H.265 硬解 20 路 1080P@30fps；FP16 4 TFLOPS；INT8 8 TOPS

项目参数（来自 app/core/config.py 与 data/demo/json）：
  fps = 15；分辨率 1024×1024（DSA 常见）；导管室 2~4 台同时开台。

诚实边界：
  - 本模型是**规格推算**，不是上机实测；单帧推理耗时取「公开经验区间」并显式标注。
  - 未涉及编码（本项目不上传影像，只上传事件时间戳）。
  - 未涉及 PCIe/DDR 竞争等二阶效应。

运行：python experiments/ascend/capacity_model.py
"""
from __future__ import annotations

import json
from pathlib import Path

OUT = Path(__file__).resolve().parent / "out"

# ---- 项目参数 ----
FPS = 15.0
W, H = 1024, 1024
CHANNELS = [2, 3, 4]              # 导管室同时开台路数
DEPTH = "yuv420"                  # 解码输出格式
BYTES_PER_PIXEL_YUV420 = 1.5

# ---- 官方规格 ----
BOARDS = {
    "Atlas 200I A2 20TOPS 12GB": {"decode_1080p30": 40, "fp16_tflops": 10.0, "int8_tops": 20.0},
    "Atlas 200I A2 20TOPS 8GB":  {"decode_1080p30": 40, "fp16_tflops": 10.0, "int8_tops": 20.0},
    "Atlas 200I A2 8TOPS 4GB":   {"decode_1080p30": 20, "fp16_tflops": 4.0,  "int8_tops": 8.0},
}

PIX_1080P30 = 1920 * 1080 * 30      # 一路 1080P@30fps 每秒像素数
# YOLOv8n @640 的公开经验单帧耗时区间（FP16，单路）；实际以自测为准
INFER_MS_RANGE = (7.0, 12.0)


def decode_demand_pxps(ch: int) -> float:
    return ch * FPS * W * H


def main() -> None:
    OUT.mkdir(parents=True, exist_ok=True)
    rows = []
    for name, spec in BOARDS.items():
        cap_pxps = spec["decode_1080p30"] * PIX_1080P30
        for ch in CHANNELS:
            need = decode_demand_pxps(ch)
            rows.append({
                "board": name,
                "channels": ch,
                "decode_capacity_1080p30": spec["decode_1080p30"],
                "demand_pxps": round(need / 1e6, 1),
                "capacity_pxps": round(cap_pxps / 1e6, 1),
                "decode_util_pct": round(100.0 * need / cap_pxps, 2),
                # 换算成"相当于几路 1080P@30fps"
                "equiv_1080p30": round(need / PIX_1080P30, 3),
            })

    # 推理：单帧耗时 -> 每秒可处理帧数 -> 可支撑路数
    infer = []
    for ms in INFER_MS_RANGE:
        fps_cap = 1000.0 / ms
        infer.append({
            "single_frame_ms": ms,
            "frames_per_sec_capacity": round(fps_cap, 1),
            "channels_supported_at_15fps": round(fps_cap / FPS, 1),
            "note": "仅推理；未计入前后处理与调度开销",
        })

    # 内存：解码缓冲（每路 4 帧双缓冲估算）
    mem = []
    for ch in CHANNELS:
        per_frame_mb = W * H * BYTES_PER_PIXEL_YUV420 / 1e6
        total = ch * 4 * per_frame_mb
        mem.append({"channels": ch, "frame_mb": round(per_frame_mb, 2),
                    "decode_buffer_mb": round(total, 1)})

    # 带宽：未压缩原始帧流入内存的速率
    bw = []
    for ch in CHANNELS:
        bps = ch * FPS * W * H * BYTES_PER_PIXEL_YUV420
        bw.append({"channels": ch, "raw_in_mbps": round(bps * 8 / 1e6, 1)})

    summary = {
        "project_params": {"fps": FPS, "resolution": f"{W}x{H}", "channels": CHANNELS},
        "spec_source": "Atlas 200I A2 基本规格（华为官方文档）",
        "decode": rows, "inference": infer, "memory": mem, "bandwidth": bw,
        "method": "规格推算，非上机实测",
    }
    (OUT / "capacity_model.json").write_text(
        json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8")

    L = ["# 昇腾边缘部署 · 容量模型（规格推算，非实测）\n",
         "配置：DSA %d×%d、%g fps、导管室同时开台 2~4 路。" % (W, H, FPS),
         "规格来源：Atlas 200I A2 基本规格（华为官方文档，2026-11 核对）。\n",
         "## 一、解码余量（DVPP 硬解）\n",
         "| 板卡 | 硬解能力 | 同时路数 | 需求 (MP/s) | 能力 (MP/s) | 占用率 | 等效 1080P@30fps |",
         "|---|---:|---:|---:|---:|---:|---:|"]
    for r in rows:
        L.append(f"| {r['board']} | {r['decode_capacity_1080p30']} 路 1080P@30 | {r['channels']} | "
                 f"{r['demand_pxps']} | {r['capacity_pxps']} | **{r['decode_util_pct']}%** | "
                 f"{r['equiv_1080p30']} 路 |")
    L += ["",
          "**结论**：4 路 1024²@15fps 的解码需求约等于 1 路 1080P@30fps，"
          "占一块 20TOPS 模块（40 路）的 **2.5%**。低配 8TOPS 模块（20 路）也只占 5%。",
          "→ 解码不是瓶颈；真正的瓶颈在「多路异步的调度与保序」，这正是 EFO 硬件扩展要处理的问题。",
          "",
          "## 二、推理余量（YOLOv8n FP16）\n",
          "| 单帧耗时 (ms) | 吞吐 (帧/s) | 可支撑路数 @15fps |",
          "|---:|---:|---:|"]
    for i in infer:
        L.append(f"| {i['single_frame_ms']} | {i['frames_per_sec_capacity']} | "
                 f"{i['channels_supported_at_15fps']} |")
    L += ["",
          "单帧耗时取公开经验区间（7~12 ms），**不是本项目实测值**。"
          "按最保守 12 ms 计，仍可支撑 5.5 路 @15fps；4 路有余量。",
          "",
          "## 三、内存与带宽\n",
          "| 路数 | 单帧 (MB, YUV420) | 解码缓冲 (MB, 4 帧/路) | 原始帧流入 (Mbps) |",
          "|---:|---:|---:|---:|"]
    bmap = {b["channels"]: b for b in bw}
    for m in mem:
        L.append(f"| {m['channels']} | {m['frame_mb']} | {m['decode_buffer_mb']} | "
                 f"{bmap[m['channels']]['raw_in_mbps']} |")
    L += ["",
          "12GB LPDDR4X 模块下，解码缓冲占用量级为几十 MB，可忽略。",
          "",
          "## 四、本模型没有测什么（必须写在材料里）\n",
          "- 没有在 Atlas 硬件上跑过：单帧耗时是区间引用，不是实测。",
          "- 没有测多路并发下的 p99 时延（需要真机 + 多路码流）。",
          "- 没有测 DVPP 与 AI Core 的实际竞争（理论上独立单元，实测需硬件）。",
          "- 编码能力未涉及：本项目只上传事件时间戳，不上传影像。",
          "",
          "结论一句话：**解码能力有 40 倍余量，所以昇腾的价值不在「解码快」，"
          "而在「多路同时接入不挤占 AI Core 与 CPU」——但这也意味着，"
          "多路一开，帧的到达顺序与间隔不再由我们控制，事件级正确性必须另有保证。**"]

    (OUT / "capacity_model.md").write_text("\n".join(L), encoding="utf-8")
    print("\n".join(L[:20]))
    print(f"\n输出：{OUT}")


if __name__ == "__main__":
    main()
