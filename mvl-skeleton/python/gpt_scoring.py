# gpt_scoring.py — VLM採点(GPT API)
# 1) 採点表B1〜B5による単体採点(アンカー付きルーブリック)
# 2) 修正前後のペア比較(GPTEval3D方式 + 順序入れ替えで位置バイアス除去)
#
# 環境変数:
#   LLM_KEY / LLM_BASE_URL / LLM_MODEL
#   VLM_STREAM (既定1), VLM_MAX_TOKENS (既定512),
#   VLM_MAX_IMAGE_PX (既定1024、0で縮小なし), VLM_RETRY_DELAY (既定2秒)
import base64
import io
import json
import os
import re
import time
from pathlib import Path   
_envp = Path(__file__).parent / ".env"
if _envp.exists():
    for _l in _envp.read_text(encoding="utf-8-sig").splitlines():
        _l = _l.strip()
        if _l and not _l.startswith("#") and "=" in _l:
            _k, _, _v = _l.partition("=")
            os.environ.setdefault(_k.strip(), _v.strip().strip('"'))

from openai import OpenAI

MODEL = os.environ.get("LLM_MODEL") 
PROMPT_DIR = Path(__file__).parent / "prompts"
MAX_TOKENS = int(os.environ.get("VLM_MAX_TOKENS", "512"))
MAX_IMAGE_PX = int(os.environ.get("VLM_MAX_IMAGE_PX", "1024"))
RETRY_DELAY_SECONDS = float(os.environ.get("VLM_RETRY_DELAY", "2"))
STREAM = os.environ.get("VLM_STREAM", "1").lower() not in ("0", "false", "no")

_client = None

def client():
    global _client
    if _client is None:
        _client = OpenAI(
            api_key=os.environ.get("LLM_KEY") or os.environ.get("OPENAI_API_KEY"),
            base_url=os.environ.get("LLM_BASE_URL") or None,
            default_headers={"User-Agent": "curl/8.5.0"},
        )
    return _client


def _img_part(path, max_px=MAX_IMAGE_PX):
    """画像を必要なら縮小し、OpenAI互換のdata URLにする。"""
    path = Path(path)
    raw = path.read_bytes()
    mime = "image/jpeg" if path.suffix.lower() in (".jpg", ".jpeg") else "image/png"
    if max_px > 0:
        try:
            from PIL import Image
            with Image.open(io.BytesIO(raw)) as image:
                if max(image.size) > max_px:
                    image = image.convert("RGB")
                    image.thumbnail((max_px, max_px))
                    buf = io.BytesIO()
                    image.save(buf, format="JPEG", quality=85, optimize=True)
                    raw = buf.getvalue()
                    mime = "image/jpeg"
        except ImportError as exc:
            raise RuntimeError(
                "画像縮小にはPillowが必要です: pip install -r requirements.txt"
            ) from exc
    b64 = base64.b64encode(raw).decode()
    return {"type": "image_url",
            "image_url": {"url": f"data:{mime};base64,{b64}", "detail": "low"}}


def _extract_json(text):
    """応答からJSONを取り出す(コードブロックで包まれても耐える)"""
    m = re.search(r"\{.*\}", text, re.DOTALL)
    if not m:
        raise ValueError(f"JSONが見つからない: {text[:200]}")
    return json.loads(m.group(0))


def _status_code(exc):
    code = getattr(exc, "status_code", None)
    if code is None:
        code = getattr(getattr(exc, "response", None), "status_code", None)
    if code is not None:
        try:
            return int(code)
        except (TypeError, ValueError):
            pass
    match = re.search(r"\b(408|409|429|5\d\d)\b", str(exc))
    return int(match.group(1)) if match else None


def _is_retryable(exc):
    """混雑・タイムアウト・サーバー障害だけを再試行する。"""
    code = _status_code(exc)
    return code in (408, 409, 429) or (code is not None and 500 <= code <= 599)


def _stream_text(chunks, started_at):
    """ストリームを最後まで読み、本文・usage・最初の文字までの秒数を返す。"""
    text_parts = []
    usage = None
    first_token_seconds = None
    for chunk in chunks:
        chunk_usage = getattr(chunk, "usage", None)
        if chunk_usage is not None:
            usage = chunk_usage
        choices = getattr(chunk, "choices", None) or []
        if not choices:
            continue
        content = getattr(getattr(choices[0], "delta", None), "content", None)
        if not content:
            continue
        if first_token_seconds is None:
            first_token_seconds = time.monotonic() - started_at
        if isinstance(content, str):
            text_parts.append(content)
        else:
            # 一部のOpenAI互換実装がcontent partの配列を返す場合に備える。
            for part in content:
                value = getattr(part, "text", None)
                if value:
                    text_parts.append(value)
    return "".join(text_parts), usage, first_token_seconds


