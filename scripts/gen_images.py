#!/usr/bin/env python3
import argparse
import base64
import json
import mimetypes
import os
import re
import sys
import tomllib
import urllib.error
import urllib.parse
import urllib.request
from datetime import datetime
from pathlib import Path


REQUEST_TIMEOUT_SECONDS = 600


def fail(message: str, status_code: int = 1):
    print(json.dumps({"ok": False, "error": message}, ensure_ascii=False))
    sys.exit(status_code)


def load_json(path: Path, label: str):
    if not path.exists():
        raise RuntimeError(f"未找到配置文件: {path}")

    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception as exc:
        raise RuntimeError(f"读取{label}失败: {exc}") from exc


def load_toml(path: Path, label: str):
    if not path.exists():
        raise RuntimeError(f"未找到配置文件: {path}")

    try:
        return tomllib.loads(path.read_text(encoding="utf-8"))
    except Exception as exc:
        raise RuntimeError(f"读取{label}失败: {exc}") from exc


def load_claude_settings():
    settings_path = Path.home() / ".claude" / "settings.json"
    data = load_json(settings_path, "Claude settings.json")

    env = data.get("env") or {}
    base_url = env.get("ANTHROPIC_BASE_URL")
    token = env.get("ANTHROPIC_AUTH_TOKEN")

    if not base_url:
        raise RuntimeError("settings.json 中缺少 env.ANTHROPIC_BASE_URL")
    if not token:
        raise RuntimeError("settings.json 中缺少 env.ANTHROPIC_AUTH_TOKEN")

    return base_url.rstrip("/"), token


def load_codex_settings():
    config_path = Path.home() / ".codex" / "config.toml"
    auth_path = Path.home() / ".codex" / "auth.json"

    config = load_toml(config_path, "Codex config.toml")
    auth = load_json(auth_path, "Codex auth.json") if auth_path.exists() else {}

    model_providers = config.get("model_providers") or {}
    active_provider_name = config.get("model_provider")
    active_provider = model_providers.get(active_provider_name) or {}
    openai_provider = model_providers.get("OpenAI") or model_providers.get("openai") or {}
    base_url = (
        active_provider.get("base_url")
        or openai_provider.get("base_url")
        or os.environ.get("OPENAI_BASE_URL")
        or auth.get("OPENAI_BASE_URL")
    )
    env_key = active_provider.get("env_key") or openai_provider.get("env_key")
    token = (
        (os.environ.get(str(env_key)) if env_key else None)
        or os.environ.get("OPENAI_API_KEY")
        or auth.get("OPENAI_API_KEY")
    )

    if not base_url:
        raise RuntimeError("Codex 配置中缺少图片接口 base_url")
    if not token:
        raise RuntimeError("Codex 配置中缺少图片接口 API token")

    return str(base_url).rstrip("/"), str(token)


def detect_caller_from_script_dir():
    current = Path(__file__).resolve().parent
    directories = (current, *current.parents)

    for directory in directories:
        if directory.name == ".codex":
            return "codex"

    for directory in directories:
        if directory.name == ".claude":
            return "claude"

    return None


def load_runtime_settings():
    caller = detect_caller_from_script_dir()
    if caller == "claude":
        base_url, token = load_claude_settings()
        return caller, base_url, token
    if caller == "codex":
        base_url, token = load_codex_settings()
        return caller, base_url, token

    errors = []
    for name, loader in (("claude", load_claude_settings), ("codex", load_codex_settings)):
        try:
            base_url, token = loader()
            return name, base_url, token
        except RuntimeError as exc:
            errors.append(f"{name}: {exc}")

    raise RuntimeError("; ".join(errors))


def build_api_url(caller: str, base_url: str, mode: str):
    endpoint = "/images/generations" if mode == "generate" else "/images/edits"
    normalized_base_url = base_url.rstrip("/")
    if normalized_base_url.endswith("/v1"):
        return f"{normalized_base_url}{endpoint}"
    return f"{normalized_base_url}/v1{endpoint}"


def guess_mime(path: Path):
    mime, _ = mimetypes.guess_type(str(path))
    return mime or "application/octet-stream"


def file_to_data_url(path_str: str):
    path = Path(path_str)
    if not path.exists():
        fail(f"图片文件不存在: {path_str}")
    data = path.read_bytes()
    mime = guess_mime(path)
    b64 = base64.b64encode(data).decode("ascii")
    return f"data:{mime};base64,{b64}"


DATA_URL_RE = re.compile(r"^data:(?P<mime>[^;]+);base64,(?P<data>.+)$", re.IGNORECASE)


def parse_data_url(data_url: str):
    match = DATA_URL_RE.match(data_url)
    if not match:
        fail("返回的 data URL 格式无效")
    mime = match.group("mime")
    raw = match.group("data")
    try:
        data = base64.b64decode(raw)
    except Exception as exc:
        fail(f"解析返回图片失败: {exc}")
    return mime, data


def choose_extension(output_format: str | None, mime: str | None = None):
    if output_format:
        normalized = output_format.lower()
        if normalized == "jpeg":
            return "jpg"
        return normalized
    if mime:
        ext = mimetypes.guess_extension(mime)
        if ext:
            return ext.lstrip(".").replace("jpe", "jpg")
    return "png"


def ensure_output_dir():
    output_dir = Path.cwd() / "gen-images"
    output_dir.mkdir(parents=True, exist_ok=True)
    return output_dir


