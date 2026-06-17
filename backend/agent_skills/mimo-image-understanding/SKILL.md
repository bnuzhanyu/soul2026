---
name: mimo-image-understanding
description: >-
  使用 MiMo 多模态图片理解能力分析用户上传到 OSS 的图片，适合给简笔画、动作照片、训练截图做观察、评分和改进建议。
---

# MiMo Image Understanding Skill

使用 MiMo `mimo-v2.5` 的图片理解能力读取公网图片 URL，并输出简短、结构化的观察结果。

## When to use

- 用户上传了图片，并且附件信息里有 `url` 或 `ossUri`。
- 需要根据图片和学习目标评分，例如简笔画线条、构图、动作姿态、训练结果截图。
- 需要对比“今日目标图/参考图”和“用户作品图”，判断是否画对、完成度和美观度。
- 需要先理解图片内容，再用 JOMO 的语气给温柔、具体的反馈。

不要用于：
- 没有公网图片 URL 的附件。
- 纯文字聊天。
- 音频理解。

## How to invoke

Host 会注入：

- `JOMO_MIMO_IMAGE_UNDERSTANDING_SCRIPT`：本 skill 的脚本路径。
- `MIMO_API_KEY` 或 `ANTHROPIC_API_KEY` / `ANTHROPIC_AUTH_TOKEN`：API key。
- `MIMO_ANTHROPIC_BASE_URL` 可选，默认 `https://api.xiaomimimo.com/anthropic/v1/messages`。
- `MIMO_IMAGE_MODEL` 可选，默认 `mimo-v2.5`。

## Skill tool args contract

如果你是通过 `Skill` 工具调用本 skill，`args` 必须是严格 JSON 字符串，不要传自然语言句子。JSON schema：

```json
{
  "mode": "single|scoring|compare",
  "imageUrls": ["用户上传图片 URL，至少 1 张"],
  "targetImageUrls": ["今日目标图或参考图 URL，可选"],
  "learningGoal": "今天要完成的学习目标",
  "rubric": "评分标准，例如是否画对、完成度、美观度、下一步建议",
  "prompt": "可选，如果不填会根据 mode/learningGoal/rubric 自动生成",
  "maxTokens": 600
}
```

示例：

```json
{
  "mode": "scoring",
  "imageUrls": ["https://example.com/user-doodle.png"],
  "targetImageUrls": ["https://example.com/today-target-cup.png"],
  "learningGoal": "画一个由圆形和直线组成的可爱杯子",
  "rubric": "先判断是否像杯子，再给完成度 1-10、美观度 1-10，最后给一个下次只改一点的建议"
}
```

如果没有参考图，仍然传 JSON：

```json
{
  "mode": "single",
  "imageUrls": ["https://example.com/user-doodle.png"],
  "learningGoal": "画一个杯子，用圆形和直线把它变可爱",
  "rubric": "观察画面内容、完成度、线条清晰度和一个小建议"
}
```

## Bash usage

用 `Bash` 调用脚本，传入图片 URL 和分析要求：

```bash
uv run --script "$JOMO_MIMO_IMAGE_UNDERSTANDING_SCRIPT" \
  --image-url "https://example.com/user-doodle.png" \
  --prompt "请按简笔画学习目标评价：1. 画面里是什么；2. 完成度 1-10 分；3. 一个做得好的点；4. 一个下次只改一点的小建议。" \
  --print-json
```

也可以从 stdin 传 JSON：

```bash
cat <<'EOF' | uv run --script "$JOMO_MIMO_IMAGE_UNDERSTANDING_SCRIPT" --stdin-json --print-json
{
  "mode": "scoring",
  "imageUrls": ["https://example.com/user-doodle.png"],
  "targetImageUrls": ["https://example.com/target.png"],
  "learningGoal": "画一个由圆形和直线组成的可爱杯子",
  "rubric": "判断是否画对、完成度、美观度和一个改进点",
  "maxTokens": 500
}
EOF
```

返回：

```json
{
  "model": "mimo-v2.5",
  "content": "图片观察和反馈文本",
  "imageUrls": ["https://..."],
  "usage": {}
}
```

## Response guidance

拿到脚本结果后，JOMO 最终回复保持短：

- 先说看到的一个具体事实。
- 如果有 `targetImageUrls`，必须先对比目标图和用户作品，再判断是否画对。
- 给 1 个 1-10 分评分或等级；简笔画评分同时考虑是否画对、完成度、美观度。
- 给 1 个用户下次能马上做的小建议。
- 如果图片读取失败，不要虚构画面内容，直接说明“图片这次没读成功”，再请用户重试或用文字描述。

## Bash guardrails

Bash 只用于调用 `$JOMO_MIMO_IMAGE_UNDERSTANDING_SCRIPT`。不要用 Bash 读取仓库文件、写文件、curl 其他地址或处理密钥。
