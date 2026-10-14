"""写真データベースから条件に合う写真を集め、光のループの物差し（P10〜P90）を作る

目的: 「曇りの日の書斎」のような世界設定に合う実写だけで物差しを作る。
      集めた写真は一覧ページで目で確認できる（条件に合っているか）。

使い方（sao フォルダで。先に photo_db.py でタグを付けておく）:
  # 条件を自分で書く（| は「どれか」）
  python mvl-skeleton\\python\\photo_search.py --name cloudy_day --where "weather=overcast time=day"
  python mvl-skeleton\\python\\photo_search.py --name sunny --where "sun_patches=yes"

  # 文章で頼む（LLM が条件に直す → 確認してから実行）
  python mvl-skeleton\\python\\photo_search.py --name calm_study --ask "曇りの日の落ち着いた書斎" --backend openai

  ※ photo_type=real_photo（CG を除く）は、指定しなければ自動で付く
  ※ タグのファイルが複数ある（GPT と Qwen など）ときは --tags tags_gpt-5.jsonl で選ぶ

出力: research\\photo_db\\rulers\\<name>.json         ← light_loop.py --ref に渡す物差し
      research\\photo_db\\rulers\\<name>_photos.txt   ← 使った写真の一覧（再現用）
      research\\photo_db\\rulers\\<name>.html         ← 目で確認するページ（自動で開く）
"""
import argparse
import base64
import json
import sys
import webbrowser
from datetime import datetime
from pathlib import Path

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parent))
from light_metrics import load, metrics          # noqa: E402  ループと同じ測り方
from light_loop import CHECKS                    # noqa: E402  ループと同じ項目
from photo_db import TAGS, DATA, DB_DIR, read_db, make_client  # noqa: E402

RULERS = DB_DIR / "rulers"
MIN_PHOTOS = 50   # これより少ないと P10/P90 が不安定（警告だけ出す）


# ======================================================================
# 1. 条件
# ======================================================================
def parse_where(text):
    """'weather=overcast|rainy time=day' → {'weather': {'overcast','rainy'}, 'time': {'day'}}"""
    cond = {}
    for part in (text or "").split():
        k, v = part.split("=", 1)
        if k not in TAGS:
            raise SystemExit(f"知らない項目: {k}（使えるのは {list(TAGS)}）")
        vals = set(v.split("|"))
        bad = vals - set(TAGS[k])
        if bad:
            raise SystemExit(f"{k} に {bad} はありません（選択肢 {TAGS[k]}）")
        cond[k] = vals
    return cond


def ask_to_where(text, backend):
    """文章 → 条件（LLM）。言われていない項目は any（絞らない）にさせる"""
    client, model = make_client(backend)
    props = {k: {"type": "string", "enum": v + ["any"]} for k, v in TAGS.items()}
    props["reason"] = {"type": "string"}
    fmt = {"type": "json_schema",
           "json_schema": {"name": "photo_filter", "strict": True,
                           "schema": {"type": "object", "properties": props,
                                      "required": list(props), "additionalProperties": False}}}
    system = ("Convert the user's description of a room's world setting into filter conditions "
              "over photo tags. Constrain only what the description states or clearly implies; "
              "use \"any\" for everything else. Explain briefly in Japanese in 'reason'.")
    r = client.chat.completions.create(
        model=model, response_format=fmt,
        messages=[{"role": "system", "content": system}, {"role": "user", "content": text}])
    c = r.choices[0].message.content
    out = json.loads(c[c.find("{"): c.rfind("}") + 1])
    print(f"{model} の解釈:", out.pop("reason"))
    return {k: {v} for k, v in out.items() if v != "any"}


def match(row, cond, categories):
    if categories and row["category"] not in categories:
        return False
    return all(row["tags"][k] in vals for k, vals in cond.items())


# ======================================================================
# 2. 物差し
# ======================================================================
def make_ruler(paths):
    vals = [metrics(load(p)) for p in paths]
    ruler, pct = {}, {}
    for k in CHECKS:
        x = np.array([v[k] for v in vals], dtype=float)
        p10, p50, p90 = np.nanpercentile(x, [10, 50, 90])
        ruler[k] = [float(p10), float(p90)]          # light_loop.py が読む形（今までと同じ）
        pct[k] = [float(p10), float(p50), float(p90)]
    return ruler, pct


