# JOMO 项目提案与 Demo 设计

## 1. 项目灵感

JOMO 是一个可爱的 AI 技能伙伴产品，帮助用户把“怕错过”的焦虑变成“我正在变好”的小确幸。用户可以为不同技能创建多个 JOMO 伙伴，例如简笔画、速读、宠物训练、深蹲、俯卧撑等。每个伙伴会根据用户基础信息生成技能树、每日小挑战和简短反馈，通过对话、图片、打分和互动小界面陪用户持续练习。预期价值是让用户用轻松、可见、可积累的成长体验对抗 FOMO。

## 2. 产品名称

JOMO

含义：Joy of Missing Out。不是追每一个热点，而是享受自己的节奏。

## 3. 一句话介绍

JOMO 是一个陪用户培养小技能的 AI 伙伴系统，用可爱、轻量、持续的练习体验，把焦虑感转化为成长感。

## 4. 核心用户流程

1. 用户进入网页，通过微信注册。
2. 首次注册时填写基础信息，包括昵称、性别、出生日期、近期目标等。
3. 用户创建一个 JOMO 伙伴，选择技能大类和技能小类。
4. 后端根据用户信息、技能配置和当前进度生成初始计划。
5. 用户进入伙伴对话页，可以汇报练习次数、发送图片、选择 AI 生成的 HTML 互动界面。
6. AI 给出短而有人味的反馈，并更新成长证据和技能树进度。
7. 用户后续可以在 profile 区修改基础信息，伙伴计划会重新生成。

## 5. 技能体系

技能由后端配置，前端通过 `/api/skills` 获取，方便后续扩展。

当前大类与小类：

- 生活
  - 宠物训练
  - 简笔画
  - 速读
- 健身
  - 仰卧起坐
  - 俯卧撑
  - 深蹲
  - 平板支撑

每个技能包含：

- `id`
- `name`
- `icon`
- `strategy`
- `starter`
- `nodes` 技能树节点

## 6. AI 伙伴设计

伙伴以对话为主，回复尽量短，减少长篇思考。它可以处理几类输入：

1. 数量汇报：例如“我做了 18 个深蹲”，AI 记录成长证据并给一句短反馈。
2. 图片输入：用户上传动作或作品图片，AI 给动作质量或作品建议。
3. 练习选择：AI 可以生成 HTML 选项卡片，用户点击后进入下一步。
4. 技能专项训练：例如速读会生成阅读训练卡片。
5. 焦虑表达：AI 用温暖话术把焦虑转成一个小行动，而不是冷冰冰地说教。

示例语气：

> 抱抱这点小焦虑。我们不追一整片海，先捡今天这颗小贝壳。

> 收到，今天的小能量到账。下一组慢一点，动作比数量更重要。

## 7. 速读专项玩法

速读不是普通聊天，而是一个 AI 生成策略界面：

1. 根据当前训练进度生成一段短文。
2. 自动设置阅读时间，例如 45 秒、38 秒、32 秒。
3. 用户点击开始后，界面 3、2、1 倒计时。
4. 倒计时结束后显示文字并开始计时。
5. 用户可以暂停，暂停时文字隐藏。
6. 用户可以从头开始，也可以强制显示文字。
7. 时间结束后，文字隐藏，用户输入中心思想。
8. AI 根据中心思想打分，并生成成长证据。

## 8. Demo 技术设计

当前 demo 拆成 Vite 前端和 Python/uv 后端：

- `frontend/index.html`：Vite HTML 入口。
- `frontend/src/app.js`：前端状态、渲染、SSE 流式消费、互动 HTML 执行。
- `frontend/src/styles.css`：可爱小清新 UI。
- `frontend/vite.config.js`：Vite 配置，开发时把 `/api` 代理到 Python 后端。
- `backend/jomo_backend/app.py`：Python API 服务，提供 health、技能、计划、速读和聊天接口。
- `backend/jomo_backend/skills.py`：后端技能目录。
- `backend/jomo_backend/strategy.py`：本地策略 fallback，包括计划生成、HTML 互动、速读训练和评分。
- `backend/jomo_backend/agent.py`：Claude Agent SDK 集成，负责 Anthropic/Claude 对话、短回复策略和 session resume。
- `pyproject.toml` / `uv.lock`：Python 后端依赖，由本项目 uv 管理。
- `package.json` / `package-lock.json`：Vite 前端依赖。

后端 API：

- `GET /api/skills`
- `POST /api/partners/plan`
- `POST /api/chat`
- `POST /api/speed-reading/exercise`

`POST /api/chat` 使用 SSE 风格事件流，事件包括：

- `agent.started`
- `token`
- `html`
- `progress`
- `done`

如果配置了 `ANTHROPIC_API_KEY` 或 `ANTHROPIC_AUTH_TOKEN`，普通聊天会优先走 Anthropic Claude agent；速读训练卡片、选项卡片等结构化 HTML 仍由本地策略生成，保证 demo 可控。AI 请求失败或未配置 key 时，会自动回退到本地策略。

session 管理：

- 每个新建 JOMO 伙伴都会生成独立 `sessionId`。
- 后端把 `sessionId` 转成稳定 UUID，传给 Claude Agent SDK。
- 每个 session 的 JSONL 历史保存在 `.run/jomo-agent/<session-id>/sessions`。
- 同一个伙伴后续对话会用 `resume` 继续，避免不同对话框互相污染上下文。

前端 debug mode 会显示 AI 所有输出事件、AI 原始回复和 HTML 原始内容，便于调试真实 agent。

本地 AI 配置示例见 `.env.example`：

- `ANTHROPIC_API_KEY`
- `ANTHROPIC_MODEL`
- `ANTHROPIC_BASE_URL`
- `JOMO_AGENT_MAX_TURNS`

Python agent 依赖由本项目 uv 管理：

```bash
UV_CACHE_DIR=.uv-cache uv sync
```

本地开发启动：

```bash
npm run dev:api
npm run dev
```

访问 `http://127.0.0.1:5173`，前端会通过 Vite proxy 调用 `http://127.0.0.1:4174/api/*`。

## 9. MVP 展示重点

比赛 demo 可以展示三条路径：

1. 首次微信注册和基础信息填写。
2. 创建多个 JOMO 伙伴，并看到后端生成的技能树和每日挑战。
3. 进入伙伴对话：
   - 汇报次数，触发短反馈和技能树进度。
   - 上传图片，触发动作或作品反馈。
   - 速读伙伴生成 HTML 训练卡片，完成中心思想评分。

## 10. 后续扩展

- 接入真实微信登录。
- 扩展 Python agent 的工具协议，让 AI 可以安全请求更多本地 HTML 互动组件。
- 让 AI 根据历史成长证据动态调整技能树。
- 给每个技能增加更专业的评分策略。
- 增加 profile 页、成长证据页和多端同步。
- 接入真实图像理解，对健身动作和绘画作品做更准确反馈。
