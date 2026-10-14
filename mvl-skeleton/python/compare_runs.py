"""2つのランの全景を並べた比較ページを作り、ブラウザで自動で開く

目的: ランのたびに「何がどう変わったか」を、ターミナルの数字ではなく画像で見る。
      数字（light_metrics.py の summary.csv）があれば表も一緒に出す。

使い方（sao フォルダで）:
  python mvl-skeleton\\python\\compare_runs.py                 # 直近2つのランを比べる
  python mvl-skeleton\\python\\compare_runs.py --a <ラン名> --b <ラン名>

  出力: research\\compare\\<A>__vs__<B>.html（ブラウザで自動で開く）
"""
import argparse
import base64
import csv
import io
import json
import webbrowser
from pathlib import Path

from PIL import Image

SAO = Path(__file__).resolve().parents[2]          # .../sao
RUNS = SAO / "mvl-skeleton" / "runs"
SUMMARIES = SAO / "research" / "places365"          # out_<ラン名>/summary.csv
OUT = SAO / "research" / "compare"

SHOW = ["L1_cct_ohno_K", "L1_duv", "L2_median", "L3_std", "L3_logstd", "L4_clip"]


# ---- ランを探す ----
def capture_dir(run):
    return RUNS / run / "iter_00" / "capture"


def latest_runs(n):
    """全景が撮れているランを新しい順に n 個"""
    runs = [p for p in RUNS.iterdir() if p.is_dir() and (p / "iter_00" / "capture" / "view_00.png").exists()]
    runs.sort(key=lambda p: p.stat().st_mtime, reverse=True)
    return [p.name for p in runs[:n]]


# ---- 画像と数字を読む ----
def encode(path, width=1280):
    im = Image.open(path).convert("RGB")
    im = im.resize((width, round(im.height * width / im.width)), Image.LANCZOS)
    buf = io.BytesIO()
    im.save(buf, "JPEG", quality=85)
    return "data:image/jpeg;base64," + base64.b64encode(buf.getvalue()).decode()


def read_summary(run):
    """light_metrics.py の summary.csv があれば {指標: 行} を返す。なければ None"""
    p = SUMMARIES / f"out_{run}" / "summary.csv"
    if not p.exists():
        return None
    with open(p, encoding="utf-8") as f:
        return {row["metric"]: row for row in csv.DictReader(f)}


def metric_rows(sa, sb):
    if sa is None and sb is None:
        return "<p>数字なし（両方のランで light_metrics.py を実行すると表が出ます）</p>"
    rows = []
    for k in SHOW:
        ra, rb = (sa or {}).get(k), (sb or {}).get(k)
        ref = ra or rb
        if ref is None:
            continue
        fmt = lambda r: "—" if r is None else f"{r['room_median']}（{r['room_in_range']}）"
        rows.append(f"<tr><td>{k}</td><td>{fmt(ra)}</td><td>{fmt(rb)}</td>"
                    f"<td>{ref['photo_P10']}〜{ref['photo_P90']}</td></tr>")
    return ("<table><tr><th>指標（部屋の中央値・範囲内の枚数）</th><th>A</th><th>B</th>"
            "<th>写真 P10〜P90</th></tr>" + "".join(rows) + "</table>")