def write_page(path, name, cond_text, rows, pct, base_pct, n_show, seed):
    rng = np.random.default_rng(seed)
    pick = [rows[i] for i in sorted(rng.choice(len(rows), size=min(n_show, len(rows)), replace=False))]
    imgs = "".join(
        f'<figure><img src="data:image/jpeg;base64,{base64.b64encode((DATA / r["id"]).read_bytes()).decode()}">'
        f'<figcaption>{r["tags"]["caption"]}</figcaption></figure>' for r in pick)
    tr = "".join(
        f"<tr><td>{k}</td><td>{pct[k][0]:.4g} 〜 {pct[k][2]:.4g}（中央 {pct[k][1]:.4g}）</td>"
        f"<td>{'' if base_pct is None else f'{base_pct[k][0]:.4g} 〜 {base_pct[k][2]:.4g}'}</td></tr>"
        for k in CHECKS)
    html = f"""<!doctype html><html lang="ja"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1"><title>物差し {name}</title><style>
:root{{--bg:#f6f5f2;--fg:#1d1d1f;--mut:#6b6b70;--card:#fff;--line:#d9d7d2}}
@media (prefers-color-scheme:dark){{:root{{--bg:#161618;--fg:#ececee;--mut:#9a9aa0;--card:#202023;--line:#38383c}}}}
body{{margin:0;background:var(--bg);color:var(--fg);font-family:system-ui,"Yu Gothic UI",sans-serif}}
.wrap{{max-width:1200px;margin:0 auto;padding:16px}} h1{{font-size:18px;margin:0 0 4px}}
.mut{{color:var(--mut);font-size:13px}}
table{{border-collapse:collapse;margin:12px 0;font-size:13px;background:var(--card)}}
td,th{{border-bottom:1px solid var(--line);padding:6px 10px;text-align:left}}
.grid{{display:grid;grid-template-columns:repeat(auto-fill,minmax(180px,1fr));gap:10px}}
figure{{margin:0;background:var(--card);border-radius:8px;overflow:hidden}}
img{{width:100%;aspect-ratio:1;object-fit:cover;display:block}}
figcaption{{font-size:11px;color:var(--mut);padding:6px}}
</style></head><body><div class="wrap">
<h1>物差し: {name}</h1>
<div class="mut">条件: {cond_text}　／　該当 {len(rows)} 枚（下は {len(pick)} 枚をランダム表示）</div>
<table><tr><th>指標</th><th>この条件の P10〜P90</th><th>条件なし（実写全部）</th></tr>{tr}</table>
<div class="mut">確認すること: 下の写真が条件に合っているか。明らかに違う写真が多ければタグか条件を見直す。</div>
<div class="grid" style="margin-top:10px">{imgs}</div>
</div></body></html>"""
    path.write_text(html, encoding="utf-8")


# ======================================================================
# 3. 本体
# ======================================================================
def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--name", required=True, help="物差しの名前（ファイル名になる）")
    ap.add_argument("--where", help='例: "weather=overcast|rainy time=day"')
    ap.add_argument("--ask", help="文章で頼む")
    ap.add_argument("--backend", default="openai", choices=["openai", "hpc"], help="--ask で使う LLM")
    ap.add_argument("--tags", help="使うタグのファイル名（research\\photo_db の中。1つしかなければ省略可）")
    ap.add_argument("--categories", nargs="+", help="カテゴリで絞る（省略時は全部）")
    ap.add_argument("--yes", action="store_true", help="--ask の確認を飛ばす")
    ap.add_argument("--show", type=int, default=40, help="確認ページに出す枚数")
    ap.add_argument("--seed", type=int, default=0)
    ap.add_argument("--no-open", action="store_true")
    a = ap.parse_args()

    if a.ask:
        cond = ask_to_where(a.ask, a.backend)
    else:
        cond = parse_where(a.where)
    cond.setdefault("photo_type", {"real_photo"})
    cond_text = "  ".join(f"{k}={'|'.join(sorted(v))}" for k, v in cond.items())
    print("条件:", cond_text)
    if a.ask and not a.yes and input("この条件で作りますか？ [y/N] ").strip().lower() != "y":
        return

    files = sorted(DB_DIR.glob("tags_*.jsonl"))
    if a.tags:
        tags_file = DB_DIR / a.tags
    elif len(files) == 1:
        tags_file = files[0]
    else:
        raise SystemExit(f"タグのファイルを --tags で選んでください: {[f.name for f in files] or 'なし（先に photo_db.py）'}")
    db = read_db(tags_file)
    print("タグ:", tags_file.name)
    rows = [r for r in db if match(r, cond, a.categories)]
    base = [r for r in db if match(r, {"photo_type": {"real_photo"}}, a.categories)]
    print(f"該当 {len(rows)} 枚 / 実写全部 {len(base)} 枚")
    if len(rows) < 10:
        raise SystemExit("10枚未満なので物差しを作れません。条件をゆるめてください")
    if len(rows) < MIN_PHOTOS:
        print(f"※ {MIN_PHOTOS} 枚未満です。P10/P90 がぶれやすいので注意")

    ruler, pct = make_ruler([DATA / r["id"] for r in rows])
    _, base_pct = make_ruler([DATA / r["id"] for r in base]) if base else (None, None)

    RULERS.mkdir(parents=True, exist_ok=True)
    ruler["_meta"] = {"name": a.name, "tags_file": tags_file.name, "conditions": cond_text, "ask": a.ask,
                      "categories": a.categories, "n_photos": len(rows),
                      "percentiles_P10_P50_P90": pct,
                      "created": datetime.now().isoformat(timespec="seconds")}
    (RULERS / f"{a.name}.json").write_text(json.dumps(ruler, indent=2, ensure_ascii=False), encoding="utf-8")
    (RULERS / f"{a.name}_photos.txt").write_text("\n".join(r["id"] for r in rows), encoding="utf-8")
    page = RULERS / f"{a.name}.html"
    write_page(page, a.name, cond_text, rows, pct, base_pct, a.show, a.seed)

    print(f"\n{'指標':16s} {'この条件 P10〜P90':>24s}   {'実写全部 P10〜P90':>24s}")
    for k in CHECKS:
        b = f"{base_pct[k][0]:.4g} 〜 {base_pct[k][2]:.4g}" if base_pct else ""
        print(f"{k:16s} {pct[k][0]:>11.4g} 〜 {pct[k][2]:<11.4g}   {b:>24s}")
    print(f"\n物差し: {RULERS / (a.name + '.json')}")
    if not a.no_open:
        webbrowser.open(page.as_uri())


if __name__ == "__main__":
    main()