def save_images(image_entries, output_format: str | None):
    output_dir = ensure_output_dir()
    timestamp = datetime.now().strftime("%Y%m%d-%H%M%S")
    paths = []

    for index, item in enumerate(image_entries, start=1):
        ext = choose_extension(output_format)
        if item.get("b64_json"):
            try:
                binary = base64.b64decode(item["b64_json"])
            except Exception as exc:
                fail(f"解码返回图片失败: {exc}")
        elif item.get("url", "").startswith("data:"):
            mime, binary = parse_data_url(item["url"])
            ext = choose_extension(output_format, mime)
        else:
            fail("接口返回中未找到可保存的图片数据")

        file_path = output_dir / f"{timestamp}-{index:02d}.{ext}"
        file_path.write_bytes(binary)
        paths.append(str(file_path))

    return paths


def post_json(url: str, token: str, payload: dict, timeout_seconds: int = REQUEST_TIMEOUT_SECONDS):
    body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
    req = urllib.request.Request(
        url,
        data=body,
        method="POST",
        headers={
            "Content-Type": "application/json",
            "Authorization": f"Bearer {token}",
        },
    )
    try:
        with urllib.request.urlopen(req, timeout=timeout_seconds) as response:
            return json.loads(response.read().decode("utf-8"))
    except urllib.error.HTTPError as exc:
        try:
            raw = exc.read().decode("utf-8")
            data = json.loads(raw)
            message = data.get("error", {}).get("message") or data.get("message") or raw
        except Exception:
            message = exc.reason or f"HTTP {exc.code}"
        fail(f"接口调用失败: {message}")
    except TimeoutError:
        fail(f"图片生成超时（{timeout_seconds} 秒）")
    except urllib.error.URLError as exc:
        if isinstance(exc.reason, TimeoutError):
            fail(f"图片生成超时（{timeout_seconds} 秒）")
        fail(f"网络请求失败: {exc.reason}")


def build_generation_payload(args):
    if not args.prompt:
        fail("缺少 prompt")

    payload = {
        "model": args.model or "gpt-image-2",
        "prompt": args.prompt,
        "response_format": "b64_json",
        "stream": False,
        "n": args.n or 1,
    }

    optional_fields = [
        "size",
        "quality",
        "background",
        "output_format",
        "output_compression",
        "partial_images",
        "moderation",
    ]
    for field in optional_fields:
        value = getattr(args, field, None)
        if value is not None:
            payload[field] = value
    return payload


def build_edit_payload(args):
    if not args.prompt:
        fail("缺少 prompt")
    if not args.image:
        fail("缺少要编辑的图片来源")

    image_value = args.image
    if not image_value.startswith("http://") and not image_value.startswith("https://") and not image_value.startswith("data:"):
        image_value = file_to_data_url(image_value)

    payload = {
        "model": args.model or "gpt-image-2",
        "prompt": args.prompt,
        "images": [{"image_url": image_value}],
        "response_format": "b64_json",
        "stream": False,
        "n": args.n or 1,
    }

    if args.mask:
        mask_value = args.mask
        if not mask_value.startswith("http://") and not mask_value.startswith("https://") and not mask_value.startswith("data:"):
            mask_value = file_to_data_url(mask_value)
        payload["mask"] = {"image_url": mask_value}

    optional_fields = [
        "size",
        "quality",
        "background",
        "output_format",
        "output_compression",
        "partial_images",
        "moderation",
        "input_fidelity",
    ]
    for field in optional_fields:
        value = getattr(args, field, None)
        if value is not None:
            payload[field] = value
    return payload


def parse_args():
    parser = argparse.ArgumentParser()
    parser.add_argument("--mode", choices=["generate", "edit"], required=True)
    parser.add_argument("--prompt")
    parser.add_argument("--model")
    parser.add_argument("--image")
    parser.add_argument("--mask")
    parser.add_argument("--size")
    parser.add_argument("--quality")
    parser.add_argument("--background")
    parser.add_argument("--output-format", dest="output_format")
    parser.add_argument("--output-compression", dest="output_compression", type=int)
    parser.add_argument("--partial-images", dest="partial_images", type=int)
    parser.add_argument("--n", type=int)
    parser.add_argument("--moderation")
    parser.add_argument("--input-fidelity", dest="input_fidelity")
    return parser.parse_args()


def main():
    args = parse_args()
    try:
        caller, base_url, token = load_runtime_settings()
    except RuntimeError as exc:
        fail(str(exc))

    if args.mode == "generate":
        payload = build_generation_payload(args)
    else:
        payload = build_edit_payload(args)

    url = build_api_url(caller, base_url, args.mode)

    response = post_json(url, token, payload)
    data = response.get("data")
    if not isinstance(data, list) or not data:
        fail("接口返回中缺少 data")

    used_params = {
        "model": payload.get("model", "gpt-image-2"),
        "size": payload.get("size"),
        "quality": payload.get("quality"),
        "background": payload.get("background"),
        "output_format": payload.get("output_format") or "png",
        "n": payload.get("n", 1),
    }
    if args.mode == "edit" and payload.get("input_fidelity") is not None:
        used_params["input_fidelity"] = payload.get("input_fidelity")

    paths = save_images(data, payload.get("output_format"))
    print(json.dumps({"ok": True, "paths": paths, "used_params": used_params}, ensure_ascii=False))


if __name__ == "__main__":
    main()
