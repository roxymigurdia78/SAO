# gpt_scoring.py — VLM採点(GPT API)
# 1) 採点表B1〜B5による単体採点(アンカー付きルーブリック)
# 2) 修正前後のペア比較(GPTEval3D方式 + 順序入れ替えで位置バイアス除去)
#
# 環境変数:
#   LLM_KEY / LLM_BASE_URL / LLM_MODEL
#   VLM_STREAM (既定1), VLM_MAX_TOKENS (既定1024),
#   VLM_MAX_IMAGE_PX (既定1024、0で縮小なし), VLM_RETRY_DELAY (既定2秒)
import base64
import io
import json
import math
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
MAX_TOKENS = int(os.environ.get("VLM_MAX_TOKENS", "1024"))
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


def _print_usage(usage):
    """従来のログ形式を保ち、usage非対応サーバーでも落とさない。"""
    prompt_tokens = getattr(usage, "prompt_tokens", None) if usage else None
    completion_tokens = (
        getattr(usage, "completion_tokens", None) if usage else None)
    print(f"[usage] in={prompt_tokens} out={completion_tokens}")


def _ask(prompt_text, image_paths, max_retries=3, sleep=time.sleep,
         validator=None, return_none_on_failure=False):
    parts = [{"type": "text", "text": prompt_text}] + [_img_part(p) for p in image_paths]
    payload_mb = sum(
        len(part["image_url"]["url"])
        for part in parts if part.get("type") == "image_url"
    ) / 1_000_000
    print(f"[vlm] images={len(image_paths)} payload={payload_mb:.2f}MB "
          f"stream={STREAM} max_tokens={MAX_TOKENS}")
    last_err = None
    can_return_none = False
    for attempt in range(max_retries):
        started_at = time.monotonic()
        try:
            request = dict(
                model=MODEL,
                messages=[{"role": "user", "content": parts}],
                reasoning_effort="none",
                max_tokens=MAX_TOKENS,
                stream=STREAM,
            )
            # OpenAI互換APIはこれを指定した場合、最終チャンクにusageを返す。
            if STREAM:
                request["stream_options"] = {"include_usage": True}
            resp = client().chat.completions.create(**request)
            if STREAM:
                text, usage, first_token = _stream_text(resp, started_at)
            else:
                text = resp.choices[0].message.content
                usage = getattr(resp, "usage", None)
                first_token = None
            total = time.monotonic() - started_at
            ttft = f"{first_token:.1f}s" if first_token is not None else "n/a"
            print(f"[vlm] ttft={ttft} total={total:.1f}s {_usage_text(usage)}")
            _print_usage(usage)
            result = _extract_json(text)
            return validator(result) if validator else result
        except (ValueError, json.JSONDecodeError) as e:
            # JSON崩れ・採点範囲外は一時的な生成失敗として再試行する。
            last_err = e
            retryable = True
            can_return_none = True
        except Exception as e:
            last_err = e
            retryable = _is_retryable(e)
            can_return_none = retryable
        if not retryable or attempt + 1 >= max_retries:
            break
        delay = RETRY_DELAY_SECONDS * (2 ** attempt)
        print(f"[vlm] retry={attempt + 1}/{max_retries - 1} "
              f"wait={delay:g}s error={last_err}")
        sleep(delay)
    if return_none_on_failure and can_return_none:
        print(f"[vlm] 採点不能: {max_retries}回失敗したためスコアをNoneで継続 "
              f"error={last_err}")
        return None
    raise RuntimeError(f"VLM呼び出し失敗: {last_err}")


def _validate_scores(result):
    """B1〜B5が数学的な整数1〜5であることを確認し、intへ正規化する。"""
    if not isinstance(result, dict):
        raise ValueError("採点応答がJSONオブジェクトではない")
    normalized = dict(result)
    invalid = []
    for key in ("B1", "B2", "B3", "B4", "B5"):
        value = result.get(key)
        valid = (isinstance(value, (int, float))
                 and not isinstance(value, bool)
                 and math.isfinite(float(value))
                 and float(value).is_integer()
                 and 1 <= int(value) <= 5)
        if not valid:
            invalid.append(f"{key}={value!r}")
        else:
            normalized[key] = int(value)
    if invalid:
        raise ValueError("採点範囲外(1〜5の整数のみ): " + ", ".join(invalid))
    return normalized


