---
name: seedream-game-assets
description: >-
  使用 Seedream 为 JOMO 学习伙伴生成图片素材，例如今日目标图、简笔画参考图、训练卡插图、奖励贴纸和小头像。生成结果写入会话 assets 目录，宿主会自动上传到 OSS 并在聊天里展示。
---

# Seedream JOMO Image Skill

这个 skill 用火山引擎 Seedream 生成适合 JOMO 学习场景的 PNG 图片。它保留 `seedream-game-assets` 这个目录名，方便复用现有后端配置，但用途已经不是游戏素材，而是 JOMO 的学习素材。

## When To Use

- 用户开始绘画、简笔画、动作规则、冥想等学习时，需要一张“今日目标图”或“参考图”。
- 需要给用户生成可照着练的视觉目标，例如“一个由圆形和直线组成的可爱杯子”。
- 需要生成练习卡插图、奖励贴纸、伙伴头像、小徽章。
- 需要给后续 `mimo-image-understanding` 评分提供 `targetImageUrls` 参考图。

不要用于：

- 纯文字训练内容、选择题、速读文章。
- UI 按钮、布局、渐变背景、纯几何占位图，这些直接用 HTML/CSS。
- 用户已经上传了作品、只需要读图评分时，应调用 `mimo-image-understanding`。

## Output Contract

生成图片后，脚本会写入 `$GAME_AGENT_DRAFT_ASSETS_DIR`。JOMO 后端会自动发现新图片、上传到 OSS，并通过 `image` SSE 事件展示在聊天里。

最终回复里不要手写本地文件路径，也不要把图片字节放进文本。只需要简短告诉用户图片是今天的目标图或参考图，并引导用户照着练后上传作品。

如果这张图是后续评分目标，回复里要明确一句：这张图就是今天评分时会对比的目标图。

## How To Invoke

Host 注入：

- `GAME_AGENT_SEEDREAM_SCRIPT`：脚本绝对路径。
- `GAME_AGENT_DRAFT_ASSETS_DIR`：当前会话 assets 输出目录。
- `ARK_API_KEY`：Seedream API key。

用 `Bash` 调用脚本，并通过 stdin 传 JSON spec：

```bash
cat <<'EOF' | uv run --script "$GAME_AGENT_SEEDREAM_SCRIPT" --output-dir "$GAME_AGENT_DRAFT_ASSETS_DIR" --print-json
{
  "prompt": "JOMO 小清新可爱风，干净白底，柔和线条，适合初学者临摹。生成一个由圆形、椭圆和直线组成的小杯子简笔画目标图，不要文字，不要复杂背景。",
  "sheets": [
    {
      "rows": 1,
      "cols": 1,
      "cellWidth": 512,
      "cellHeight": 512,
      "transparentBackground": false,
      "assetNames": ["today-target-cup.png"]
    }
  ]
}
EOF
```

返回示例：

```json
{
  "saved": ["today-target-cup.png"],
  "count": 1
}
```

## Spec Shape

```json
{
  "prompt": "整体风格 + 图片用途 + 每张图具体内容",
  "sheets": [
    {
      "rows": 1,
      "cols": 1,
      "cellWidth": 512,
      "cellHeight": 512,
      "transparentBackground": false,
      "assetNames": ["today-target.png"]
    }
  ]
}
```

- `rows × cols` 必须等于 `assetNames.length`。
- 文件名只能是 `.png`，用英文小写和连字符，例如 `today-target-cup.png`。
- 参考图、目标图、练习卡插图通常用 `512 × 512` 或 `768 × 512`。
- 贴纸、徽章、伙伴表情可以用透明背景：`transparentBackground: true`。
- 目标图/参考图通常不要透明背景，使用干净浅色背景更利于用户临摹和 MiMo 对比。

## Prompt Guidance

写 prompt 时优先说明：

- 学习技能：例如简笔画、跳水动作规则、冥想训练。
- 图片用途：今日目标图、参考图、奖励贴纸、练习卡插图。
- 用户难度：初学者、轻量练习、可临摹。
- 视觉风格：JOMO 小清新、可爱但不幼稚、干净、明亮、柔和线条。
- 不要在图里生成文字、题目、分数或按钮，这些由 HTML/Markdown 展示。

简笔画目标图建议：

- 画面主体单一，不要复杂背景。
- 线条清楚，形状拆解明显。
- 可以可爱，但不要塞太多装饰。
- 适合后续与用户作品图对比评分。

## Common Specs

单张今日目标图：

```json
{
  "prompt": "JOMO 小清新可爱风，干净浅色背景。一个初学者可临摹的简笔画目标图：用圆形、椭圆和直线画一只小猫，线条清楚，不要文字。",
  "sheets": [
    {
      "rows": 1,
      "cols": 1,
      "cellWidth": 512,
      "cellHeight": 512,
      "transparentBackground": false,
      "assetNames": ["today-target-cat.png"]
    }
  ]
}
```

四个奖励贴纸：

```json
{
  "prompt": "JOMO 小清新贴纸风，透明背景，四个可爱奖励小贴纸：完成啦、线条更稳、观察很棒、今天也来了。不要生成任何文字，只用图形表达。",
  "sheets": [
    {
      "rows": 2,
      "cols": 2,
      "cellWidth": 256,
      "cellHeight": 256,
      "transparentBackground": true,
      "assetNames": ["sticker-done.png", "sticker-line.png", "sticker-observe.png", "sticker-daily.png"]
    }
  ]
}
```

## Pairing With MiMo Scoring

如果你生成的是今日目标图，后面用户上传作品评分时，调用 `mimo-image-understanding` 必须把目标图作为 `targetImageUrls`：

```json
{
  "mode": "scoring",
  "imageUrls": ["用户上传作品图 URL"],
  "targetImageUrls": ["本 skill 生成并由 JOMO 展示的目标图 URL"],
  "learningGoal": "画一个由圆形和直线组成的可爱杯子",
  "rubric": "判断是否画对、完成度、美观度和一个下次只改一点的建议"
}
```

## Bash Guardrails

Bash 只用于调用 `$GAME_AGENT_SEEDREAM_SCRIPT`。不要用 Bash 读写项目文件、curl 其他地址、打印密钥、手动移动图片或处理 OSS。图片输出目录由 `$GAME_AGENT_DRAFT_ASSETS_DIR` 提供。

## Environment

- `ARK_API_KEY` 必填。
- `GAME_AGENT_DRAFT_ASSETS_DIR` 必填。
- `GAME_AGENT_SEEDREAM_SCRIPT` 必填。
- `SEEDREAM_MODEL` 可选。
- `SEEDREAM_SIZE` 可选，默认 `2K`。

如果生成失败，不要假装已经生成图片。直接用 JOMO 的语气简短说明“图片这次没生成出来”，再给一个无需图片也能完成的小练习。