# ---- ページを作る ----
PAGE = r"""<!doctype html><html lang="ja"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1"><title>ラン比較</title>
<style>
:root{--bg:#f6f5f2;--fg:#1d1d1f;--mut:#6b6b70;--card:#fff;--line:#d9d7d2;--acc:#2f6fdf}
@media (prefers-color-scheme:dark){:root{--bg:#161618;--fg:#ececee;--mut:#9a9aa0;--card:#202023;--line:#38383c;--acc:#7aa7ff}}
body{margin:0;background:var(--bg);color:var(--fg);font-family:system-ui,"Yu Gothic UI","Hiragino Sans",sans-serif}
.wrap{max-width:1100px;margin:0 auto;padding:16px} h1{font-size:17px;margin:0 0 6px}
.names{font-size:12px;color:var(--mut);margin-bottom:10px;word-break:break-all}
.row{display:flex;gap:6px;flex-wrap:wrap;margin-bottom:8px}
button{border:1px solid var(--line);background:var(--card);color:var(--fg);padding:6px 10px;border-radius:8px;cursor:pointer;font-size:13px}
button.on{border-color:var(--acc);color:var(--acc);font-weight:600}
.stage{position:relative;width:100%;aspect-ratio:16/9;background:#000;border-radius:10px;overflow:hidden;user-select:none;touch-action:none}
.stage img{position:absolute;inset:0;width:100%;height:100%;object-fit:cover;pointer-events:none}
#bar{position:absolute;top:0;bottom:0;width:2px;background:#fff;box-shadow:0 0 4px #000}
.lab{position:absolute;top:8px;padding:3px 8px;border-radius:6px;background:rgba(0,0,0,.6);color:#fff;font-size:12px}
#la{left:8px}#lb{right:8px}
table{border-collapse:collapse;margin-top:14px;font-size:13px;width:100%;background:var(--card)}
td,th{border-bottom:1px solid var(--line);padding:6px 8px;text-align:left}th{color:var(--mut);font-weight:500}
.hint{font-size:12px;color:var(--mut);margin-top:6px}
</style></head><body><div class="wrap">
<h1>ラン比較</h1>
<div class="names">A: __A__<br>B: __B__</div>
<div class="row"><button id="m1" class="on">スライダー</button><button id="m2">切り替え（A⇄B）</button></div>
<div class="row" id="tabs"></div>
<div class="stage" id="stage"><img id="imB"><img id="imA"><div id="bar"></div>
<span class="lab" id="la">A</span><span class="lab" id="lb">B</span></div>
<div class="hint">スライダー: 画像をドラッグ ／ 切り替え: クリックかスペース ／ 視点: ← →</div>
__TABLE__
</div><script>
const D=__DATA__;let v=0,mode=1,showB=false,pos=50,drag=false;
const imA=document.getElementById('imA'),imB=document.getElementById('imB'),bar=document.getElementById('bar'),
st=document.getElementById('stage'),la=document.getElementById('la'),lb=document.getElementById('lb'),
tabs=document.getElementById('tabs'),m1=document.getElementById('m1'),m2=document.getElementById('m2');
D.forEach((d,i)=>{const b=document.createElement('button');b.textContent=d.name;b.onclick=()=>{v=i;draw()};tabs.appendChild(b)});
function draw(){[...tabs.children].forEach((b,i)=>b.classList.toggle('on',i===v));
 if(mode===1){imB.src=D[v].b;imA.src=D[v].a;imA.style.display='';imA.style.clipPath=`inset(0 ${100-pos}% 0 0)`;
  bar.style.display='';bar.style.left=pos+'%';lb.style.display='';la.textContent='A';}
 else{imA.style.display='none';bar.style.display='none';lb.style.display='none';imB.src=showB?D[v].b:D[v].a;la.textContent=showB?'B':'A';}}
function setPos(e){const r=st.getBoundingClientRect();pos=Math.max(0,Math.min(100,(e.clientX-r.left)/r.width*100));draw()}
st.addEventListener('pointerdown',e=>{if(mode===1){drag=true;setPos(e)}else{showB=!showB;draw()}});
window.addEventListener('pointermove',e=>{if(drag)setPos(e)});window.addEventListener('pointerup',()=>drag=false);
m1.onclick=()=>{mode=1;m1.classList.add('on');m2.classList.remove('on');draw()};
m2.onclick=()=>{mode=2;m2.classList.add('on');m1.classList.remove('on');draw()};
window.addEventListener('keydown',e=>{const n=D.length;if(e.key==='ArrowRight'){v=(v+1)%n;draw()}
 else if(e.key==='ArrowLeft'){v=(v+n-1)%n;draw()}else if(e.key===' '){e.preventDefault();if(mode===2){showB=!showB;draw()}}});
draw();
</script></body></html>"""


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--a", help="比べる元のラン名（省略時: 2番目に新しいラン）")
    ap.add_argument("--b", help="比べる先のラン名（省略時: 一番新しいラン）")
    ap.add_argument("--no-open", action="store_true", help="ブラウザを開かない")
    args = ap.parse_args()

    if args.a is None or args.b is None:
        newest = latest_runs(2)
        b = args.b or newest[0]
        a = args.a or next(r for r in newest if r != b)
    else:
        a, b = args.a, args.b

    views = sorted(capture_dir(a).glob("view_*.png"))
    data = []
    for va in views:
        vb = capture_dir(b) / va.name
        if vb.exists():
            data.append({"name": va.stem, "a": encode(va), "b": encode(vb)})
    if not data:
        raise SystemExit(f"共通の全景画像がありません: {a} / {b}")

    html = (PAGE.replace("__A__", a).replace("__B__", b)
                .replace("__TABLE__", metric_rows(read_summary(a), read_summary(b)))
                .replace("__DATA__", json.dumps(data)))
    OUT.mkdir(parents=True, exist_ok=True)
    out = OUT / f"{a}__vs__{b}.html"
    out.write_text(html, encoding="utf-8")
    print(f"A: {a}\nB: {b}\n出力: {out}")
    if not args.no_open:
        webbrowser.open(out.as_uri())


if __name__ == "__main__":
    main()
