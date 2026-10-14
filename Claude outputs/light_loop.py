"""光のループ（引き継ぎ書 §12.3・§12.12）

目的: 部屋全体の光（色温度・明るさ・明暗の差・白飛び）を、実写の室内写真の範囲に近づける。
      人が「違反 → この手」の表を作るのではなく、ループがつまみを1段ずつ試し、
      測って良くなったものだけを採用する。

1周の流れ:
  [撮る]  今のシーンJSONで撮影（orchestrator.py --max-iters 1 --skip-vlm）
  [測る]  全景8枚それぞれで L1(Ohno)・L2・L3(σ/μ)・L4(白飛び) を計算し、
          写真の範囲(P10〜P90)からのはみ出しを「範囲の幅」で割って全部足す ＝ 外れ具合
  [選ぶ]  一番外れている項目について、つまみを1つ1段動かす候補を作る
          （ヒントの順に試し、ヒントが尽きたら残りのつまみも試す）
  [採否]  撮り直して外れ具合が減れば採用。減らなければ元に戻し「つまみ×向き」を禁止して次の候補へ
  止まる: 外れ具合ゼロ ／ 試せる候補が尽きた ／ 採用回数が上限 ／ 撮影回数が上限

使い方（sao フォルダで）:
  python mvl-skeleton\\python\\light_loop.py --scene mvl-skeleton\\scene\\scene_study_room_seed1_4096_model_holodeck.json
"""
import argparse
import copy
import json
import subprocess
import sys
import time
from datetime import datetime
from pathlib import Path

import numpy as np
import colour

sys.path.insert(0, str(Path(__file__).resolve().parent))
from light_metrics import load, metrics, pick_photos  # noqa: E402  同じ測り方を使う

SAO = Path(__file__).resolve().parents[2]
SKELETON = SAO / "mvl-skeleton"
UNITY = r"C:\Program Files\Unity\Hub\Editor\6000.5.6f1\Editor\Unity.exe"
PROJECT = SAO / "XRunity"

# ======================================================================
# 1. ものさし（どの項目を、どちら側だけ見るか）
# ======================================================================
CHECKS = {                     # 指標名: 見る側（both=範囲の両側 / upper=上限だけ）
    "L1_cct_ohno_K": "both",   # 色温度（Ohno 2013）
    "L2_median": "both",       # 明るさ
    "L3_rms_rel": "both",      # 明暗の差（σ/μ, Frazor & Geisler 2006）
    "L4_clip": "upper",        # 白飛び・黒つぶれ（多すぎるときだけ違反, 10/10 決定）
}


def reference_ranges(photo_dir, n, seed, cache):
    """写真の P10〜P90 を出す（1回計算したら cache に保存して使い回す）"""
    if cache.exists():
        return json.loads(cache.read_text(encoding="utf-8"))
    vals = [metrics(load(p)) for p in pick_photos(photo_dir, n, seed)]
    ref = {k: [float(np.percentile([v[k] for v in vals], 10)),
               float(np.percentile([v[k] for v in vals], 90))] for k in CHECKS}
    cache.parent.mkdir(parents=True, exist_ok=True)
    cache.write_text(json.dumps(ref, indent=2), encoding="utf-8")
    return ref


def measure(capture_dir, ref):
    """全景8枚を測り、外れ具合の合計と、項目×向きごとの内訳を返す"""
    per = {}                                   # ("L3_rms_rel","low") → はみ出し量の合計
    views = sorted(Path(capture_dir).glob("view_*.png"))
    for v in views:
        m = metrics(load(v))
        for k, side in CHECKS.items():
            lo, hi = ref[k]
            width = hi - lo
            if side == "both" and m[k] < lo:
                per[(k, "low")] = per.get((k, "low"), 0.0) + (lo - m[k]) / width
            if m[k] > hi:
                per[(k, "high")] = per.get((k, "high"), 0.0) + (m[k] - hi) / width
    return sum(per.values()), per


# ======================================================================
# 2. つまみ（段階は粗め, 10/13 決定）
# ======================================================================
KNOBS = {
    "ceil_int": [0.3, 0.45, 0.6, 0.75, 0.9, 1.05],      # 天井照明の強さ
    "sun_int":  [0.35, 0.7, 1.0, 1.4, 1.8],             # 太陽の強さ（約1.4倍刻み）
    "ceil_cct": [2700, 3000, 3500, 4000, 5000, 6500],   # 天井照明の色温度 [K]
}


