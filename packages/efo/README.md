# efo — Event Fidelity Optimization

量化「检测 → 连续 k 帧确认 → 业务事件」这条流水线里，**帧级指标（mAP）看不见的事件级误差**，并给出校准解法。

## 它解决什么问题

模型部署/量化验收只看帧级指标（mAP、top-1、吞吐）。但质检、交通、安防、医疗的下游，
几乎都是「连续 k 帧确认 → 事件/告警」。帧级验收在数学上掩盖了三个系统性损失：

| 命题 | 闭式解 | 含义 |
|---|---|---|
| **结构性盲区** | `(k_in − 1) · Δt` | 短于此的事件必然漏检，与模型精度无关 |
| **指数放大** | `p ** k_in` | 单帧命中率 p 被 k 次幂放大；帧级掉 5% 可放大成事件级掉 16% |
| **滞留偏置** | `(m_out − k_in + 1) · Δt` | 时长被系统性高估，指标需校正再比较 |

`efo` 把这三条做成可复用、可证伪的工具：**测量 + 校准**，而不是又一个检测算法。

## 安装

```bash
pip install -e .
```

纯标准库，零第三方依赖，Python 3.9+。

## 快速上手

```python
from efo import generate_events, blind_zone_ms, corrected_dwell_ms, recalibrate_after_quant

# 1. 把逐帧检测收敛成事件
frames = [{"frame": i, "ts_ms": i * 66.67,
           "boxes": [{"conf": 0.9}] if 10 <= i < 40 else []} for i in range(50)]
events = generate_events(frames, conf=0.5, k_in=3, m_out=5)

# 2. 三命题
blind_zone_ms(3, 66.67)          # 133.3 ms：短于此必漏
corrected_dwell_ms(raw, 3, 5, 66.67)  # 校正滞留偏置

# 3. 量化感知重标定：量化后自动重选阈值，救回事件召回
r = recalibrate_after_quant(fp32_frames, int8_frames, conf_ref=0.5, k_in=3, m_out=5)
```

完整示例见 [`demo/run_demo.py`](demo/run_demo.py)。

## 模块

| 模块 | 职责 |
|---|---|
| `efo.events` | 通用事件化状态机 `generate_events` |
| `efo.metrics` | 事件级匹配 `match_events` / P·R·F1 / 时刻偏移 |
| `efo.laws` | 三命题闭式解 |
| `efo.calibrate` | 偏置校正 / 盲区感知参数建议 / 量化感知重标定 |

## 测试

```bash
python tests/run.py     # 纯 stdlib，无 pytest 也可
# 或
pytest tests/
```

## 诚实边界

- **不是新算法**：滞回状态机、阈值网格搜索都是成熟方法。
- **不是训练/推理框架**：它作用在"检测输出之后"，与任何模型、任何硬件无关。
- **价值在系统化**：把「事件级正确性」从散落在各处的经验，变成一组可复用、可测试、可引用的接口与定律。

## License

MIT
