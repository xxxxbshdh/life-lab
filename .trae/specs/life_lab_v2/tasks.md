# Life Lab v2 - 任务拆分

**对应 AC 总览**: AC-1 到 AC-10

## 依赖图(从上到下)
```
Task 1 基础公共库 (numpy/requests 安装 + 公共数据类型)
 ├── Task 2 基因与量子启发算子 (FR-2, FR-8)
 ├── Task 3 神经进化大脑 (FR-1, FR-8)
 ├── Task 4 视觉皮层 VisionCortex (FR-5, FR-6 依赖)
 ├── Task 5 LLM 客户端 + 离线降级 (FR-3, FR-6 依赖)
 ├── Task 6 浏览器学习 + 知识库 RAG (FR-7, FR-6 依赖)
 ├── Task 7 升级 life_agent: 接入 NN 大脑
 ├── Task 8 升级 mode_ecosystem: 基因遗传 + 小龙虾
 ├── Task 9 升级 mode_pet: 接入 LLM
 ├── Task 10 新建 mode_manager: 统一面板 + 指令调度 (FR-6)
 └── Task 11 更新 life_lab 主菜单(模式 5) + 状态持久化
```

---

## Task 1: 基础依赖安装 + 公共类型模块 (AC-1 前置)

**覆盖 AC**: (所有 AC 前置依赖)

### 说明
- pip 安装 numpy + requests;
- 新建 `core_types.py`,放所有跨模块公共类型:
  - `Gene` (dataclass,5维traits + 3维颜色);
  - `EntityKind` Enum(AGENT, BOID, HERB, PRED, CRAYFISH, PLANT);
  - `WorldEntity` (id, kind, pos, energy 基类,可选 gene_id);
  - `InstructionIntent` Enum(SPAWN_PLANTS, RESET_AGENT, PET_SEND_MSG, ECO_ADJUST, STUDY_URL, FREE_TEXT)
  - `ParsedInstruction` (intent: InstructionIntent, payload: dict)
- 新建 `quantum_ops.py`:放量子启发函数:
  - `sample_from_softmax(probs: list[float]) -> int` — 按概率采样(叠加坍缩);
  - `tunnel_mutate(value: float, prob=0.001) -> float, bool` — 隧穿(返回新值和是否触发);
  - `crossover(a: list[float], b: list[float]) -> list[float]` — 均匀交叉。

### 测试要求 (TR)
| ID | 类型 | 内容 |
|----|------|------|
| T1-TR1 | rule | `pip list | grep -E 'numpy|requests'` 两者均出现 |
| T1-TR2 | rule | `from core_types import Gene, WorldEntity, ParsedInstruction` 无报错 |
| T1-TR3 | rule | `quantum_ops.sample_from_softmax([0.1, 0.8, 0.1])` 多次执行后 1 占比 ≈ 80%(跑 1000 次,在 [0.7,0.9] 区间内) |
| T1-TR4 | rule | `quantum_ops.tunnel_mutate` 在 1 万次调用中触发次数 ∈ [5, 25] (prob=0.001, 容错 +/− 1.5 倍) |

**状态**: pending
**完成证据**: (待填)

---

## Task 2: 基因遗传算子 (FR-2, FR-8)

**覆盖 AC**: AC-4, AC-10

### 说明
- 在 `gene_ops.py`(可放到 core_types 或独立文件,但推荐独立):
  - `random_gene() -> Gene`:5 个 trait 均匀采样 [0,1],颜色随机;
  - `gene_to_phenotype(gene: Gene) -> Phenotype`:Phenotype = dataclass(speed, vision_radius, aggression, reproduce_threshold, metabolism, color_rgb);
  - `reproduce(parent_a: Gene, parent_b: Gene, mutate_rate=0.05, tunnel_rate=0.001) -> Gene`:交叉 + 每位置高斯突变 + 隧穿;
  - 全局计数器 `TUNNEL_COUNTER` 每次触发 +1,提供 `tunnel_stats() -> dict` 给控制台打印。
- 每 500 tick 的统计由主循环统一调用(在 Task 11 接入),这里只提供接口。

### 测试要求
| ID | 类型 | 内容 |
|----|------|------|
| T2-TR1 | rule | `reproduce(Gene(a..), Gene(b..))` 子代每个 trait ∈ [0, 1] |
| T2-TR2 | rule | `gene_to_phenotype` 后 speed ∈ [1.0, 4.0]、vision ∈ [50, 250]、颜色 RGB ∈ [0, 255] |
| T2-TR3 | rule | 连续 1 万次 reproduce,`TUNNEL_COUNTER` ∈ [5, 25] |

**状态**: pending
**完成证据**: (待填)

---

## Task 3: 神经进化大脑 (FR-1, FR-8)

**覆盖 AC**: AC-2, AC-3