def cct_to_hex(k):
    """色温度 K → Unity の光の色（sRGB の16進, 一番明るい成分を1にそろえる）"""
    xy = colour.temperature.CCT_to_xy_Kang2002(k)
    rgb = np.clip(colour.XYZ_to_sRGB(colour.xy_to_XYZ(xy)), 0, None)
    rgb = rgb / rgb.max()
    return "".join(f"{int(round(c * 255)):02X}" for c in rgb)


def hex_to_cct(h):
    rgb = np.array([int(h[i:i + 2], 16) for i in (0, 2, 4)]) / 255.0
    return float(colour.temperature.XYZ_to_CCT_Ohno2013(colour.sRGB_to_XYZ(rgb))[0])


def nearest(levels, value):
    return int(np.argmin([abs(l - value) for l in levels]))


def read_knobs(scene):
    """シーンJSONの今の値を、各つまみの「何段目か」に直す"""
    L = scene["room"]["lighting"]
    return {
        "ceil_int": nearest(KNOBS["ceil_int"], L["ceiling_light"]["intensity"]),
        "sun_int": nearest(KNOBS["sun_int"], L["sun"]["intensity"]),
        "ceil_cct": nearest(KNOBS["ceil_cct"], hex_to_cct(L["ceiling_light"]["color_hex"])),
    }


def write_knob(scene, knob, idx):
    """つまみ1つを idx 段目にしたシーンJSONを返す（元のシーンは変えない）"""
    s = copy.deepcopy(scene)
    L = s["room"]["lighting"]
    v = KNOBS[knob][idx]
    if knob == "ceil_int":
        L["ceiling_light"]["intensity"] = v
    elif knob == "sun_int":
        L["sun"]["intensity"] = v
    elif knob == "ceil_cct":
        L["ceiling_light"]["color_hex"] = cct_to_hex(v)
    return s


# ======================================================================
# 3. 手を選ぶ（ヒントは「試す順番」だけ。採否は必ず測って決める）
# ======================================================================
HINTS = {
    ("L1_cct_ohno_K", "low"):  [("ceil_cct", +1)],                     # 暖かすぎ → 色温度を上げる
    ("L1_cct_ohno_K", "high"): [("ceil_cct", -1)],                     # 青すぎ → 下げる
    ("L2_median", "low"):      [("ceil_int", +1), ("sun_int", +1)],    # 暗すぎ
    ("L2_median", "high"):     [("ceil_int", -1), ("sun_int", -1)],    # 明るすぎ
    ("L3_rms_rel", "low"):     [("ceil_int", -1), ("sun_int", +1)],    # のっぺり → 補助光を弱め、窓の光を強める
    ("L3_rms_rel", "high"):    [("ceil_int", +1), ("sun_int", -1)],    # 明暗がきつすぎ
    ("L4_clip", "high"):       [("sun_int", -1), ("ceil_int", -1)],    # 白飛び
}


def candidates(worst, idx, banned):
    """一番外れている項目へのヒント → 残りのつまみ全部、の順で、試せる手を並べる"""
    order = list(HINTS.get(worst, []))
    for knob in KNOBS:
        for d in (+1, -1):
            if (knob, d) not in order:
                order.append((knob, d))
    out = []
    for knob, d in order:
        j = idx[knob] + d
        if 0 <= j < len(KNOBS[knob]) and (knob, d) not in banned:
            out.append((knob, d))
    return out


# ======================================================================
# 4. 撮る（いつもの orchestrator を1回だけ回す）
# ======================================================================
def capture(scene, scene_id):
    s = copy.deepcopy(scene)
    s["scene_id"] = scene_id
    path = SKELETON / "scene" / f"scene_{scene_id}.json"
    path.write_text(json.dumps(s, ensure_ascii=False, indent=2), encoding="utf-8")
    t0 = time.time()
    subprocess.run([sys.executable, str(SKELETON / "python" / "orchestrator.py"),
                    "--scene", str(path), "--unity", UNITY, "--project", str(PROJECT),
                    "--max-iters", "1", "--skip-vlm"], check=True)
    runs = sorted((SKELETON / "runs").glob(f"{scene_id}_*"), key=lambda p: p.stat().st_mtime)
    print(f"    撮影 {time.time() - t0:.0f} 秒: {runs[-1].name}")
    return runs[-1]


