# gpt_scoring.py — VLM採点(GPT API)
# 1) 採点表B1〜B5による単体採点(アンカー付きルーブリック)
# 2) 修正前後のペア比較(GPTEval3D方式 + 順序入れ替えで位置バイアス除去)
#
# 環境変数: OPENAI_API_KEY(必須), OPENAI_MODEL(省略時 gpt-4o)
import base64
import json
import os
import re
from pathlib import Path

from openai import OpenAI

MODEL = os.environ.get("OPENAI_MODEL", "gpt-5")
PROMPT_DIR = Path(__file__).parent / "prompts"

_client = None


def client():
    global _client
    if _client is None:
        _client = OpenAI()
    return _client


def _img_part(path):
    b64 = base64.b64encode(Path(path).read_bytes()).decode()
    return {"type": "image_url",
            "image_url": {"url": f"data:image/png;base64,{b64}", "detail": "low"}}


def _extract_json(text):
    """応答からJSONを取り出す(コードブロックで包まれても耐える)"""
    m = re.search(r"\{.*\}", text, re.DOTALL)
    if not m:
        raise ValueError(f"JSONが見つからない: {text[:200]}")
    return json.loads(m.group(0))


def _ask(prompt_text, image_paths, max_retries=3):
    parts = [{"type": "text", "text": prompt_text}] + [_img_part(p) for p in image_paths]
    last_err = None
    for _ in range(max_retries):
        try:
            resp = client().chat.completions.create(
                model=MODEL,
                messages=[{"role": "user", "content": parts}],
            )
            u = resp.usage
            print(f"[usage] in={u.prompt_tokens} out={u.completion_tokens}")
            
            return _extract_json(resp.choices[0].message.content)
        except Exception as e:  # JSON崩れ・一時エラーはリトライ
            last_err = e
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
