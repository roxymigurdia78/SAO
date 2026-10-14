"""写真の山に GPT でタグを付けて、写真データベース（tags.jsonl）を作る

目的: 物差しを「世界設定（天気・時間など）に合う実写」だけから作れるようにする。
      1回タグを付けておけば、あとは条件で絞り込むだけ（photo_search.py）。
      将来の写真検索も、この tags.jsonl を土台にする（id で他の情報とつなげる）。

使い方（sao フォルダで）:
  python mvl-skeleton\\python\\photo_db.py --backend openai --limit 20 --reasoning minimal   # GPT で20枚お試し
  python mvl-skeleton\\python\\photo_db.py --backend hpc --limit 20                         # KambeHPC の Qwen で20枚
  python mvl-skeleton\\python\\photo_db.py --backend openai --categories home_office bedroom

  ・キー・URL・モデル名は .env から読む（openai: OPENAI_API_KEY / OPENAI_API_MODEL,
                                         hpc:    LLM_KEY / LLM_BASE_URL / LLM_MODEL）
  ・途中で止めても、同じコマンドをもう一度打てば続きから（付け済みの写真は飛ばす）
  ・モデルごとに別ファイルに貯める → GPT と Qwen のタグを比べられる

出力: research\\photo_db\\tags_<モデル名>.jsonl（1行＝写真1枚）
      research\\photo_db\\errors.log（失敗した写真）
"""
import os
import re
import argparse
import base64
import json
import threading
import time
from collections import Counter
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime
from pathlib import Path

import numpy as np
from openai import OpenAI

SAO = Path(__file__).resolve().parents[2]
DATA = SAO / "research" / "data_256"                 # data_256/<頭文字>/<カテゴリ>/*.jpg
DB_DIR = SAO / "research" / "photo_db"


# ======================================================================
# 0. 接続先（.env を読む → OpenAI か KambeHPC か）
# ======================================================================
def load_env():
    """.env を探して環境変数に入れる（すでにある値は上書きしない）"""
    here = Path(__file__).resolve().parent
    for p in [Path.cwd() / ".env", here / ".env", SAO / "mvl-skeleton" / ".env", SAO / ".env"]:
        if p.exists():
            for line in p.read_text(encoding="utf-8").splitlines():
                if "=" in line and not line.lstrip().startswith("#"):
                    k, v = line.split("=", 1)
                    os.environ.setdefault(k.strip(), v.strip().strip('"').strip("'"))
            return p
    return None


def make_client(backend, model=None):
    """(client, モデル名) を返す。KambeHPC は OpenAI 互換なので同じ書き方で呼べる"""
    load_env()
    if backend == "openai":
        return OpenAI(api_key=os.environ["OPENAI_API_KEY"]), model or os.environ.get("OPENAI_API_MODEL")
    if backend == "hpc":
        return (OpenAI(api_key=os.environ["LLM_KEY"], base_url=os.environ["LLM_BASE_URL"]),
                model or os.environ.get("LLM_MODEL"))
    raise SystemExit(f"backend は openai か hpc: {backend}")


def db_path(model):
    return DB_DIR / f"tags_{re.sub(r'[^A-Za-z0-9._-]', '_', model)}.jsonl"   # qwen3.5:35b → qwen3.5_35b

# ======================================================================
# 1. タグの項目（選択肢を固定する → あとで「天気=曇り」のように絞り込める）
# ======================================================================
TAGS = {
    "photo_type":       ["real_photo", "cg_render", "not_indoor_room"],  # CG は物差しから外すため
    "time":             ["day", "dusk", "night", "unknown"],
    "weather":          ["sunny", "overcast", "rainy", "unknown"],
    "window_visible":   ["yes", "no"],
    "sun_patches":      ["yes", "no"],          # 床や壁に日なたの形が落ちているか（＝メリハリ強い）
    "main_light":       ["daylight", "artificial", "mixed"],
    "artificial_color": ["warm", "neutral", "cool", "none"],
    "style":            ["modern", "traditional", "industrial", "scandinavian", "rustic", "other"],
}