# ======================================================================
# 5. ループ本体
# ======================================================================
def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--scene", required=True, help="出発点のシーンJSON（例: Holodeck の値の部屋）")
    ap.add_argument("--photo-dir", default=str(SAO / "research" / "data_256" / "h" / "home_office"))
    ap.add_argument("--n", type=int, default=100)
    ap.add_argument("--seed", type=int, default=0)
    ap.add_argument("--max-accept", type=int, default=8, help="採用回数の上限（＝周回数）")
    ap.add_argument("--max-captures", type=int, default=30, help="撮影回数の上限（時間の上限）")
    a = ap.parse_args()

    name = "lightloop_" + datetime.now().strftime("%Y%m%d_%H%M%S")
    log_dir = SAO / "research" / "light_loop" / name
    log_dir.mkdir(parents=True, exist_ok=True)
    ref = reference_ranges(a.photo_dir, a.n, a.seed,
                           SAO / "research" / "light_loop" / f"ref_home_office_n{a.n}_seed{a.seed}.json")
    print("写真の範囲 P10〜P90:", json.dumps(ref))

    scene = json.loads(Path(a.scene).read_text(encoding="utf-8"))
    idx = read_knobs(scene)
    log = {"name": name, "start_scene": a.scene, "reference": ref, "knobs": KNOBS, "trials": []}

    # 出発点を撮って測る
    run = capture(scene, f"{name}_start")
    score, per = measure(run / "iter_00" / "capture", ref)
    start_run = best_run = run.name
    print(f"[出発点] 外れ具合 {score:.3f}  つまみ {idx}")
    log["trials"].append({"step": 0, "run": run.name, "knobs": dict(idx), "score": score,
                          "detail": {f"{k}:{d}": v for (k, d), v in per.items()}, "accepted": True})

    accepted, captures, banned = 0, 1, set()
    while score > 0 and accepted < a.max_accept and captures < a.max_captures:
        worst = max(per, key=per.get)
        cands = candidates(worst, idx, banned)
        if not cands:
            print("試せる手がなくなった → 終了")
            break
        knob, d = cands[0]
        new_idx = dict(idx)
        new_idx[knob] += d
        print(f"[試す] 一番外れている: {worst[0]}({worst[1]})  手: {knob} を {d:+d} 段"
              f"（{KNOBS[knob][idx[knob]]} → {KNOBS[knob][new_idx[knob]]}）")
        trial_scene = write_knob(scene, knob, new_idx[knob])
        run = capture(trial_scene, f"{name}_t{captures:02d}")
        captures += 1
        new_score, new_per = measure(run / "iter_00" / "capture", ref)
        ok = new_score < score
        print(f"    外れ具合 {score:.3f} → {new_score:.3f}  {'採用' if ok else '不採用（巻き戻して禁止）'}")
        log["trials"].append({"step": captures - 1, "run": run.name, "move": [knob, d],
                              "knobs": dict(new_idx), "score": new_score,
                              "detail": {f"{k}:{dd}": v for (k, dd), v in new_per.items()},
                              "accepted": ok})
        if ok:
            scene, idx, score, per, best_run = trial_scene, new_idx, new_score, new_per, run.name
            accepted += 1
            banned = set()          # 状態が変わったら禁止をリセット（外れ具合は必ず減るので無限ループしない）
        else:
            banned.add((knob, d))
        (log_dir / "loop_log.json").write_text(json.dumps(log, ensure_ascii=False, indent=2), encoding="utf-8")

    reason = ("外れ具合ゼロ" if score == 0 else
              "採用回数の上限" if accepted >= a.max_accept else
              "撮影回数の上限" if captures >= a.max_captures else "手が尽きた")
    log.update({"end_reason": reason, "best_run": best_run, "best_knobs": idx, "best_score": score,
                "accepted": accepted, "captures": captures})
    (log_dir / "loop_log.json").write_text(json.dumps(log, ensure_ascii=False, indent=2), encoding="utf-8")
    (log_dir / "best_scene.json").write_text(json.dumps(scene, ensure_ascii=False, indent=2), encoding="utf-8")

    print(f"\n終了: {reason}  採用 {accepted} 回 / 撮影 {captures} 回")
    print(f"出発点: {start_run}\n最良:   {best_run}  外れ具合 {score:.3f}  つまみ {idx}")
    print(f"ログ: {log_dir / 'loop_log.json'}")
    print("見比べる:")
    print(f"  python mvl-skeleton\\python\\compare_runs.py --a {start_run} --b {best_run}")
    print(f"  .\\mvl-skeleton\\python\\open_two.ps1 -A {start_run} -B {best_run}")


if __name__ == "__main__":
    main()