### 说明
- 新建 `neural_brain.py`:
  - `class NeuralBrain`:
    - 8-16-4 MLP (8 输入:energy、hunger、mood_code、food_angle_sin、food_angle_cos、food_dist_norm、threat_angle_cos、threat_angle_sin;16 隐藏 tanh;4 输出 softmax)
    - `forward(obs: list[float]) -> list[float]` 返回 softmax 分布;
    - `genome_size()` 属性(权值+偏置总数,大约 8*16+16+16*4+4 = 212);
    - `to_flat() -> list[float]`、`from_flat(arr)` 序列化/反序列化权重;
    - `mutate(rate=0.03, tunnel_rate=0.001)` 直接原位变;
    - `crossover(other: NeuralBrain) -> NeuralBrain`(flat 后均匀交叉,再重建)。
- 量子启发决策:`decision = quantum_ops.sample_from_softmax(forward(obs))`(采样,不 argmax)。

### 测试要求
| ID | 类型 | 内容 |
|----|------|------|
| T3-TR1 | rule | `NeuralBrain().forward([0]*8)` 返回 4 维数组,和为 1.0 ± 0.001 |
| T3-TR2 | rule | `to_flat() → len == 212`;`from_flat(flat)` 后 forward 输出等价 |
| T3-TR3 | rule | `mutate` 10 次相同 brain,最终输出分布两两不同(已发生变化) |
| T3-TR4 | rubric | NN 决策表现:饥饿时(obs 高 hunger+低 energy)输出 softmax 的觅食动作 > 0.4 (0-5 分,观察值≥0.4 时记 5 分) |

**状态**: pending
**完成证据**: (待填)

---

## Task 4: 视觉皮层 (FR-5)

**覆盖 AC**: AC-6

### 说明
- 新建 `vision_cortex.py`:
  - `class VisionCortex(grid_size=16)`:
    - `render(entities: list[WorldEntity]) -> VisonFrame`:
      - VisionFrame = dataclass(density: dict[Kind, list[list[int]]], energy_heat: list[list[float]], attention: list[list[float]])
      - 每种物种一个 N×N 计数矩阵;
      - 能量矩阵每格累加所有 entity.energy;
      - attention = 距离 manager_pos(构造时传)的反距离归一化。
    - `summarize(frame: VisionFrame, topk=5) -> str`:输出中文摘要(如"绿色植物在区域 8:8 最密集,捕食者在右下角聚集")。

### 测试要求
| ID | 类型 | 内容 |
|----|------|------|
| T4-TR1 | rule | 构造 100 个均匀分布 + 20 个集中在右上的实体,render 后右上区域对应 count > 左上 count × 2 |
| T4-TR2 | rule | density 矩阵每个通道尺寸 = grid_size × grid_size(如 16×16) |
| T4-TR3 | rubric | summarize() 文本长度 ≥ 30 且包含 1 个"密集/聚集"之类的关键词 (0-5 分 ≥3) |

**状态**: pending
**完成证据**: (待填)

---

## Task 5: LLM 客户端 + 离线降级 (FR-3)

**覆盖 AC**: AC-5

### 说明
- 新建 `llm_client.py`:
  - `load_config() -> LLMConfig | None`:从同目录 `llm_config.json` 读取(base_url、api_key、model),缺字段/文件不存在返回 None;
  - `LLMClient(config)`:
    - `chat(system_prompt: str, user_message: str, context: list[str] | None = None, temperature=0.7) -> str`: 发起 OpenAI 兼容 `/chat/completions` POST;
    - 超时 10 秒,异常返回 `"__OFFLINE__"`。
  - 工具函数 `llm_chat_or_fallback(system, user, context, fallback_fn) -> str, online:bool`:自动选择 LLM 或 fallback 规则函数,返回结果和是否在线。
- 新建 `llm_config.example.json`(只给模板,不填真实 key)。

### 测试要求
| ID | 类型 | 内容 |
|----|------|------|
| T5-TR1 | rule | 无 llm_config.json 时 load_config 返回 None,不抛异常 |
| T5-TR2 | rule | `llm_chat_or_fallback(..., fallback_fn=lambda *_: "离线回复")` 在 load_config=None 时返回 ("离线回复", False) |
| T5-TR3 | rule | HTTP 调用目标 URL 不存在(断网或模拟失败)时,也能正常走 offline 分支(不抛未捕获异常) |

**状态**: pending
**完成证据**: (待填)

---

## Task 6: 浏览器学习 + RAG 知识库 (FR-7)

**覆盖 AC**: AC-8