PROMPT = """You label indoor room photos for a lighting study.
Judge only from what is visible. If you cannot tell, answer "unknown" (or the closest neutral option).
- photo_type: real_photo / cg_render (3D rendering, game, catalog CG) / not_indoor_room
- time: time of day judged from window light or outside view; "unknown" if no evidence
- weather: only if the outside is visible or direct sunlight clearly shows it; otherwise "unknown"
- sun_patches: "yes" only if sharp patches of direct sunlight fall on floor/walls/furniture
- main_light: what mainly lights the room
- artificial_color: color of the lamps/ceiling lights if any are on; "none" if none are on
- style: interior style
- caption: one short English sentence describing the room and its lighting
- confidence: how sure you are about time/weather/main_light overall"""


def response_format():
    props = {k: {"type": "string", "enum": v} for k, v in TAGS.items()}
    props["caption"] = {"type": "string"}
    props["confidence"] = {"type": "string", "enum": ["low", "medium", "high"]}
    return {"type": "json_schema",
            "json_schema": {"name": "photo_tags", "strict": True,
                            "schema": {"type": "object", "properties": props,
                                       "required": list(props), "additionalProperties": False}}}


# ======================================================================
# 2. 1枚にタグを付ける
# ======================================================================
def parse_tags(text):
    """返事から JSON を取り出し、選択肢の外の値がないか確かめる（Qwen は前に考えた文が付くことがある）"""
    text = text[text.find("{"): text.rfind("}") + 1]
    tags = json.loads(text)
    for k, choices in TAGS.items():
        if tags.get(k) not in choices:
            raise ValueError(f"{k}={tags.get(k)!r} は選択肢の外")
    return tags


def tag_one(client, model, path, reasoning, use_schema=True):
    b64 = base64.b64encode(path.read_bytes()).decode()
    kw = {"reasoning_effort": reasoning} if reasoning else {}   # GPT-5 系だけ。temperature は付けない
    if use_schema:
        kw["response_format"] = response_format()              # 選択肢を API 側で強制
    for attempt in range(4):
        try:
            r = client.chat.completions.create(
                model=model, **kw,
                messages=[{"role": "system", "content": PROMPT + "\nAnswer with JSON only. Allowed values: "
                           + json.dumps(TAGS) + ' plus "caption" (string) and "confidence" (low/medium/high).'},
                          {"role": "user", "content": [{"type": "image_url", "image_url": {
                              "url": f"data:image/jpeg;base64,{b64}", "detail": "low"}}]}])
            tags = parse_tags(r.choices[0].message.content)
            u = r.usage
            return tags, ((u.prompt_tokens, u.completion_tokens) if u else (0, 0))
        except Exception:
            if attempt == 3:
                raise
            time.sleep(5 * 2 ** attempt)                  # 5, 10, 20 秒待ってやり直す


# ======================================================================
# 3. どの写真に付けるか
# ======================================================================
def list_photos(categories, sample, seed):
    out = []
    for c in categories:
        files = sorted((DATA / c[0] / c).glob("*.jpg"))
        if not files:
            raise SystemExit(f"写真が見つかりません: {DATA / c[0] / c}")
        if sample and sample < len(files):
            idx = np.random.default_rng(seed).choice(len(files), size=sample, replace=False)
            files = [files[i] for i in sorted(idx)]
        out += [(c, f) for f in files]
    return out


def photo_id(path):
    return path.relative_to(DATA).as_posix()             # 例: h/home_office/00000001.jpg


def read_db(path):
    path = Path(path)
    if not path.exists():
        return []
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]


