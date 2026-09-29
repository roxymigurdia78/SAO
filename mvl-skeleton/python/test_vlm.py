#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
test_vlm.py -- KambeHPCのLLM APIで、画像入力が通るかと速度を確認する

APIキーは環境変数から読む(ファイルに書かない):
    同じフォルダの .env に LLM_KEY を書くか、
    PowerShell:  $env:LLM_KEY = "発行したkey"

使い方:
    python test_vlm.py
    python test_vlm.py --model gemma4:12b
    python test_vlm.py --run mvl-skeleton\\runs\\wizard_study_seed1_20260820_164441
"""
import argparse
import base64
import glob
import io
import json
import os
import re
import sys
import time

DEFAULT_BASE_URL = "https://llm.kambehpc.com/v1"


def load_env():
    """同じフォルダの .env を読む(既存の環境変数が優先)。外部ライブラリ不要。"""
    path = os.path.join(os.path.dirname(os.path.abspath(__file__)), ".env")
    if not os.path.exists(path):
        return
    with open(path, encoding="utf-8-sig") as f:
        for line in f:
            line = line.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            k, _, v = line.partition("=")
            os.environ.setdefault(k.strip(), v.strip().strip('"').strip("'"))

RUBRIC = """あなたは3DCG空間の品質評価者です。以下は同一の部屋を8方向から撮影した画像です。
次の5項目を1〜5の整数で採点し、JSONだけを出力してください。説明文は不要です。

B1 スケールの正しさ (5=全て実寸として自然 / 3=1〜2箇所に違和感 / 1=空間として破綻)
B2 照明の物理的妥当性 (5=光源と影が矛盾なし / 3=影や露出が不自然 / 1=光源と結果が矛盾)
B3 配置の一貫性 (5=貫通/浮遊/向きの誤りが0件 / 3=3〜5件 / 1=破綻)
B4 材質の写実性 (5=写真と誤認しうる / 3=CGと分かる / 1=単色プレースホルダ)
B5 総合臨場感 (5=その場に居る感覚が持続 / 3=作り物感が消えない / 1=没入не成立)