def score_scene(image_paths, scene, max_retries=3, sleep=time.sleep):
    """採点表B1〜B5で採点する。全試行が不正ならNone。"""
    tmpl = (PROMPT_DIR / "rubric_prompt.txt").read_text(encoding="utf-8")
    object_list = ", ".join(f"{o['id']}({o['class']})" for o in scene["objects"])
    prompt = tmpl.format(

        space_type=scene["spec"].get("space_type", ""),
        theme=scene["spec"].get("theme", ""),
        object_list=object_list,
    )
    result = _ask(
        prompt, image_paths, max_retries=max_retries, sleep=sleep,
        validator=_validate_scores, return_none_on_failure=True)
    if result is None:
        return None
    keys = ["B1", "B2", "B3", "B4", "B5"]
    result["total"] = sum(float(result.get(k, 0)) for k in keys)
    result["mean"] = result["total"] / len(keys)
    return result


DETAIL_KINDS = {
    "floating", "penetration", "orientation", "scale",
    "functional_relation",
}
DETAIL_REPAIRS = {
    "snap_to_support", "orient_to_target", "move_near", "rescale",
    "swap_variant", "none",
}


def _detail_context(scene, object_id, nearby_limit=8):
    """詳細監査用に宣言関係と近傍候補を決定的に列挙する。"""
    objects = {o.get("id"): o for o in scene.get("objects", [])}
    obj = objects.get(object_id)
    if obj is None:
        raise ValueError(f"シーンに対象IDがない: {object_id}")

    relations = []
    related_ids = []
    if obj.get("rests_on"):
        relations.append(f"rests_on={obj['rests_on']}")
        related_ids.append(obj["rests_on"])
    faces = obj.get("faces")
    faces_id = faces.get("target") if isinstance(faces, dict) else faces
    if faces_id:
        relations.append(f"faces={faces_id}")
        related_ids.append(faces_id)
    near = obj.get("near")
    if isinstance(near, dict) and near.get("target"):
        relations.append(
            f"near={near['target']} (max={near.get('max_distance')}m)")
        related_ids.append(near["target"])

    position = obj.get("position") or [0, 0, 0]
    nearby = []
    for other in scene.get("objects", []):
        if other.get("id") == object_id:
            continue
        other_position = other.get("position") or [0, 0, 0]
        distance = math.hypot(
            float(other_position[0]) - float(position[0]),
            float(other_position[2]) - float(position[2]))
        nearby.append((distance, other.get("id"), other.get("class", "")))
    nearby.sort(key=lambda item: (item[0], str(item[1])))
    nearby = nearby[:nearby_limit]

    allowed_ids = {object_id}
    allowed_ids.update(value for value in related_ids if value in objects)
    allowed_ids.update(value for _, value, _ in nearby if value in objects)
    relation_text = ", ".join(relations) if relations else "なし"
    nearby_text = ", ".join(
        f"{oid}({cls}, {distance:.2f}m)"
        for distance, oid, cls in nearby)
    return obj, relation_text, nearby_text or "なし", allowed_ids