# ======================================================================
# 4. 本体
# ======================================================================
def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--backend", required=True, choices=["openai", "hpc"], help="openai=GPT / hpc=KambeHPC の LLM API")
    ap.add_argument("--model", help="省略時は .env の OPENAI_API_MODEL / LLM_MODEL")
    ap.add_argument("--categories", nargs="+", default=["home_office"])
    ap.add_argument("--sample", type=int, help="カテゴリごとに何枚に付けるか（省略時は全部）")
    ap.add_argument("--seed", type=int, default=0)
    ap.add_argument("--limit", type=int, help="今回は何枚まで（試し用）")
    ap.add_argument("--workers", type=int, default=4, help="同時に投げる数（hpc は 1〜2 が無難）")
    ap.add_argument("--reasoning", help="GPT-5 なら minimal / low を指定すると安く速い（hpc では付けない）")
    ap.add_argument("--no-schema", action="store_true", help="選択肢の強制(json_schema)が通らない相手用")
    a = ap.parse_args()

    client, model = make_client(a.backend, a.model)
    if not model:
        raise SystemExit("モデル名がありません（--model か .env）")
    db = db_path(model)
    DB_DIR.mkdir(parents=True, exist_ok=True)
    done = {r["id"] for r in read_db(db)}
    todo = [(c, p) for c, p in list_photos(a.categories, a.sample, a.seed) if photo_id(p) not in done]
    if a.limit:
        todo = todo[:a.limit]
    print(f"backend={a.backend}  model={model}  出力={db.name}")
    print(f"付け済み {len(done)} 枚 / 今回 {len(todo)} 枚")
    if not todo:
        return

    def work(c, p):
        tags, tok = tag_one(client, model, p, a.reasoning, use_schema=not a.no_schema)
        return {"id": photo_id(p), "category": c, "tags": tags, "model": model, "backend": a.backend,
                "tokens": list(tok), "time": datetime.now().isoformat(timespec="seconds")}

    # 最初の1枚だけ先に試す（キー・URL・画像が通るかをすぐ確かめる）
    try:
        first = work(*todo[0])
    except Exception as e:
        raise SystemExit(f"最初の1枚で失敗しました。設定を確認してください:\n  {e!r}")
    print("1枚目:", json.dumps(first["tags"], ensure_ascii=False))

    lock = threading.Lock()
    tok_in, tok_out, n_ok, n_err = first["tokens"][0], first["tokens"][1], 1, 0
    with ThreadPoolExecutor(a.workers) as ex, open(db, "a", encoding="utf-8") as f:
        f.write(json.dumps(first, ensure_ascii=False) + "\n")
        futs = {ex.submit(work, c, p): p for c, p in todo[1:]}
        for fut in as_completed(futs):
            with lock:
                try:
                    row = fut.result()
                    f.write(json.dumps(row, ensure_ascii=False) + "\n")
                    f.flush()
                    tok_in += row["tokens"][0]; tok_out += row["tokens"][1]; n_ok += 1
                except Exception as e:
                    n_err += 1
                    with open(DB_DIR / "errors.log", "a", encoding="utf-8") as g:
                        g.write(f"{model}\t{photo_id(futs[fut])}\t{e!r}\n")
                if (n_ok + n_err) % 20 == 0:
                    print(f"  {n_ok + n_err}/{len(todo)}  失敗 {n_err}  トークン 入{tok_in} 出{tok_out}")

    print(f"\n完了: 成功 {n_ok}  失敗 {n_err}")
    print(f"トークン: 入力 {tok_in}（1枚平均 {tok_in / n_ok:.0f}）  出力 {tok_out}（1枚平均 {tok_out / n_ok:.0f}）")
    if a.backend == "openai":
        print("  → この平均 × 枚数 × モデルの単価 で全体の料金を見積もる")

    # タグの分布（このモデルのファイル全体）
    rows = read_db(db)
    print(f"\n{db.name}: {len(rows)} 枚")
    for k in TAGS:
        cnt = Counter(r["tags"][k] for r in rows)
        print(f"  {k:17s} " + "  ".join(f"{v}={cnt[v]}" for v in TAGS[k]))


if __name__ == "__main__":
    main()