### 说明
- 新建 `browser_study.py`:
  - `class KnowledgeBase(path="knowledge.jsonl")`:
    - `add(text: str)`:切片(每 200 字切片,overlap=50),每片 TF-IDF top-10 关键词(用 jieba 分词如果能装,否则用中文标点+空格分词 fallback),存为 jsonl。
    - `retrieve(query: str, topk=3) -> list[str]`:Jaccard 相似度(query词 vs 切片关键词),返回 topk。
    - `count() -> int` 切片数。
  - `async_study_url(url: str)` —— **这里有环境边界**:
    - 如果运行在 Trae 内,走 browser_use;否则(纯 python 直接运行)提供 `study_text(url, text)` 入口让用户粘贴文本,或 `study_file(path)` 读取本地 txt/md。
    - 返回摘要字符串。
- 提供 `study_cli.py` 命令行入口。

### 测试要求
| ID | 类型 | 内容 |
|----|------|------|
| T6-TR1 | rule | `KnowledgeBase.add("Python 是一种解释型语言,支持函数式编程") × 3` 后 `count()` ≥ 1 且 retrieve("Python 语言") 首条含 "Python" |
| T6-TR2 | rule | knowledge.jsonl 写入后重新加载能读出相同 count |
| T6-TR3 | rule | `study_text(url="test", text="Hello" * 1000)` 调用后 count() 增加 |

**状态**: pending
**完成证据**: (待填)

---

## Task 7: 升级 life_agent.py → 神经进化

**覆盖 AC**: AC-2, AC-3

### 说明
- `Agent.think()` 从规则改为:
  1. 构造 8 维 obs(energy/100, hunger/100, mood={-1,0,1}, food_angle_sin/cos, food_dist/vision_radius, threat_angle_sin/cos);
  2. 调用 `self.brain.forward(obs) → probs`;
  3. `action_idx = sample_from_softmax(probs) → Action enum`;
- Agent 持有 `self.brain = NeuralBrain()`;
- Agent 持有 `self.gene = random_gene()`(视觉、速度、代谢用 FR-2 映射);
- 全局 `EVOLUTION_COUNTER`、按 R 新建 Agent 不重置统计;
- 按 E(进化)键:挑当前 Agent(或死亡前 Top Agent)做 `crossover(second_best)` → 产生新 Agent,控制台打印"继承 + 突变位 N,是否隧穿:Y/N";
- 保留原 HUD 风格,加上"NN 输出分布"4 条动作概率条、基因型摘要。

### 测试要求
| ID | 类型 | 内容 |
|----|------|------|
| T7-TR1 | rule | 进入 Agent 模式,不操作,运行 10s 不崩溃,能量/饥饿自然变化,动作随时间切换 |
| T7-TR2 | rule | 人工构造 hunger=90,energy=20 状态,softmax 的觅食动作概率 > 0.4 (HUD 可见) |
| T7-TR3 | rule | 按 E 后控制台输出包含"继承""突变位""隧穿"三个关键词 |
| T7-TR4 | rule | ESC 返回菜单,再进入,计数器和进化统计不清空(主循环保存) |

**状态**: pending
**完成证据**: (待填)

---

## Task 8: 升级 mode_ecosystem.py → 基因遗传 + 小龙虾

**覆盖 AC**: AC-4, AC-10

### 说明
- Animal 新增 `gene: Gene` 字段、`phenotype: Phenotype`;
- speed / vision / aggression / reproduce_thr 从 phenotype 读取;动物颜色从 phenotype.color_rgb 读取;
- 幼崽继承 `reproduce(parent_a.gene, parent_b.gene)`;
- 新增 Crayfish 类:
  - kind = CRAYFISH;
  - 8 方向触须:`antenna_distances = [d for angle in 0..315 at step 45]`,每 tick 更新(射线与最近实体/边界的距离);
  - 运动:冲刺/滑行阶段计数,phase 切换;
  - HUD 可视化:画 8 条小线(触须)从身体向外,长度=距离/最大距;
  - 食性:优先吃 plant,如果 hungry>70 且看到 herb 幼体(size<5)则攻击。
- 每 500 tick:控制台 `tunnel_stats() + 各物种基因均值`。

### 测试要求
| ID | 类型 | 内容 |
|----|------|------|
| T8-TR1 | rule | 启动生态模式,出现 3 种物种:食草(褐)、捕食(红)、小龙虾(橙/带触须小标记),数量 ≥1 |
| T8-TR2 | rule | 任一幼崽的颜色不等于纯父亲颜色(已发生交叉 + 突变,概率几乎 1) |
| T8-TR3 | rule | 连续运行 ≥2 分钟,任何一种物种数量未恒定(至少 ±2 变化) |
| T8-TR4 | rule | 500 tick 统计输出出现在控制台 |

**状态**: pending
**完成证据**: (待填)

---

## Task 9: 升级 mode_pet.py → LLM + 状态持久化

**覆盖 AC**: AC-5, AC-9