出力形式:
{"B1":n,"B2":n,"B3":n,"B4":n,"B5":n,"worst_object":"最も品質を下げている物体","comment":"一文"}"""


def img_part(path, max_px=1024):
    raw = open(path, "rb").read()
    mime = "image/png"
    if max_px:
        try:
            from PIL import Image
            im = Image.open(io.BytesIO(raw)).convert("RGB")
            if max(im.size) > max_px:
                s = max_px / max(im.size)
                im = im.resize((int(im.width * s), int(im.height * s)))
            buf = io.BytesIO()
            im.save(buf, format="JPEG", quality=85)
            raw, mime = buf.getvalue(), "image/jpeg"
        except ImportError:
            print("  (Pillow未導入のため縮小せず送信)")
    b64 = base64.b64encode(raw).decode()
    return {"type": "image_url", "image_url": {"url": "data:%s;base64,%s" % (mime, b64)}}


def ask(client, model, text, paths, max_px=1024):
    parts = [{"type": "text", "text": text}] + [img_part(p, max_px) for p in paths]
    t0 = time.time()
    chunks = client.chat.completions.create(
        model=model,
        messages=[{"role": "user", "content": parts}],
        reasoning_effort="none",
        max_tokens=512,
        stream=True,
    )
    text_parts = []
    first_token = None
    usage = None
    for chunk in chunks:
        if getattr(chunk, "usage", None) is not None:
            usage = chunk.usage
        choices = getattr(chunk, "choices", None) or []
        if not choices:
            continue
        content = getattr(getattr(choices[0], "delta", None), "content", None)
        if content:
            if first_token is None:
                first_token = time.time() - t0
            text_parts.append(content)
    dt = time.time() - t0
    print("  最初の応答: %s" % ("%.1f秒" % first_token if first_token is not None else "計測不能"))
    return "".join(text_parts), dt, usage


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--model", default="")
    ap.add_argument("--run", default="")
    ap.add_argument("--max-px", type=int, default=1024,
                    help="画像の長辺をこのpxに縮小して送る(既定1024、0=そのまま)")
    args = ap.parse_args()

    load_env()
    key = (os.environ.get("LLM_KEY") or os.environ.get("LITELLM_API_KEY")
           or os.environ.get("OPENAI_API_KEY"))
    base = os.environ.get("LLM_BASE_URL") or os.environ.get("OPENAI_BASE_URL") or DEFAULT_BASE_URL
    model = args.model or os.environ.get("LLM_MODEL") or "qwen3.5:35b"
    if not key or "ここに" in key:
        print("キーがありません。.env に LLM_KEY を書くか、$env:LLM_KEY を設定してください。",
              file=sys.stderr)
        return 2

    try:
        from openai import OpenAI
    except ImportError:
        print("pip install openai が必要です", file=sys.stderr)
        return 2
    client = OpenAI(api_key=key, base_url=base,
                    default_headers={"User-Agent": "curl/8.5.0"})

    # 画像を探す
    if args.run:
        pngs = sorted(glob.glob(os.path.join(args.run, "iter_00", "capture", "*.png")))
    else:
        cand = sorted(glob.glob(os.path.join("mvl-skeleton", "runs", "*", "iter_00", "capture", "*.png")))
        if not cand:
            cand = sorted(glob.glob(os.path.join("runs", "*", "iter_00", "capture", "*.png")))
        pngs = cand[:8]
    if not pngs:
        print("画像が見つかりません。--run で実行ログのフォルダを指定してください。", file=sys.stderr)
        return 2
    print("接続  : %s" % base)
    print("モデル: %s" % model)
    print("画像  : %d枚 (%s ...)" % (len(pngs), os.path.basename(pngs[0])))
    print("サイズ: %.2f MB" % (sum(os.path.getsize(p) for p in pngs) / 1e6))
    print("-" * 60)

    # --- テスト1: 画像1枚
    print("[1] 画像1枚")
    try:
        txt, dt, u = ask(client, model, "この画像に何が写っていますか。日本語で1文で答えてください。",
                         pngs[:1], args.max_px)
        print("  %.1f秒" % dt, ("| in=%s out=%s" % (u.prompt_tokens, u.completion_tokens)) if u else "")
        print("  応答: %s" % txt.strip()[:300])
    except Exception as e:
        print("  失敗: %s" % e)
        print("\n→ このモデルは画像を受け付けません。gemma4:12b を試すか、Discordで申請してください。")
        return 1

    # --- テスト2: 画像8枚 + 採点JSON
    print("\n[2] 画像%d枚 + B1〜B5採点" % len(pngs))
    try:
        txt, dt, u = ask(client, model, RUBRIC, pngs, args.max_px)
        print("  %.1f秒" % dt, ("| in=%s out=%s" % (u.prompt_tokens, u.completion_tokens)) if u else "")
        print("  生応答:\n%s" % txt.strip()[:800])
        m = re.search(r"\{.*\}", txt, re.DOTALL)
        if m:
            d = json.loads(m.group(0))
            print("\n  JSON解析: OK")
            print("  B1=%s B2=%s B3=%s B4=%s B5=%s" %
                  tuple(d.get(k) for k in ("B1", "B2", "B3", "B4", "B5")))
            vals = [d.get(k) for k in ("B1", "B2", "B3", "B4", "B5")]
            if all(isinstance(v, int) for v in vals):
                print("  平均 %.2f" % (sum(vals) / 5.0))
        else:
            print("\n  JSON解析: 失敗(JSONが見つからない)")
    except Exception as e:
        print("  失敗: %s" % e)
        print("\n→ 1枚は通るが8枚が通らない場合、コンテキスト長か画像サイズの問題です。")
        print("   --max-px 512 を付けて再実行してください。")
        return 1

    print("\n" + "=" * 60)
    print("両方通りました。所要時間を見て、実用速度か判断してください。")
    print("参考: 今日のGPT-5は1回あたり数十秒でした。")
    return 0


if __name__ == "__main__":
    sys.exit(main())
