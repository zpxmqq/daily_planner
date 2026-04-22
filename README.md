# Daily Planner | 目标驱动型 AI 规划与复盘助手

![Python](https://img.shields.io/badge/Python-3.10+-blue)
![Streamlit](https://img.shields.io/badge/Streamlit-1.37-red)
![LLM](https://img.shields.io/badge/LLM-DeepSeek-orange)
![RAG](https://img.shields.io/badge/RAG-lightweight-8A2BE2)

[在线演示](https://aracd49kjcqm5a7mslyksw.streamlit.app) | [Demo 视频](https://www.bilibili.com/video/BV1KSdfBJEdL/?share_source=copy_web&vd_source=94df4a8c6841c4de85fbc438f83189d0)

这是一个面向个人成长场景的 LLM 应用项目，用来把“长期目标”“今日计划”“AI 评价”“晚间复盘”“建议追踪”“历史经验检索”串成一个可持续使用的闭环。

它不是一次性的聊天 Demo，而是一个更接近真实产品原型的 AI 规划系统：

- 会结合长期背景理解你今天该推进什么
- 会追踪昨天的建议今天有没有真正执行
- 会容忍短期波动，而不是机械地一天没做就提醒
- 会利用历史记录和轻量 RAG，让新一天的建议更具体
- 会结合“预计用时 vs 实际用时”给出执行校准建议

## 项目闭环

`长期背景 / 长期目标 -> 今日任务 -> AI 晨间评价 -> 晚间轻量复盘 -> 建议追踪 -> 历史经验检索 -> 下一步建议`

在当前版本里，这个闭环已经不只停留在“计划”和“复盘”，还加入了新的执行层数据：

`任务计划 -> 实际用时记录 -> 时间分析 -> AI focus insight`

## 核心功能

### 1. 个人信息页收口长期信息

系统将长期信息统一放在“个人信息”页，而不是堆在首页。当前支持维护：

- 当前总目标
- 当前阶段重点
- 近期优先事项
- 当前约束
- 不必猛冲事项
- 反馈风格
- 职业规划长文本与 AI 结构化提取
- 长期目标、描述、优先级、截止时间、标签

### 2. 自然输入的今日计划

今日计划页支持直接输入任务文本、优先级、预计时长、是否必须完成等信息，不要求用户机械地手工绑定所有目标。

系统会在已有目标和历史任务的基础上，尽量自动推断：

- 任务更可能关联哪个长期目标
- 任务更可能属于哪个标签

### 3. 四级自动打标

新增 `classification_service` 后，任务标签识别采用四级链路：

1. 用户手填标签
2. 关键词匹配
3. embedding 语义匹配
4. `突发 / 其他` 兜底

这让用户即使不填 tag，系统也能尽量做出稳定分类，同时保留标签来源信息用于展示。

### 4. 晨间 AI 计划评价

系统会对今日计划做结构化分析，重点输出：

- 总体判断
- 阶段重点覆盖情况
- 时间负荷判断
- 问题发现
- 今日重点任务
- 建议调整
- `top_priority`

AI 输出不会直接原样展示，而是先解析 JSON，再渲染成结构化卡片。

### 5. 晚间轻量复盘

晚间复盘保持轻量，不做重问卷。用户只需要：

- 勾选完成项
- 给完成项补一句短备注
- 填写额外完成内容
- 选择今日状态
- 必要时补录实际用时

AI 再根据这些内容输出：

- 完成度评价
- 今天真实推进了什么
- 哪条线较弱
- 明天最重要的一步
- `focus_insight`

### 6. 实际用时记录

这是这轮改动里最重要的新能力之一。

计划页每个任务右侧都可以开始/结束一次“实际用时”记录。底层不是简单前端计时，而是任务级 session 持久化：

- 一个任务可以有多段 session
- 可以汇总为 `actual_minutes`
- 浏览器异常关闭后可以恢复 orphan session
- 晚间复盘页也支持手工补录实际用时

这部分数据会进入后续 AI 分析，而不是只停留在界面上。

### 7. AI 基于执行数据做校准

复盘服务层现在会把以下信息一起注入模型上下文：

- 今日时间去向
- 预计 vs 实际偏差
- 最近 7 日预估偏差
- 突发任务占用时间

因此，AI 新增了 `focus_insight` 字段，用来输出更具体的执行校准建议，例如：

- 哪类任务长期高估或低估
- 某任务实际耗时明显偏离预期
- 明天应该如何拆解任务或调整时长预估

这让项目从“AI 点评计划”升级成“AI 根据真实执行数据校准计划”。

### 8. 建议追踪与容忍机制

系统会自动判断昨日建议今天是否执行，并输出：

- `done`
- `partial`
- `not_obvious`

同时，提醒逻辑不是机械绑定：

- 某条长期线一天没推进，不会立刻强提醒
- 会结合最近几天推进情况、目标优先级和 deadline 再决定是否提示
- 对计划外突发任务有容忍机制

### 9. 轻量 RAG

当前项目已实现轻量历史检索增强：

- 每天生成 `plan_chunk` 和 `review_chunk`
- 检索排序综合考虑语义相似度、时间新近性、goal_id / tag 重叠
- 晨间计划和晚间复盘都会注入 `【相关历史经验】`
- `actual_minutes` 和 `unplanned` 也会进入 RAG chunk

这意味着系统不仅记“做了什么”，也开始记“做这件事真实花了多少时间”。

### 10. 时间分析页

新增独立的时间分析页面，支持：

- 日期范围切换：今天 / 7 天 / 30 天
- 按标签统计实际用时
- Plotly 饼图展示时间分布
- 预计 vs 实际散点图
- 文字洞察：预估准确率、偏差最大的类别、突发任务占比

这个页面让“执行数据”从后台字段变成了可见、可解释的产品能力。

## 技术亮点

### 结构化 Prompt 与 JSON 输出

计划评价和复盘总结都使用固定 schema，模型输出先解析再展示，减少格式不稳定和空泛话术问题。

### 上下文工程

模型上下文不只包含当天任务，还会综合：

- 长期背景档案
- 长期目标与标签
- 今日任务及属性
- 建议追踪结果
- 长期线断档提醒
- 历史检索结果
- 实际用时与时间偏差

### 执行数据闭环

这轮新增的时间记录不是孤立功能，而是被贯穿到了：

- `task_sessions`
- `history_tasks.actual_minutes`
- `review_context`
- `focus_insight`
- `time_analysis`
- `rag_chunks`

这是项目完成度提升最明显的一点。

### SQLite 统一数据层

当前运行时真源为 SQLite，主要表包括：

- `goals`
- `profile`
- `history_records`
- `history_tasks`
- `rag_chunks`
- `task_sessions`

同时保留 JSON 作为导入备份和兼容来源。

## 技术栈

- `Python`
- `Streamlit`
- `OpenAI Python SDK（兼容 DeepSeek）`
- `python-dotenv`
- `SQLite`
- `Plotly`
- `JSON（仅作备份导入）`

## 项目结构

```text
daily-planner/
├─ app.py
├─ pages/                    # 首页、计划、复盘、历史、个人信息、时间分析
├─ components/               # 导航、卡片、AI 展示组件
├─ services/                 # LLM、计划、复盘、RAG、时间跟踪、自动打标等
├─ prompts/                  # Prompt 模板与结构化 schema
├─ data/                     # SQLite Repository
├─ config/                   # 配置与环境变量
├─ planner.db                # 运行时数据库
└─ {goals,history,profile}.json
```

## 快速开始

```bash
pip install -r requirements.txt
streamlit run app.py
```

在项目根目录创建 `.env`：

```env
DEEPSEEK_API_KEY=your_api_key

# 可选：embedding API
EMBEDDING_API_KEY=your_embedding_api_key
EMBEDDING_BASE_URL=your_embedding_base_url
EMBEDDING_MODEL=your_embedding_model
```

如果不配置 embedding 接口，系统会自动走本地 fallback，不影响主流程运行。

## 使用流程

1. 进入“个人信息”页，填写长期背景与长期目标
2. 在“今日计划”页录入任务，并获取 AI 晨评
3. 若需要，可对任务记录实际用时
4. 晚上进入“复盘”页勾选完成项、补备注、补额外完成内容，生成 AI 复盘
5. 在“历史”页查看每日快照与建议追踪
6. 在“时间分析”页查看实际用时分布与预估偏差

## LLM 输出 Schema

```json
// ai_plan_result
{
  "overall": "string",
  "covers_focus": "string",
  "time_assessment": "string",
  "issues": ["string"],
  "focus_tasks": ["string"],
  "adjustments": ["string"],
  "top_priority": "string"
}

// ai_review_result
{
  "score": "string",
  "real_progress": "string",
  "weak_lines": "string",
  "tomorrow": "string",
  "focus_insight": "string"
}

// suggestion_tracking
{
  "source_date": "string",
  "source_top_priority": "string",
  "source_tomorrow": "string",
  "status": "done|partial|not_obvious",
  "reason": "string",
  "auto_judged": true
}
```

## 项目边界

这是一个 `LLM 应用开发原型`，不是：

- 底座模型训练项目
- 完整生产级 SaaS
- 带账号体系、多人协作、部署集群和正式评测平台的成熟产品

当前使用本地 SQLite 存储，适合个人使用和原型验证。

## 这个项目体现的能力

- 将大模型能力嵌入完整产品闭环，而不是只做单次问答
- 设计 Prompt 与结构化输出，提升结果稳定性
- 构建多源上下文，包括长期背景、任务、历史经验和执行数据
- 设计本地数据层与历史记录机制，支撑持续使用
- 实现轻量 RAG、建议追踪、自动打标、时间分析等更接近真实 LLM 应用的问题

## 当前不足与后续优化

- 还没有正式评测集去量化“RAG 和执行数据校准是否显著提升效果”
- SQLite 更适合当前阶段，若做多人协作需要升级后端存储
- 结构化输出目前主要依赖 Prompt 约束，后续可加入更严格的 schema 校验
- 时间记录目前仍是轻量版，未来可继续做更细粒度趋势分析
- 在线 demo 更适合作品展示，不适合作为正式多用户产品
