# Traitor_Agent

`Traitor_Agent` 是独立于主 fuzz 流程的 Rust 重写模块，使用独立配置 `Traitor_Agent/Traitorconfig.json`。

能力包括：

- Stage I：保守 trait 抽象重写
- Stage II：激进 trait 特性注入（GAT / specialization / RPIT / RPITIT / TAIT）
- 动态 few-shot（baseline + experience 池）
- 编译失败修复循环（默认最多 2 次）
- TSA 指标过滤（基于 rustc 输出 trait 相关行计数）

## 配置文件

默认读取 `Traitor_Agent/Traitorconfig.json`，重点字段：

- `paths.input_dataset`：输入数据集目录（默认 `seeds`）
- `paths.output_dir`：输出目录（默认 `Traitor_Agent/trait_dense_seeds`）
- `paths.summary_jsonl`：运行摘要 JSONL
- `runtime.*`：`shuffle/seed/skip_existing/max_cases`
- `llm.*`：Ollama 地址、模型和采样参数
- `traitor_agent.*`：repair/shot/pool/compile/TSA 参数
- `pool_builder.*`：从 `results` 逆向构建 pool 的参数

## 单文件运行

在 `trait-fuzzer` 根目录执行：

```bash
python Traitor_Agent/run_agent.py \
  --input seeds/some_seed.rs \
  --output Traitor_Agent/trait_dense_seeds/some_seed.rs \
  --config Traitor_Agent/Traitorconfig.json \
  --summary Traitor_Agent/trait_dense_seeds/some_seed.summary.json
```

## 数据集批处理

```bash
python Traitor_Agent/run_dataset.py --config Traitor_Agent/Traitorconfig.json
```

可选覆盖：`--max-cases`、`--input-dataset`、`--output-dir`。

## 构建 few-shot 样本池

从 `results/rustc` 与 `results/gccrs` 逆向提取 `before.rs/after.rs`：

```bash
python Traitor_Agent/build_pools.py --config Traitor_Agent/Traitorconfig.json
```

输出到 `Traitor_Agent/pools/`（推荐分层结构）：

- `stage1_baseline.jsonl`
- `stage1_experience.jsonl`
- `stage2_generic.jsonl`
- `stage2_gat.jsonl`
- `stage2_specialization.jsonl`
- `stage2_rpit.jsonl`
- `stage2_rpitit.jsonl`
- `stage2_tait.jsonl`

兼容旧结构：若上述文件不存在，会回退到 `baseline.jsonl` / `experience.jsonl`。

JSONL 每行格式：

```json
{"before":"<rust code>","after":"<rewritten rust code>"}
```

## 进程管理

提供根目录 `run_agent.sh`：

```bash
./run_agent.sh start    # ollama + dataset runner
./run_agent.sh watch    # 看状态与日志
./run_agent.sh kill     # 安全停止（仅允许目标用户）
```

`start` 支持可选模型参数，例如：

```bash
./run_agent.sh start qwen2.5-coder:14b
```