def _usage_text(usage):
    if usage is None:
        return "usage=unavailable"
    return "in=%s out=%s" % (
        getattr(usage, "prompt_tokens", "?"),
        getattr(usage, "completion_tokens", "?"),
    )


def _ask(prompt_text, image_paths, max_retries=3, sleep=time.sleep):
    parts = [{"type": "text", "text": prompt_text}] + [_img_part(p) for p in image_paths]
    payload_mb = sum(
        len(part["image_url"]["url"])
        for part in parts if part.get("type") == "image_url"
    ) / 1_000_000
    print(f"[vlm] images={len(image_paths)} payload={payload_mb:.2f}MB "
          f"stream={STREAM} max_tokens={MAX_TOKENS}")
    last_err = None
    for attempt in range(max_retries):
        started_at = time.monotonic()
        try:
            resp = client().chat.completions.create(
                model=MODEL,
                messages=[{"role": "user", "content": parts}],
                reasoning_effort="none",
                max_tokens=MAX_TOKENS,
                stream=STREAM,
            )
            if STREAM:
                text, usage, first_token = _stream_text(resp, started_at)
            else:
                text = resp.choices[0].message.content
                usage = getattr(resp, "usage", None)
                first_token = None
            total = time.monotonic() - started_at
            ttft = f"{first_token:.1f}s" if first_token is not None else "n/a"
            print(f"[vlm] ttft={ttft} total={total:.1f}s {_usage_text(usage)}")
            return _extract_json(text)
        except (ValueError, json.JSONDecodeError) as e:
            # JSON崩れは一時的な生成失敗として再試行する。
            last_err = e
            retryable = True
        except Exception as e:
            last_err = e
            retryable = _is_retryable(e)
        if not retryable or attempt + 1 >= max_retries:
            break
        delay = RETRY_DELAY_SECONDS * (2 ** attempt)
        print(f"[vlm] retry={attempt + 1}/{max_retries - 1} "
              f"wait={delay:g}s error={last_err}")
        sleep(delay)
    raise RuntimeError(f"VLM呼び出し失敗: {last_err}")


def score_scene(image_paths, scene):
    """採点表B1〜B5でシーンを採点。戻り値: {"B1"..."B5", "total", "worst_object", ...}"""
    tmpl = (PROMPT_DIR / "rubric_prompt.txt").read_text(encoding="utf-8")
    object_list = ", ".join(f"{o['id']}({o['class']})" for o in scene["objects"])
    prompt = tmpl.format(

        space_type=scene["spec"].get("space_type", ""),
        theme=scene["spec"].get("theme", ""),
        object_list=object_list,
    )
    result = _ask(prompt, image_paths)
    keys = ["B1", "B2", "B3", "B4", "B5"]
    result["total"] = sum(float(result.get(k, 0)) for k in keys)
    result["mean"] = result["total"] / len(keys)
    return result


def pairwise(images_a, images_b, scene):
    """修正前(A)と修正後(B)のペア比較。順序を入れ替えて2回聞き、一致した時だけ勝敗を確定。
    戻り値: "A" | "B" | "tie"
    """
    tmpl = (PROMPT_DIR / "pairwise_prompt.txt").read_text(encoding="utf-8")
    prompt = tmpl.format(space_type=scene["spec"].get("space_type", ""),
                         n_views=len(images_a))
    r1 = _ask(prompt, list(images_a) + list(images_b))  # 1回目: A=前, B=後
    r2 = _ask(prompt, list(images_b) + list(images_a))  # 2回目: 順序反転
    w1 = r1.get("winner", "tie")
    w2 = r2.get("winner", "tie")
    w2_mapped = {"A": "B", "B": "A"}.get(w2, "tie")  # 反転分を戻す
    if w1 == w2_mapped and w1 in ("A", "B"):
        return w1
    return "tie"


if __name__ == "__main__":
    import argparse
    ap = argparse.ArgumentParser(description="撮影画像のVLM採点")
    ap.add_argument("scene_json")
    ap.add_argument("capture_dir")
    args = ap.parse_args()
    scene = json.loads(Path(args.scene_json).read_text(encoding="utf-8"))
    imgs = sorted(Path(args.capture_dir).glob("view_*.png"))
    print(json.dumps(score_scene(imgs, scene), ensure_ascii=False, indent=2))
