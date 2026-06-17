# ERA:面向科学家的经验型软件协同写作 AI 系统(本地化分支)

[![arXiv](https://img.shields.io/badge/arXiv-2509.06503-b31b1b.svg)](https://arxiv.org/abs/2509.06503)
[![Project Page](https://img.shields.io/badge/Project%20Page-google--research.github.io%2Fera-blue)](https://google-research.github.io/era/)
[![License](https://img.shields.io/badge/license-Apache--2.0-green.svg)](./LICENSE)

> 本仓库(`localized_era`)是 [Google ERA](https://arxiv.org/abs/2509.06503) 的**本地化扩展分支**。
> 在上游 FUTS + LLM 方法的基础上,将该方法落地到**组合调度优化**领域,新增了三个独立的调度搜索应用。

---

## 目录

- [简介](#简介)
- [本仓库相对上游的区别](#本仓库相对上游的区别)
- [核心方法:Flat UCB Tree Search (FUTS)](#核心方法flat-ucb-tree-search-futs)
- [仓库结构](#仓库结构)
- [环境与依赖](#环境与依赖)
- [快速开始](#快速开始)
- [调度优化应用](#调度优化应用)
  - [`job_shop_era` —— 自由变异](#job_shop_era--自由变异)
  - [`exact_job_shop_era` —— CP-SAT 精确求解](#exact_job_shop_era--cp-sat-精确求解)
  - [`multi_bot_era` —— 多机器人调度](#multi_bot_era--多机器人调度)
  - [三者对比](#三者对比)
- [实验产物](#实验产物)
- [引用](#引用本工作)
- [许可证](#许可证)

---

## 简介

ERA(Empirical Research Assistant,经验型研究助手)是一个帮助科学家撰写高质量经验型软件的 AI 系统。它将大语言模型与一种树搜索算法 —— **Flat UCB Tree Search (FUTS)** —— 结合,迭代地**生成 → 执行 → 评分**候选程序,逐步收敛到专家级解。

论文原文:

> **[An AI system to help scientists write expert-level empirical software](https://arxiv.org/abs/2509.06503)**
> Aygün, et al., 2025

上游 ERA 面向科学任务(如流感预测、单细胞批次整合)。本分支则把同样的"代码即解、客观打分、树搜索迭代"范式,迁移到**作业车间调度 / 多机器人任务调度**这类 NP-hard 组合优化问题上:让 LLM 直接产出可运行的求解脚本,FUTS 用真实的目标值(makespan)驱动搜索。

---

## 本仓库相对上游的区别

| 维度 | 上游 ERA | 本分支 `localized_era` |
| --- | --- | --- |
| 任务域 | 经验科学(Kaggle 回归、流行病预测、单细胞) | 组合调度(job-shop、多机器人) |
| 解的形态 | 数据处理 notebook / 脚本 | 返回 `Schedule` 的求解器脚本 |
| 评分信号 | 测试集指标(RMSE、batch score 等) | `-makespan`(越低越好) |
| 求解范式 | 无约束 | 分自由变异 / 强制 CP-SAT 两套 |
| 新增模块 | — | `job_shop_era`、`exact_job_shop_era`、`multi_bot_era` |
| 保留模块 | FUTS 核心、`playground_s3e1.py`、notebooks | 同上,均保留 |

> 注:上游 README 提到的 `era_applications/` 目录不属于本分支;本分支的应用位于 `implementation/` 下的三个子包。

---

## 核心方法:Flat UCB Tree Search (FUTS)

`implementation/futs.py` 是论文 Algorithm 1 的通用单线程参考实现。`search` 函数只需调用方提供两个函数:

- **`generate_fn(problem, parent_solution, parent_score)`**:基于问题定义与一个父解,**生成一个新的(理想上更优的)候选解** —— 通常是渲染 prompt 喂给 LLM,再解析其输出。
- **`execute_fn(problem, solution)`**:把候选解放进**沙箱**执行,针对问题的度量返回一个**客观分数**。

`search` 会迭代 `num_iterations` 次,每次用 Flat UCB(PUCT)策略扩展一个搜索节点,最终返回找到的最优解。FUTS **最大化**分数,因此调度任务中统一用 `-makespan` 作为 score(makespan 越低 → 分数越高)。

FUTS 的完整实现见 `implementation/futs.py`(`futs_test.py` 为其单元测试)。

---

## 仓库结构

```
era/
├── implementation/                 # 全部可运行代码
│   ├── futs.py / futs_test.py      # FUTS 核心算法 + 测试
│   ├── llm.py                      # LLM 调用封装
│   ├── sandbox.py                  # 候选脚本执行沙箱
│   ├── playground_s3e1.py          # 原版端到端示例(Kaggle 回归)
│   ├── experiment_pipeline.ipynb   # 原版交互式实验
│   ├── data/                       # playground 数据
│   ├── notebooks/                  # 原版科学任务示例(流感预测 / 单细胞)
│   ├── job_shop_era/               # 【新增】自由变异 job-shop
│   ├── exact_job_shop_era/         # 【新增】CP-SAT 精确 job-shop
│   └── multi_bot_era/              # 【新增】多机器人调度
├── experiments/                    # 43 组实验产物(候选脚本/节点日志/图)
├── docs/                           # 实验可视化(_study.html / _diffs)
├── README.md  LICENSE  CONTRIBUTING.md
└── job_shop_lib_dataset_directory.txt
```

---

## 环境与依赖

- **Python 3.10+**
- 上游通用依赖:`pandas`、`numpy`、`scikit-learn`、`openai`
- 本分支调度应用额外依赖:
  - [`job-shop-lib`](https://pypi.org/project/job-shop-lib/) —— job-shop 基准实例与 `Schedule` 校验
  - [`ortools`](https://pypi.org/project/ortools/) —— CP-SAT 精确求解(`exact_job_shop_era`、`multi_bot_era`)
- 一个 OpenAI 兼容的 API Key

```bash
pip install pandas numpy scikit-learn openai job-shop-lib ortools
```

**LLM 配置**:各应用默认从 `~/.config/era/openai.env` 读取私有的 endpoint / key / model 设置(文件不入库)。也可用环境变量 `OPENAI_API_KEY`、`OPENAI_MODEL` 等覆盖。`--no-llm` 可在无 LLM 时跑通流程做 smoke test。

---

## 快速开始

### 1. 原版示例:Kaggle 回归(Playground S3E1)

```bash
cd implementation/
export OPENAI_API_KEY="your-api-key"
export OPENAI_MODEL="gpt-5.5"
python playground_s3e1.py
```

或用 Jupyter 打开 `experiment_pipeline.ipynb` 交互式跑完整流程。

### 2. 原版科学任务 notebooks

`implementation/notebooks/` 提供两个评测基准 notebook —— CDC 流感预测、单细胞批次整合,详见 [`notebooks/README.md`](./implementation/notebooks/README.md)。

### 3. 调度应用(本分支重点)

见下方[调度优化应用](#调度优化应用)。

---

## 调度优化应用

三个应用共享同一套 FUTS 接口与沙箱执行框架,差异在于**候选脚本的形态约束**与**问题数据接口**。

### `job_shop_era` —— 自由变异

最开放的 job-shop 代码搜索版本。每个 FUTS 节点生成**完整 Python solver 脚本**,算法形式不受限制(启发式、局部搜索、贪心、随机修复均可),只要能返回合法 `job_shop_lib.Schedule` 并通过 scorer 即可进入搜索树。

- 适配 `job_shop_lib` 标准基准(`ft06`、`ft10`、`taXX` 等)
- 候选脚本须定义 `def solve(instance): ... return schedule`
- `execute_fn` 在子进程沙箱执行,用 `Schedule.check_schedule` 校验可行性,返回 `-makespan`
- CLI 默认对 LLM **隐藏**基准参考最优值(避免 hard-code)

```bash
# 列出可用基准
python -m implementation.job_shop_era.cli --list-benchmarks

# 跑一个 FUTS 搜索
python -m implementation.job_shop_era.cli \
    --instance ft06 --mode futs --iterations 50 --timeout-seconds 30

# 无 LLM 冒烟测试
python -m implementation.job_shop_era.cli --instance ft06 --no-llm --iterations 1
```

主要参数:`--instance`、`--mode {single,bon,futs}`、`--iterations`、`--timeout-seconds`、`--no-llm`、`--early-stop-at-optimum`、`--include-reference-values-in-prompt`。

详见 [`job_shop_era/README.md`](./implementation/job_shop_era/README.md) 与 [`FULL_MUTATION_LOG.md`](./implementation/job_shop_era/FULL_MUTATION_LOG.md)。

---

### `exact_job_shop_era` —— CP-SAT 精确求解

把探索空间收束到**可复用的 CP-SAT 求解脚本**。prompt 明确要求用 OR-Tools CP-SAT 建模(变量、约束、hint、branching、repair、LNS 等),返回标准 `Schedule`。相比自由变异,它额外支持:

- **optimum 早停**:命中已知最优 makespan 即提前结束
- **runtime tie-breaker**:达到相同 makespan 后,以运行时间作为次级排序
- **结构化反馈**:把 parent / best / recent-failure 信息传给子节点(而非一句自然语言建议)
- **完整产物**:每个实验落盘 `best.py`、节点候选、`versions`、`manifest`,以及二维 / 三维甘特图

```bash
python -m implementation.exact_job_shop_era.cli \
    --instance ft06 --iterations 10 --c-puct 1.0 --timeout-seconds 30 \
    --early-stop-at-optimum
```

辅助工具:`audit_cli.py`(审计候选)、`plot_tree_cli.py`(搜索树可视化)、`cp_sat_solver.py`。

详见 [`FREE_MUTATION_COMPARISON.md`](./implementation/exact_job_shop_era/FREE_MUTATION_COMPARISON.md)。

---

### `multi_bot_era` —— 多机器人调度

面向实验室的**多机器人 / 多任务调度**数据(JSON / SQLite)。借鉴 `exact_job_shop_era` 的结构性约束:

- 候选脚本**必须使用 OR-Tools CP-SAT**
- 数据接口**只暴露问题实例**,不向候选脚本泄露"非固定任务"的已排好答案 —— 避免 FUTS 学到 replay
- scorer 只做**可行性与 makespan 验证**,不做主观代码质量判断
- prompt 向子节点传递父节点、best 节点、近期失败、score contract、代码摘要与 diff,让变异有可继承信息

```bash
# 用自定义数据集
python -m implementation.multi_bot_era.cli \
    --dataset /path/to/scheduling_benchmark.json \
    --mode futs --iterations 20 --c-puct 1.0 --timeout-seconds 30
```

主要参数:`--dataset`、`--mode {single,futs}`、`--iterations`、`--c-puct`、`--timeout-seconds`、`--no-llm`。

详见 [`IMPROVEMENT_LOG.md`](./implementation/multi_bot_era/IMPROVEMENT_LOG.md)。

---

### 三者对比

| 维度 | `job_shop_era` | `exact_job_shop_era` | `multi_bot_era` |
| --- | --- | --- | --- |
| 候选形态 | 任意 Python solver | solver,但 prompt 强制 CP-SAT | solver,强制 CP-SAT |
| 问题数据 | `job_shop_lib` 标准基准 | `job_shop_lib` 标准基准 | 实验室 JSON / SQLite |
| 输出对象 | 合法 `job_shop_lib.Schedule` | 同左 | 实验室 schedule 结构 |
| 优化目标 | makespan(可行即计) | makespan + runtime tie-break | makespan |
| 理论最优 | 不强制 bound | 支持 optimum 早停 | 防答案泄露、防 replay |
| 失败反馈 | 分数 / 错误 | parent/best/recent 结构化反馈 | parent/best/recent + diff |
| 产物 | best.py + 节点候选 | best.py/nodes/versions/manifest/图 | best.py + 节点候选 |

---

## 实验产物

- **`experiments/`**:43 组实验目录,涵盖各类 smoke test 与正式搜索(ft06/ft10、`taXX` 系列、multi-bot 多配置、CP-SAT vs 非 CP-SAT 对比等)。每组保留候选脚本、节点日志与可视化。
- **`docs/`**:以 `_study.html`(完整解的可视化页面)与 `_diffs/`(父子候选差异)形式组织的实验可视化,可在浏览器直接查看。

---

## 引用本工作

如使用了本仓库的代码或数据,请引用上游论文:

```bibtex
@misc{aygun2025aihelpscientistswrite,
      title={An AI system to help scientists write expert-level empirical software},
      author={Eser Aygün and Anastasiya Belyaeva and Gheorghe Comanici and Marc Coram and Hao Cui and Jake Garrison and Renee Johnston and Anton Kast and Cory Y. McLean and Peter Norgaard and Zahra Shamsi and David Smalling and James Thompson and Subhashini Venugopalan and Brian P. Williams and Chujun He and Sarah Martinson and Martyna Plomecka and Lai Wei and Yuchen Zhou and Qian-Ze Zhu and Matthew Abraham and Erica Brand and Anna Bulanova and Jeffrey A. Cardille and Chris Co and Scott Ellsworth and Grace Joseph and Malcolm Kane and Ryan Krueger and Johan Kartiwa and Dan Liebling and Jan-Matthis Lueckmann and Paul Raccuglia and Xuefei Wang and Katherine Chou and James Manyika and Yossi Matias and John C. Platt and Lizzie Dorfman and Shibl Mourad and Michael P. Brenner},
      year={2025},
      eprint={2509.06503},
      archivePrefix={arXiv},
      primaryClass={cs.AI},
      url={https://arxiv.org/abs/2509.06503}
}
```

## 许可证

Apache License 2.0,详见 [`LICENSE`](./LICENSE)。

> 本项目并非 Google 官方支持的产品(Not an officially supported Google product)。
