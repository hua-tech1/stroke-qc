# 实验索引

四个目录，一个原则：**所有实验与系统共用同一份状态机实现**（`packages/efo/efo/events.py`），
不复制一份——否则「实验里测的」与「线上跑的」不是同一个东西，结论不可信。

| 目录 | 回答什么问题 | 依赖 | 需不需要 GPU |
| :--- | :--- | :--- | :--- |
| `efo/` | 「连续 k 帧确认」这个判据自带哪些系统性误差？ | 纯标准库 | 否 |
| `efo_val/` | 在 1527 帧真实标注上，事件级到底对不对？ | ultralytics + torch | 是（CPU 也能跑，慢） |
| `int8/` | 权重量化会不会毁掉事件级指标？ | ultralytics + torch | 是 |
| `ascend/` | 一块昇腾卡够不够接管一个导管室？ | 纯标准库 | 否 |

## 数据流向

```
data/guidewire_yolo/images/val (1527 帧)
        │  efo_val/export_detections.py        ← GPU 推理，导出逐帧置信度
        ▼
efo_val/out/detections/*.json                  ← EFO 数据契约（含 gt_hit）
        │  efo_val/run_val_experiment.py       ← 事件级评估
        ▼
efo_val/out/val_event_level.{json,md}

int8/weight_int8.py  ──► int8/out/detections_int8w/*.json
        └──► efo_val/run_val_experiment.py --dir ... --tag _int8w
```

## 逐条复现

```bash
# 1) 三命题（零依赖）
python -m experiments.efo.run_all

# 2) 1527 帧导出 + 事件级评估（需 CUDA 版 torch）
python experiments/efo_val/export_detections.py --weights runs/baseline/weights/best.pt --device 0
python experiments/efo_val/run_val_experiment.py

# 3) INT8 权重量化对照
python experiments/int8/weight_int8.py --weights runs/baseline/weights/best.pt --device 0
python experiments/efo_val/run_val_experiment.py \
    --dir experiments/int8/out/detections_int8w --tag _int8w

# 4) 昇腾容量模型（零依赖）
python experiments/ascend/capacity_model.py
```

## 写材料时不能越过的边界

1. **P1 / P3 是解析结论**，由定义直接推出，实验只是验证实现与结论一致。不要表述为「实验发现」。
2. **P2 的实验部分是注入噪声模型**，不等于真实 INT8 量化。
3. **INT8 那组是权重量化（per-channel fake-quant），激活仍为 FP32**，不是完整 INT8 推理；
   实测结果为「跨阈值 0 帧、事件级不变」——这恰好说明崩坏源于**分布漂移跨阈值**，而非权重误差。
4. **1527 帧验证集全部为「导丝在场」帧**，无空帧：盲区、离画、闭合滞留不可在真实标注上验证。
5. **昇腾容量模型是规格推算**，不是上机实测；单帧推理耗时取经验区间。
6. 演示序列来自公开数据集（许可为 null），**不能**据此下任何临床有效性结论。
