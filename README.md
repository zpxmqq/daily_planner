# Daily Planner · 目标驱动型 AI 规划与复盘助手

![Python](https://img.shields.io/badge/Python-3.10+-blue) ![Streamlit](https://img.shields.io/badge/Streamlit-1.37-red) ![LLM](https://img.shields.io/badge/LLM-DeepSeek-orange) ![RAG](https://img.shields.io/badge/RAG-lightweight-8A2BE2)

[🔗 在线演示](https://aracd49kjcqm5a7mslyksw.streamlit.app) · [🎬 Demo 视频](https://www.bilibili.com/video/BV1KSdfBJEdL/?share_source=copy_web&vd_source=94df4a8c6841c4de85fbc438f83189d0)

> **不会机械提醒、会记得你上次没做什么、会容忍短期空档的个人规划 AI**

## 30 秒看懂它做什么

大多数个人规划 AI 止步于「每天给你出一张任务清单」。这个项目想再往前一步——**它会记住你昨天的 AI 建议，会判断你今天是否真正执行了，会在某条目标断线时温和地提醒而不是机械轰炸，会用历史经验让新一天的建议更具体**。一个把「长期目标 → 今日动作 → AI 评价 → 晚间复盘 → 历史检索」串成闭环的 LLM 应用原型。

与市面同类 "todo + AI" 项目的具体区别：

- 🎯 **建议追踪三状态**（done / partial / not_obvious）—— 规则引擎自动判断昨日 AI 建议是否执行，而非让用户手工勾选
- 🫥 **容忍机制** —— 某条目标一天没覆盖不立刻追问，结合多天节奏、目标优先级和截止时间判断是否提醒
- 🔗 **结构化 JSON 输出** —— AI 评价与复盘以 schema 约束输出可解析字段，渲染为结构化卡片而非聊天气泡
- 📚 **轻量 RAG** —— 历史计划/复盘切分为 chunk，检索综合语义相似度 + 时间新近性 + 目标标签重合度

**技术栈**：`Python · Streamlit · OpenAI SDK (兼容 DeepSeek) · SQLite · Embedding RAG`

---

## 核心功能

### 1. 个人信息页收口长期信息

首页不再把"目标"和"档案"大面积铺开，而是通过左上角的小入口进入"个人信息页"，统一维护：长期背景档案、长期目标、职业规划长文本以及 AI 结构化提取结果。这样产品主页面更聚焦于"今天该做什么"，同时长期信息依然可以被 AI 自动使用。

### 2. 自然输入的今日计划

用户输入今日任务时，不需要机械地把每个任务都手动绑定到目标。系统结合 **任务文本 + 标签 + 历史目标语义 + embedding 相似度** 自动推断关联目标，以更自然的方式支持任务录入。

### 3. 晨间 AI 计划评价

系统对当天计划做结构化分析，关注：任务量是否过满、当前阶段重点是否被覆盖、哪条主线今天最值得推进、是否需要调整优先级、哪些提醒需要容忍短期空档。输出不是模型原话，而是解析为结构化字段后渲染成页面卡片。

### 4. 晚间轻量复盘

复盘保持轻量，不走重问卷路线。用户只需勾选已完成任务、给已完成项补一句短备注、填写额外完成内容、选择今日状态。系统生成具体的复盘结果：今天真正推进了什么、哪条线推进一般、明天最重要的一件具体动作。

### 5. 建议追踪与容忍机制

系统自动追踪前一日建议是否被执行，输出 `done` / `partial` / `not_obvious` 三态，并结合备注质量信号给出判断理由。提醒逻辑不再机械——某条目标一天没覆盖不会立即在复盘里强行提醒，会综合最近多天推进情况、目标优先级和截止时间做更有容忍度的判断。

### 6. 历史经验检索增强

晨间计划和晚间复盘时，系统从历史记录中检索最相关的过往计划或复盘经验，作为 `【相关历史经验】` 注入模型上下文。首版只使用项目内部数据，不接外部知识库，重点验证"历史经验能否提升计划与复盘质量"。

---

## 技术亮点

### 结构化 Prompt 与 JSON 输出

计划评价和复盘总结都使用结构化 schema，约束模型输出可解析的 JSON，减少"空泛鼓励"和不稳定格式问题。

### 上下文工程

服务层在模型调用前统一构建上下文，来源包括长期背景档案、长期目标与标签、今日任务及属性、建议追踪结果、目标推进节奏以及检索到的历史经验。

### 模型输出解析与异常兜底

模型返回内容不会直接原样上屏。项目先解析 JSON，再提取关键字段渲染；若模型异常、embedding 配置缺失或检索失败，系统会优雅降级，而不阻断主流程。

### 轻量 RAG 设计

每个日期生成 `plan_chunk` 和 `review_chunk` 两类检索单元。检索排序综合 **语义相似度 + 时间新近性 + goal_id/tag 元数据重合度**；检索结果最多注入 3-4 条摘要，不把整段原始历史堆给模型。embedding 接口采用 OpenAI-compatible 方式，便于更换 provider；embedding 不可用时自动降级。

### SQLite 数据层统一化

运行时主数据源为 `SQLite`（`goals` / `profile` / `history_records` / `history_tasks` / `rag_chunks` 五张表），JSON 文件仅作为首次导入和本地备份。

---

## 项目结构

```text
daily-planner/
├─ app.py                    # 应用入口与页面路由
├─ pages/                    # 页面层：首页、计划、复盘、历史、个人信息
├─ components/               # 组件层：导航、卡片、目标卡片、AI 结果展示
├─ services/                 # 业务服务层：LLM、计划、复盘、RAG、目标统计、任务推断
├─ prompts/                  # Prompt 模板与结构化输出约束
├─ data/                     # Repository 与数据持久化逻辑
├─ config/                   # 配置项与环境变量读取
├─ planner.db                # SQLite 主数据库（运行时生成）
└─ {goals,history,profile}.json   # 首次导入源 / 本地备份
```

## 快速开始

```bash
pip install -r requirements.txt
streamlit run app.py
```

项目根目录创建 `.env`：

```env
DEEPSEEK_API_KEY=your_api_key

# 可选：启用 embedding API 版 RAG
EMBEDDING_API_KEY=your_embedding_api_key
EMBEDDING_BASE_URL=your_embedding_base_url
EMBEDDING_MODEL=your_embedding_model
```

不配置 embedding 接口时，项目自动走轻量本地 fallback，不影响主流程。

## 使用流程

1. 进入"个人信息"页，填写长期背景档案与长期目标（可粘贴职业规划长文本让 AI 结构化提取）
2. 进入"今日计划"页录入任务属性（时长、优先级、标签、是否必须完成），点击获取 AI 晨评
3. 晚上进入"复盘"页勾选完成项、补短备注、填写额外完成内容，生成 AI 复盘与自动追踪
4. 在"历史"页查看每日快照、建议追踪和 AI 结果沉淀

## LLM 输出 Schema

```json
// ai_plan_result
{ "overall": str, "covers_focus": str, "issues": [str],
  "focus_tasks": [str], "top_priority": str }

// ai_review_result
{ "score": str, "real_progress": str, "weak_lines": str, "tomorrow": str }

// suggestion_tracking （规则引擎，非 AI 生成）
{ "source_date": str, "source_top_priority": str, "source_tomorrow": str,
  "status": "done|partial|not_obvious", "reason": str, "auto_judged": bool }
```

---

## 项目边界

这是一个 **LLM 应用开发原型**，而不是：

- 底座模型训练项目
- 完整生产级 SaaS
- 含复杂评测平台、权限体系、多人协作的成熟产品

当前使用本地 `SQLite` 存储，适合原型验证与个人使用，不是生产级后端架构。

## 在这个项目里锻炼了什么

- 将大模型能力嵌入完整产品闭环，而不是单次对话 Demo
- 设计 Prompt 与结构化 JSON 输出，提升 LLM 结果的稳定性与可用性
- 构建多源上下文（长期背景、任务、历史建议、检索结果）
- 设计本地数据层与历史记录机制，让应用具备持续使用能力
- 实现轻量 RAG、自动目标推断、建议追踪等贴近真实 LLM 应用的问题

## 当前不足与后续方向

- 还没有正式评测集量化 "RAG 是否显著提升计划与复盘质量"
- SQLite 适合当前阶段，多端同步/多人协作需升级为服务端数据库
- 结构化输出主要靠 Prompt 约束，可继续加 Pydantic / JSON Schema 硬校验
- 历史检索目前只覆盖项目内数据，未接入外部知识材料

后续可扩展：更细粒度的 task-level 检索、系统时间/趋势分析、面向实习场景的"学习/项目/求职"多主题看板。
