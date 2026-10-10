#!/usr/bin/env python3
"""既存の盲検2x2画像から、欠陥を2軸で再監査するHTMLを作る。"""
import argparse
import csv
from pathlib import Path


def build_html(blind_ids):
    cards = "\n".join(
        f'''<article class="card" data-id="{blind_id}">
  <h2>{index:02d} / {len(blind_ids)} &mdash; {blind_id}</h2>
  <img src="samples/{blind_id}.png" alt="{blind_id} の2x2反復画像">
  <fieldset><legend>A. 中央の継ぎ目を線として追えるか</legend>
    <label><input type="radio" name="{blind_id}_seam" value="yes"> 目立つ（欠陥あり）</label>
    <label><input type="radio" name="{blind_id}_seam" value="no"> 目立たない</label>
  </fieldset>
  <fieldset><legend>B. 特徴的な模様が周期的に繰り返して目立つか</legend>
    <label><input type="radio" name="{blind_id}_repeat" value="yes"> 目立つ（欠陥あり）</label>
    <label><input type="radio" name="{blind_id}_repeat" value="no"> 目立たない</label>
  </fieldset>
  <label class="note">メモ（任意）<input type="text" name="{blind_id}_note"></label>
</article>'''
        for index, blind_id in enumerate(blind_ids, 1))
    ids_json = "[" + ",".join(f'"{value}"' for value in blind_ids) + "]"
    return f'''<!doctype html>
<html lang="ja"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>テクスチャ欠陥 再監査 v2</title>
<style>
body{{font-family:system-ui,sans-serif;max-width:1080px;margin:auto;padding:24px;background:#f4f1eb;color:#222}}
header{{position:sticky;top:0;background:#f4f1ebee;padding:12px 0;z-index:2;border-bottom:2px solid #765}}
.guide{{background:white;padding:14px 18px;border-radius:10px}} .card{{background:white;margin:24px 0;padding:18px;border-radius:12px}}
img{{display:block;width:min(100%,768px);margin:auto;image-rendering:auto}} fieldset{{margin:14px 0;padding:12px}}
fieldset label{{display:inline-block;margin-right:28px;font-size:1.1rem}} .note{{display:block}} .note input{{width:100%;padding:8px;box-sizing:border-box}}
button{{font-size:1rem;padding:10px 18px;margin-right:10px}} #progress{{font-weight:bold}}
</style></head><body>
<header><strong>テクスチャ欠陥 再監査 v2</strong>　<span id="progress">0 / {len(blind_ids)}</span></header>
<section class="guide">
<p><b>A 継ぎ目:</b> 中央の水平・垂直境界を線として追えるなら「目立つ（欠陥あり）」。</p>
<p><b>B 不自然な反復:</b> 特徴的な列・帯・色むら・模様がタイル周期で再登場するなら「目立つ（欠陥あり）」。</p>
<p><b>A・Bの両方が「目立たない」の画像だけが許容です。</b> 両方に欠陥がある場合もあります。旧ラベルやVLM結果は表示していません。</p>
<button id="download">全20枚をCSV保存</button><button id="clear">回答を消去</button>
</section>
{cards}
<script>
const ids={ids_json}; const key='texture-reaudit-v2-20260930';
const read=()=>{{try{{return JSON.parse(localStorage.getItem(key)||'{{}}')}}catch{{return {{}}}}}};
function collect(){{const out={{}}; for(const id of ids){{
 const seam=document.querySelector(`input[name="${{id}}_seam"]:checked`)?.value||'';
 const repeat=document.querySelector(`input[name="${{id}}_repeat"]:checked`)?.value||'';
 const note=document.querySelector(`input[name="${{id}}_note"]`).value;
 out[id]={{visible_seam:seam,unnatural_repetition:repeat,note}};}} return out;}}
function update(){{const out=collect();localStorage.setItem(key,JSON.stringify(out));
 const done=ids.filter(id=>out[id].visible_seam&&out[id].unnatural_repetition).length;
 document.getElementById('progress').textContent=`${{done}} / ${{ids.length}}`;}}
const saved=read(); for(const id of ids){{for(const field of ['seam','repeat']){{const value=saved[id]?.[field==='seam'?'visible_seam':'unnatural_repetition'];if(value)document.querySelector(`input[name="${{id}}_${{field}}"][value="${{value}}"]`).checked=true;}}document.querySelector(`input[name="${{id}}_note"]`).value=saved[id]?.note||'';}}
document.addEventListener('change',update);document.addEventListener('input',update);update();
const quote=value=>'"'+String(value).replaceAll('"','""')+'"';
document.getElementById('download').onclick=()=>{{const out=collect();const incomplete=ids.filter(id=>!out[id].visible_seam||!out[id].unnatural_repetition);if(incomplete.length){{alert('未回答: '+incomplete.join(', '));return;}}
 const lines=['blind_id,visible_seam,unnatural_repetition,acceptable,note'];for(const id of ids){{const r=out[id];lines.push([id,r.visible_seam,r.unnatural_repetition,(r.visible_seam==='no'&&r.unnatural_repetition==='no')?'yes':'no',r.note].map(quote).join(','));}}
 const blob=new Blob(['\\ufeff'+lines.join('\\r\\n')],{{type:'text/csv'}});const a=document.createElement('a');a.href=URL.createObjectURL(blob);a.download='human_labels_v2.csv';a.click();URL.revokeObjectURL(a.href);}};
document.getElementById('clear').onclick=()=>{{if(confirm('保存済み回答をすべて消しますか？')){{localStorage.removeItem(key);location.reload();}}}};
</script></body></html>'''


def write_blank_csv(path, blind_ids):
    with Path(path).open("w", encoding="utf-8-sig", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=(
            "blind_id", "visible_seam", "unnatural_repetition",
            "acceptable", "note"))
        writer.writeheader()
        for blind_id in blind_ids:
            writer.writerow({"blind_id": blind_id})


def main(argv=None):
    parser = argparse.ArgumentParser(description="テクスチャ再監査HTMLを作る")
    parser.add_argument("review_dir", help="samplesディレクトリを含むblind_review")
    args = parser.parse_args(argv)
    review_dir = Path(args.review_dir)
    blind_ids = sorted(path.stem for path in (review_dir / "samples").glob("*.png"))
    if not blind_ids:
        raise FileNotFoundError(f"監査画像がありません: {review_dir / 'samples'}")
    html_path = review_dir / "human_reaudit_v2.html"
    csv_path = review_dir / "human_labels_v2_blank.csv"
    html_path.write_text(build_html(blind_ids), encoding="utf-8")
    write_blank_csv(csv_path, blind_ids)
    print(f"HTML: {html_path.resolve()}")
    print(f"Blank CSV: {csv_path.resolve()}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