### 说明
- respond() 重写:
  - 构造 system_prompt = `"你是一只可爱的数字宠物,名字叫{name}。当前情绪:{mood},饥饿度:{hunger},好感度:{affection}。你需要用简短可爱的中文回复用户..."`;
  - user_message = 输入文本;
  - context = retrieve(query=输入, topk=3) 知识增强;
  - 用 `llm_chat_or_fallback(..., fallback=原规则 respond)` 取得回复。
- 状态持久化:每 10 秒或关闭前 `json.dump(pet.__dict__, ...)`,启动时从 `pet_state.json` 恢复,文件不存在用默认。
- 保留原界面,加一行"在线:Y/N" 状态显示。

### 测试要求
| ID | 类型 | 内容 |
|----|------|------|
| T9-TR1 | rule | 无 LLM 配置 → "在线:N",对话不崩溃,规则回复正常 |
| T9-TR2 | rule | 关闭再重启后,好感度误差 ≤ 1(恢复成功) |
| T9-TR3 | rule | 知识库中已加入关于"Python"的知识后,输入"你知道 Python 吗",回复包含知识片段关键词(如"解释型""编程") |

**状态**: pending
**完成证据**: (待填)

---

## Task 10: 新建 mode_manager.py 中央管理面板 (FR-6)

**覆盖 AC**: AC-6, AC-7, AC-9

### 说明
- mode_manager 分为三栏 pygame UI:
  - 左栏:4 个子系统实时卡:
    1. Agent:存活、能量均值、最强基因;
    2. 生态:三物种数、植物数;
    3. Boids:数量;
    4. 宠物:情绪、饥饿、好感、在线状态;
  - 右栏:与 Manager 的对话输入框(回车发送);
  - 底栏:VisionCortex 文字摘要区(每 120 tick 刷新,或点"刷新"按钮)、"学习网页 URL"输入框。
- 中央**意图解析器**:
  - 用户输入文本 → LLM (或离线规则关键词) 解析为 `ParsedInstruction`;
  - 调度器根据 intent 执行:SPAWN_PLANTS → `ecosystem_ref.spawn_food(n)`、PET_SEND_MSG → 往宠物对话栈插入、STUDY_URL → 调用 `async_study_url`、FREE_TEXT → 直接对话回复。
- Manager 自身状态持久化到 `manager_state.json`(记忆 + 好感度 + 学习过的 URL 列表)。
- 为了 Manager 能拿到其它模式的引用,主程序在 menu 层维护 `WorldContext`(一个 dataclass,含 ecosystem/agent/pet/boids 的当前活跃实例指针)。

### 测试要求
| ID | 类型 | 内容 |
|----|------|------|
| T10-TR1 | rule | Manager 面板正常显示 4 张子卡,不空白 |
| T10-TR2 | rule | 发送"在生态系统投放 5 株植物"→ 解析为 SPAWN_PLANTS,随后进入生态模式植物数净增 ≥ 3 |
| T10-TR3 | rule | 发送"告诉对话宠物我回来了"→ 解析为 PET_SEND_MSG,进入宠物模式对话日志包含该消息 |
| T10-TR4 | rule | 发送"学习 https://python.org" → knowledge.jsonl 行数增加(无需 browser 真正跑通,走 study_text 模拟也视为通过) |
| T10-TR5 | rule | 关闭重启 Manager,保留"学过的 URL 列表" |

**状态**: pending
**完成证据**: (待填)

---

## Task 11: life_lab 主菜单升级 + 世界上下文 + 统计打印

**覆盖 AC**: AC-1, AC-9, AC-10

### 说明
- 主菜单新增 "5 - Manager 统一管理面板";
- 主程序维护 `WorldContext` 单例(Agent 实例、生态植物实例列表、Pet 实例、Boids 列表、Manager 实例、全局 tick 计数),所有模式 run() 签名改为 `run(screen, font, clock, ctx: WorldContext)`;
- 每个主循环 tick: `ctx.tick_count += 1`;每 500 tick:打印所有 `tunnel_stats()` + 各模式关键统计;
- `manager_state.json`/`pet_state.json` 在菜单退出/进入时自动 save/load;
- 原 mode_boids 基本不变,但需接受 `ctx` 签名,并把 boids 列表存入 ctx。

### 测试要求
| ID | 类型 | 内容 |
|----|------|------|
| T11-TR1 | rule | 主菜单显示 5 个选项,1~5 均可进入,ESC 可返回 |
| T11-TR2 | rule | 每 500 tick 控制台打印"隧穿统计:XXX",可观察到 ≥ 1 次 |
| T11-TR3 | rule | 从生态返回菜单 → 再进入 → 种群数量保留(不重置);重启程序后才重置(持久化仅针对 Pet/Manager 状态,不持久化整个世界) |

**状态**: pending
**完成证据**: (待填)
