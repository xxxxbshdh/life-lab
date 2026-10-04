# Life Lab v2 · 人工生命实验室

一个用纯 Python 写的桌面「人工生命实验台」：神经进化 Agent、生态系统、Boids 鸟群、对话宠物、管家面板，5 个模式一键切换。

> 这是一个学习性质的开源项目。**欢迎任何人 fork、修改、提交 PR**。原创设计保留，代码自由使用。

---

## 这是什么

Life Lab 把几个经典的人工生命 / 智能体实验做成了一个可视化桌面程序：

| 模式 | 说明 |
|---|---|
| 🧠 **自主感知 Agent** | 决策由 `NeuralBrain`（8-16-4 MLP）给出，不用规则；量子启发式 softmax 概率采样；按 `E` 键进化（交叉 + 隧穿/高斯突变） |
| 🌿 **生态系统** | 植物 / 食草动物 / 捕食者 / 小龙虾；每只动物携带基因 → 表型，繁殖时交叉 + 突变 |
| 🐦 **Boids 鸟群** | 人工生命经典：分离 / 对齐 / 聚合三条规则涌现群体行为 |
| 💬 **对话宠物** | LLM 接入（OpenAI 兼容接口）+ 离线规则降级 + RAG 知识增强 + 状态持久化 |
| 🎛️ **Manager 管家** | 视觉皮层文字摘要 + 自然语言指令解析执行 + 网页学习 |

## 亮点设计

- **零重依赖**：神经网络、分词、基因操作全部纯 Python 实现，**不依赖 numpy / jieba / torch**
- **可遗传的权重**：`NeuralBrain` 权重 flat 成列表后直接当基因型，`mutate` / `crossover` 开箱即用
- **量子启发决策**：不是 `argmax`，而是按 softmax 概率采样（模拟叠加态坍缩）
- **统一模式接口**：每个 mode 都实现 `run(screen, font, clock, ctx)`，主菜单随意插拔
- **优雅降级**：LLM 无配置 / 断网时自动退回规则引擎，不会崩

## 快速开始

```bash
# 1. 安装依赖（只有一个）
pip install pygame

# 2. 运行
python life_lab.py
```

### 可选：接入大模型

对话宠物 / 管家支持任何 **OpenAI 兼容接口**（本地 Ollama、智谱、DeepSeek、OpenAI 等）。

```bash
# 复制配置模板
cp llm_config.example.json llm_config.json
# 编辑 llm_config.json 填入你的 base_url / api_key / model
```

示例（本地 Ollama，免密钥）：

```json
{
  "base_url": "http://localhost:11434/v1",
  "api_key": "ollama",
  "model": "qwen3:8b"
}
```

> ⚠️ `llm_config.json` 已在 `.gitignore` 中，不会被提交。**切勿把真实 API 密钥提交到公开仓库。**

## 目录结构

```
life_lab.py          主入口（统一菜单 + WorldContext）
mode_manager.py      管家面板（视觉皮层 + 指令调度 + 网页学习）
mode_pet.py          对话宠物（LLM + 离线降级 + RAG + 持久化）
mode_ecosystem.py    生态系统（基因遗传 + 小龙虾）
life_agent.py        自主感知 Agent（神经进化 + 量子采样）
mode_boids.py        Boids 鸟群
browser_study.py     知识库 RAG（TF-IDF + Jaccard）
neural_brain.py      纯 Python MLP（可遗传）
quantum_ops.py       量子启发操作
gene_ops.py          基因交叉 / 突变 / 隧穿
vision_cortex.py     视觉皮层
ui_widgets.py        界面组件
core_types.py        基础类型
settings_store.py    配置持久化
llm_client.py        LLM 客户端
font_utils.py        字体工具
```

## 键盘操作

- 主菜单：按数字键 `1`~`5` 进入对应模式
- Agent 模式：按 `E` 触发进化
- `Esc` 返回主菜单

## 参与贡献

非常欢迎贡献！任何形式的改进都可以：

1. **Fork** 本仓库
2. 新建分支：`git checkout -b feature/你的改动`
3. 提交：`git commit -m "描述你的改动"`
4. 推送并发起 **Pull Request**

无论是修 bug、加新模式、优化算法还是改进文档，都欢迎。也欢迎提 Issue 讨论想法。

## 许可

本项目采用 **MIT License**，详见 [LICENSE](LICENSE)。你可以自由使用、修改、分发，包括商业用途，只需保留版权声明。

---

*原创作品开源分享，希望它对你有所启发。*