def _validate_detail_audit(result, expected_id, allowed_ids, image_count):
    if not isinstance(result, dict):
        raise ValueError("詳細監査応答がJSONオブジェクトではない")
    if result.get("object_id") != expected_id:
        raise ValueError(
            f"詳細監査のobject_id不一致: {result.get('object_id')!r}")
    status = result.get("status")
    if status not in ("pass", "fail", "uncertain"):
        raise ValueError(f"詳細監査のstatusが不正: {status!r}")

    normalized_findings = []
    findings = result.get("findings", [])
    if not isinstance(findings, list):
        raise ValueError("詳細監査のfindingsが配列ではない")
    for finding in findings:
        if not isinstance(finding, dict):
            raise ValueError("詳細監査のfindingがオブジェクトではない")
        kind = finding.get("kind")
        if kind not in DETAIL_KINDS:
            raise ValueError(f"詳細監査のkindが不正: {kind!r}")
        target_id = finding.get("target_id")
        if target_id is not None and target_id not in allowed_ids:
            raise ValueError(f"存在しない周辺target_id: {target_id!r}")
        repair_name = finding.get("suggested_repair", "none")
        if repair_name not in DETAIL_REPAIRS:
            raise ValueError(f"詳細監査のsuggested_repairが不正: {repair_name!r}")
        try:
            confidence = float(finding.get("confidence"))
        except (TypeError, ValueError):
            raise ValueError("詳細監査のconfidenceが数値ではない")
        if not math.isfinite(confidence) or not 0.0 <= confidence <= 1.0:
            raise ValueError(f"詳細監査のconfidenceが範囲外: {confidence!r}")
        normalized_findings.append({
            "kind": kind,
            "target_id": target_id,
            "confidence": confidence,
            "detail": str(finding.get("detail", "")),
            "suggested_repair": repair_name,
        })
    if status == "pass" and normalized_findings:
        raise ValueError("passなのにfindingsが存在する")
    if status == "fail" and not normalized_findings:
        raise ValueError("failなのにfindingsが空")

    evidence = result.get("evidence_views", [])
    if not isinstance(evidence, list) or any(
            not isinstance(index, int) or isinstance(index, bool)
            or index < 0 or index >= image_count for index in evidence):
        raise ValueError("詳細監査のevidence_viewsが不正")
    return {
        "object_id": expected_id,
        "status": status,
        "findings": normalized_findings,
        "evidence_views": evidence,
    }


def audit_scene_details(detail_captures, capture_dir, scene,
                        max_retries=3, sleep=time.sleep):
    """全オブジェクトを個別に監査する。1対象=1リクエストで注意希釈を避ける。"""
    template = (PROMPT_DIR / "detail_audit_prompt.txt").read_text(
        encoding="utf-8")
    capture_dir = Path(capture_dir)
    audits = []
    for detail in detail_captures or []:
        object_id = detail.get("object_id")
        obj, relations, nearby, allowed_ids = _detail_context(
            scene, object_id)
        image_paths = [capture_dir / value for value in detail.get("files", [])]
        image_paths = [path for path in image_paths if path.is_file()]
        if not image_paths:
            audits.append({
                "object_id": object_id,
                "status": "uncertain",
                "findings": [],
                "evidence_views": [],
                "error": "detail_images_missing",
            })
            continue
        prompt = template.format(
            object_id=object_id,
            object_class=obj.get("class", ""),
            declared_relations=relations,
            nearby_objects=nearby,
        )
        validator = lambda value, oid=object_id, ids=allowed_ids, n=len(image_paths): (
            _validate_detail_audit(value, oid, ids, n))
        result = _ask(
            prompt, image_paths, max_retries=max_retries, sleep=sleep,
            validator=validator, return_none_on_failure=True)
        if result is None:
            result = {
                "object_id": object_id,
                "status": "uncertain",
                "findings": [],
                "evidence_views": [],
                "error": "vlm_invalid_after_retries",
            }
        audits.append(result)
    return audits


def detail_defects(audits, min_confidence=0.8):
    """明確なfailだけを既存の安全な修復経路へ渡す。"""
    defects = []
    for audit in audits or []:
        if audit.get("status") != "fail":
            continue
        for finding in audit.get("findings", []):
            if float(finding.get("confidence", 0.0)) < min_confidence:
                continue
            defect = dict(finding)
            defect["id"] = audit.get("object_id")
            defect["source"] = "detail_vlm"
            defects.append(defect)
    return defects


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
