#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import os
import sys
from typing import Any
from urllib.error import HTTPError
from urllib.request import Request, urlopen


DEFAULT_BASE_URL = "https://api.xiaomimimo.com/anthropic/v1/messages"
DEFAULT_MODEL = "mimo-v2.5"


def main() -> int:
    args = parse_args()
    try:
        payload = load_payload(args)
        result = understand_image(payload)
    except Exception as error:
        print(json.dumps({"error": str(error)}, ensure_ascii=False), file=sys.stderr)
        return 1
    if args.print_json:
        print(json.dumps(result, ensure_ascii=False, indent=2))
    else:
        print(result["content"])
    return 0


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Analyze image URLs with MiMo multimodal understanding.")
    parser.add_argument("--image-url", action="append", default=[], help="Public image URL. May be repeated.")
    parser.add_argument("--prompt", default="", help="Image analysis prompt.")
    parser.add_argument("--system", default="你是 JOMO 的图片观察助手，反馈短、具体、温柔，不虚构图片细节。")
    parser.add_argument("--model", default=os.getenv("MIMO_IMAGE_MODEL", DEFAULT_MODEL))
    parser.add_argument("--max-tokens", type=int, default=600)
    parser.add_argument("--stdin-json", action="store_true", help="Read {imageUrls,prompt,system,model,maxTokens} from stdin.")
    parser.add_argument("--print-json", action="store_true")
    return parser.parse_args()


def load_payload(args: argparse.Namespace) -> dict[str, Any]:
    if args.stdin_json:
        raw = sys.stdin.read()
        data = json.loads(raw)
        image_urls = data.get("imageUrls") or data.get("image_urls") or []
        target_image_urls = data.get("targetImageUrls") or data.get("target_image_urls") or []
        return {
            "mode": data.get("mode") or "single",
            "imageUrls": image_urls,
            "targetImageUrls": target_image_urls,
            "learningGoal": data.get("learningGoal") or data.get("learning_goal") or "",
            "rubric": data.get("rubric") or "",
            "prompt": data.get("prompt") or args.prompt,
            "system": data.get("system") or args.system,
            "model": data.get("model") or args.model,
            "maxTokens": int(data.get("maxTokens") or data.get("max_tokens") or args.max_tokens),
        }
    return {
        "mode": "single",
        "imageUrls": args.image_url,
        "targetImageUrls": [],
        "learningGoal": "",
        "rubric": "",
        "prompt": args.prompt,
        "system": args.system,
        "model": args.model,
        "maxTokens": args.max_tokens,
    }


def understand_image(payload: dict[str, Any]) -> dict[str, Any]:
    image_urls = [str(url).strip() for url in payload.get("imageUrls") or [] if str(url).strip()]
    target_image_urls = [str(url).strip() for url in payload.get("targetImageUrls") or [] if str(url).strip()]
    prompt = str(payload.get("prompt") or "").strip() or build_prompt(payload, has_targets=bool(target_image_urls))
    if not image_urls:
        raise ValueError("at least one --image-url is required")
    if not prompt:
        raise ValueError("--prompt is required")
    api_key = (
        os.getenv("MIMO_API_KEY")
        or os.getenv("ANTHROPIC_API_KEY")
        or os.getenv("ANTHROPIC_AUTH_TOKEN")
        or ""
    ).strip()
    if not api_key:
        raise RuntimeError("MIMO_API_KEY or ANTHROPIC_API_KEY is required")
    model = str(payload.get("model") or DEFAULT_MODEL)
    body = {
        "model": model,
        "max_tokens": int(payload.get("maxTokens") or 600),
        "system": str(payload.get("system") or ""),
        "messages": [
            {
                "role": "user",
                "content": content_blocks(target_image_urls=target_image_urls, image_urls=image_urls, prompt=prompt),
            }
        ],
    }
    response = post_json(
        normalize_messages_url(os.getenv("MIMO_ANTHROPIC_BASE_URL") or os.getenv("ANTHROPIC_BASE_URL") or DEFAULT_BASE_URL),
        headers={
            "content-type": "application/json",
            "api-key": api_key,
            "x-api-key": api_key,
            "anthropic-version": os.getenv("MIMO_ANTHROPIC_VERSION", "2023-06-01"),
        },
        data=body,
    )
    return {
        "model": response.get("model") or model,
        "content": extract_text(response),
        "imageUrls": image_urls,
        "targetImageUrls": target_image_urls,
        "mode": payload.get("mode") or "single",
        "usage": response.get("usage") or {},
        "id": response.get("id"),
    }


def content_blocks(*, target_image_urls: list[str], image_urls: list[str], prompt: str) -> list[dict[str, Any]]:
    blocks: list[dict[str, Any]] = []
    for index, url in enumerate(target_image_urls, start=1):
        blocks.append({"type": "text", "text": f"目标图/参考图 {index}："})
        blocks.append({"type": "image", "source": {"type": "url", "url": url}})
    blocks.append({"type": "text", "text": "用户作品图："})
    for index, url in enumerate(image_urls, start=1):
        if len(image_urls) > 1:
            blocks.append({"type": "text", "text": f"用户作品图 {index}："})
        blocks.append({"type": "image", "source": {"type": "url", "url": url}})
    blocks.append({"type": "text", "text": prompt})
    return blocks


def build_prompt(payload: dict[str, Any], *, has_targets: bool) -> str:
    mode = str(payload.get("mode") or "single")
    learning_goal = str(payload.get("learningGoal") or "").strip()
    rubric = str(payload.get("rubric") or "").strip()
    parts = [
        "请用中文输出一份很短的图片分析，适合 JOMO 伙伴直接转述给用户。",
    ]
    if learning_goal:
        parts.append(f"今日学习目标：{learning_goal}")
    if rubric:
        parts.append(f"评分标准：{rubric}")
    if mode in {"scoring", "compare"} or has_targets:
        parts.append("请先比较目标图/参考图和用户作品图，判断用户是否画对或动作是否符合目标。")
        parts.append("请给出：1. 你看到的关键差异；2. 是否完成目标；3. 完成度 1-10；4. 美观度或动作质量 1-10；5. 一个下次只改一点的小建议。")
    else:
        parts.append("请给出：1. 图片内容；2. 完成度 1-10；3. 一个做得好的点；4. 一个下次只改一点的小建议。")
    return "\n".join(parts)


def normalize_messages_url(value: str) -> str:
    url = value.rstrip("/")
    if url.endswith("/messages"):
        return url
    if url.endswith("/v1"):
        return f"{url}/messages"
    return f"{url}/v1/messages"


def post_json(url: str, *, headers: dict[str, str], data: dict[str, Any]) -> dict[str, Any]:
    request = Request(
        url,
        method="POST",
        data=json.dumps(data, ensure_ascii=False).encode("utf-8"),
        headers=headers,
    )
    try:
        with urlopen(request, timeout=60) as response:
            return json.loads(response.read().decode("utf-8"))
    except HTTPError as error:
        detail = error.read().decode("utf-8", errors="replace")[:1000]
        raise RuntimeError(f"MiMo image understanding failed: HTTP {error.code}: {detail}") from error


def extract_text(response: dict[str, Any]) -> str:
    parts = []
    for block in response.get("content") or []:
        if isinstance(block, dict) and block.get("type") == "text":
            parts.append(str(block.get("text") or ""))
    return "\n".join(part for part in parts if part).strip()


if __name__ == "__main__":
    raise SystemExit(main())
