# 证据包索引（网评用）

> 一张表回答评委最想问的：「你说的这些，我能不能核？」
> 等级：**L3 留痕**（截图/录屏/账单）＞ **L2 可复现**（代码+脚本+输出）＞ **L1 测算**（公式+参数+来源）＞ **L0 声称**（仅文字）

> 所有数字的**唯一出处**见 [NUMBERS.md](NUMBERS.md)：22 项指标、模型指标、实验数字、市场口径与旧值黑名单，均在其中。

## 一、赛题硬门槛 → 证据对照

| 门槛 | 现状 | 证据位置 | 等级 | 材料里应怎么写 |
|---|---|---|---|---|
| ① 华为云 CodeArts 开发 | 未留痕 | — | L0 | 「AI 编码辅助开发」；**不要说「全链路 CodeArts」** |
| ② 关联 RDS / Redis | 本地已跑通（PG16+Redis7） | `docker-compose.dev.yml`、`migrations/`、`app/core/db.py` | L2 | 「本地同构跑通，云端迁移步骤见附录」 |
| ③ 华为云部署 | 未执行 | `deploy/RUNBOOK.md`（步骤已就绪） | L0 | 执行 Runbook 后升 L3，见 §0 八项证据 |
| ④ 开源 | **已公开**：`github.com/hua-tech1/stroke-qc`（83 文件 / 0.23MB，2026-11-21 快照） | 远端仓库 | **L3** | 「已开源；本地新增 `experiments/`、`deploy/`、`EVIDENCE.md` 待同步」 |
| 昇腾 DVPP 多路 | 设计路线 + 容量测算 | `experiments/ascend/out/capacity_model.md` | **L1** | 「规格推算，未上机」 |
| **多路并发管线** | **已进系统侧**：`app/modules/events/multichannel.py` + 实测 | `experiments/ascend_multichannel/`、`scripts/check_multichannel.py` | **L2** | 「多路调度已进系统，`check_multichannel.py` 1 秒可复现；解码为内存帧替代 DVPP」 |
| 推理后端可替换 | `JsonBackend` / `TorchBackend` / `AclBackend` 同接口 | `app/modules/events/backends.py` | L2（接口）/ L0（昇腾） | 「后端接口已预留；昇腾后端**未实现**」 |
| 昇腾抖动 / 乱序 | 仿真验证 | `experiments/efo/out/`、`packages/efo/jitter.py`、`reorder.py` | L2 | 「仿真，非 DVPP 实测」 |

## 二、EFO 创新点的证据（本次新增）

| 结论 | 数字 | 证据 | 等级 |
|---|---|---|---|
| 真实验证集事件级 F1 | **0.9333**（P 0.875 / R 1.0） | `experiments/efo_val/out/val_event_level.md` | L2 |
| 序列级完全正确率 | **14 / 15** 序列 | 同上 | L2 |
| 真实数据验证确认延迟 | 中位 **2 帧 = 133.3 ms**，与 (k_in−1)·Δt 完全一致 | 同上 | L2 |
| 帧级不差、事件级错 | `4_ST0_SE23`：逐帧命中 0.80，却被拆成 **2 次入画 + 1 次伪离画** | 同上 | L2 |
| INT8 权重量化（per-channel） | 逐帧 \|Δconf\| 均值 **0.0013** / p99 **0.0191** / 最大 0.0614；**跨阈值帧 0**；事件级指标**完全不变** | `experiments/int8/out/` | L2 |
| 4 路 DSA 解码占用 | 一块 20TOPS 模块（40 路 1080P@30）的 **2.53%** | `experiments/ascend/out/capacity_model.md` | L1 |
| 多路推理容量（本机） | batch 4 时单帧等效 **14.82 ms**，容量 **67.5 fps**，可支撑 **4.5 路@15fps**（4 路负载 88.9%） | `experiments/ascend_multichannel/out/capacity.json` | L2 |
| 多路并发不破坏事件 | 4 路实时：丢帧 0，事件与基准 **4/4 一致**（两次独立运行一致） | `experiments/ascend_multichannel/out/realtime_on.json` | L2 |
| **乱序破坏、保序恢复** | 乱序 p=0.3、4 路：无保序 **1/4** 正确；有保序 **4/4** 正确（**两次独立运行完全一致**） | `experiments/ascend_multichannel/out/reorder_{off,on}.json` | L2 |
| 时延（仅记录） | 4 路 p99 单次 160–432 ms，**波动一个数量级，不作结论** | 同上 | L1 |

## 三、由新证据引出的三处口径修正（必须改）

1. **页 7 的「20 路 1080P@30fps」是错的**。官方规格：20TOPS 模块 **40 路**，8TOPS 模块 20 路。
   改成「Atlas 200I A2 20TOPS 12GB，硬解 40 路 1080P@30fps；4 路 DSA 只用 2.53%」——更从容且可查。
2. **页 10 的「判定余量 0.0082」必须限定为 FP16 前提**。INT8 权重量化的 p99 漂移是 **0.0191**，
   已经大于 0.0082。不限定就等于说「量化也安全」，会被一句问倒。
3. **页 15 的量化示例必须标注为「机制演示」**。真实权重量化 0 帧跨阈值、事件级不变，
   说明崩坏发生在「分布漂移跨过阈值」而非权重误差。把这个讲清楚，比原来的夸张例子更有说服力。

## 四、数据边界（写进材料是加分，不是自曝）

- 验证集 1527 帧**全部为「导丝在场」帧**，无空帧 → 盲区、离画、闭合滞留**无法在真实标注上验证**，
  只能靠合成序列（`experiments/efo` exp1/exp3）。这一条必须写明。
- 600 例队列为仿真数据（种子 42 可复现），非真实患者。
- 演示影像来自公开数据集，许可为 null，不进仓库、不随作品分发。

## 五、复现命令

```bash
# 1) 导出 1527 帧检测（需 CUDA 版 torch + ultralytics）
python experiments/efo_val/export_detections.py --weights <best.pt> --device 0
# 2) 事件级评估
python experiments/efo_val/run_val_experiment.py
# 3) INT8 权重量化对照
python experiments/int8/weight_int8.py --weights <best.pt> --device 0
python experiments/efo_val/run_val_experiment.py --dir experiments/int8/out/detections_int8w --tag _int8w
# 4) 昇腾容量模型（零依赖，无硬件也可跑）
python experiments/ascend/capacity_model.py
# 5) EFO 三命题（原有）
python -m experiments.efo.run_all
```
