# repair.py — 修正オペレータ(違反 → シーンJSONの編集)
# 修正対応表(8月版):
#   欠落            → add_object(バリアントプールから追加配置)
#   貫通            → push_apart(transform修正: 最小重なり軸に沿って押し出し)
#   浮遊/めり込み    → snap_to_floor / snap_to_parent(transform修正)
#   スケール逸脱     → rescale(クラス許容範囲の中央値へ)
#   範囲外          → clamp_into_room
#   低品質(VLM指摘) → swap_variant(バリアント差し替え。再生成は9月=スパコン復帰後)
import copy
import math
from pathlib import Path

import machine_checks as mc
# TODO 9月: push_apartが内包+壁詰みで進めない場合、直交軸や大きい方の移動・relocateへの切替を検討
# TODO 9月: 巻き戻し時のブラックリストが複数修正を連帯責任にする問題(単修正のみ記録 or 一手ずつ再試行)

def _obj(scene, oid):
    for o in scene["objects"]:
        if o["id"] == oid:
            return o
    return None


def _is_locked(obj):
    return obj is not None and obj.get("locked", False)


# ---------- 各オペレータ ----------

def snap_to_floor(scene, v):
    obj = _obj(scene, v["object_id"])
    if _is_locked(obj) or obj is None:
        return None
    old = obj["position"][1]
    obj["position"][1] = scene["room"].get("floor_y", 0.0)
    return f"{obj['id']}: y {old:.3f}→{obj['position'][1]:.3f}(接地)"


def snap_to_parent(scene, v):
    obj = _obj(scene, v["object_id"])
    if _is_locked(obj) or obj is None:
        return None
    old = obj["position"][1]
    obj["position"][1] = v.get("snap_to", old - v.get("gap", 0))
    return f"{obj['id']}: y {old:.3f}→{obj['position'][1]:.3f}({obj.get('rests_on')}上面へ)"


def push_apart(scene, v, aabbs):
    """貫通ペアの、locked でない・小さい方を最小重なり軸に沿って移動"""
    ids = v.get("object_ids")
    if not ids or len(ids) < 2:
        return None
    a, b = _obj(scene, ids[0]), _obj(scene, ids[1])
    if a is None or b is None:
        return None
    # 動かす方を決める(lockedでない、より小さい方)
    def vol(o):
        d = o.get("target_dimensions") or {}
        return d.get("width", 1) * d.get("height", 1) * d.get("depth", 1)
    candidates = [o for o in (a, b) if not _is_locked(o)]
    if not candidates:
        return None
    mover = min(candidates, key=vol)
    other = b if mover is a else a
    va = v.get("aabbs") or {}
    if mover["id"] in va and other["id"] in va:
        amn, amx = va[mover["id"]]
        bmn, bmx = va[other["id"]]
    else:
        (amn, amx, _), (bmn, bmx, _) = aabbs[mover["id"]], aabbs[other["id"]]
    # 水平軸のうち重なりが小さい方に押し出す(+方向/-方向は部屋中心から遠ざからない側)
    ox = mc.overlap_1d(amn[0], amx[0], bmn[0], bmx[0])
    oz = mc.overlap_1d(amn[2], amx[2], bmn[2], bmx[2])
    axis = 0 if ox <= oz else 2
    depth = (ox if axis == 0 else oz) + 0.05
    center_other = (bmn[axis] + bmx[axis]) / 2
    center_mover = (amn[axis] + amx[axis]) / 2
    sign = 1 if center_mover >= center_other else -1
    old = mover["position"][axis]
    mover["position"][axis] = old + sign * depth
    _clamp_obj(scene, mover)
    ax = "x" if axis == 0 else "z"
    if abs(mover["position"][axis] - old) < 0.005:
        mover["position"][axis] = old
        return None  # 実質動かない修正は「適用」と数えない
    return f"{mover['id']}: {ax} {old:.2f}→{mover['position'][axis]:.2f}(貫通解消)"

def clamp_into_room(scene, v):
    obj = _obj(scene, v["object_id"])
    if _is_locked(obj) or obj is None:
        return None
    before = list(obj["position"])
    if "aabb_min" in v and "aabb_max" in v:
        # 実測AABBに基づく押し込み(公称サイズとの乖離に強い)
        b = scene["room"]["bounds"]
        mn, mx = v["aabb_min"], v["aabb_max"]
        for axis, key in ((0, "width"), (2, "depth")):
            limit = b[key]
            if mn[axis] < 0:
                obj["position"][axis] += -mn[axis] + 0.01
            elif mx[axis] > limit:
                obj["position"][axis] -= (mx[axis] - limit) + 0.01
    else:
        _clamp_obj(scene, obj)
    if before == obj["position"]:
        return None
    return f"{obj['id']}: {[round(p,2) for p in before]}→{[round(p,2) for p in obj['position']]}(部屋内へ)"

def _clamp_obj(scene, obj):
    b = scene["room"]["bounds"]
    d = obj.get("target_dimensions") or {}
    th = math.radians(obj.get("rotation_y_deg", 0))
    rw = abs(d.get("width", 0.1) * math.cos(th)) + abs(d.get("depth", 0.1) * math.sin(th))
    rd = abs(d.get("width", 0.1) * math.sin(th)) + abs(d.get("depth", 0.1) * math.cos(th))
    obj["position"][0] = min(max(obj["position"][0], rw / 2 + 0.02), b["width"] - rw / 2 - 0.02)
    obj["position"][2] = min(max(obj["position"][2], rd / 2 + 0.02), b["depth"] - rd / 2 - 0.02)


def rescale(scene, v):
    obj = _obj(scene, v["object_id"])
    if _is_locked(obj) or obj is None:
        return None
    rng = obj.get("class_height_range")
    if not rng:
        return None
    target = (rng[0] + rng[1]) / 2
    d = obj.setdefault("target_dimensions", {})
    old_h = d.get("height", target)
    if old_h <= 0:
        return None
    d["height"] = round(target, 3)
    return f"{obj['id']}: 高さ {old_h:.2f}→{target:.2f}(再スケール・高さのみ)"


def add_object(scene, v, assets_dir):
    """欠落クラスをバリアントプールの既存GLBから追加。位置は空き床の簡易探索"""
    cls = v.get("object_class")
    # 既存の同クラス定義(他シーン共通のプリセット)が無い骨格版では、
    # assets_dir に <cls>_v1.glb 形式のファイルがあることを前提に最小追加を行う
    candidates = sorted(Path(assets_dir).glob(f"{cls}*_v*.glb")) or sorted(Path(assets_dir).glob(f"{cls}*.glb"))
    if not candidates:
        return None  # 手持ちアセットが無い → 9月の再生成対象としてログに残る
    b = scene["room"]["bounds"]
    aabbs = mc.collect_aabbs(scene)
    grid, cell, nx, nz = mc.walkability_grid(scene, aabbs)
    pos = None
    for ix in range(nx):
        for iz in range(nz):
            if grid[ix][iz]:
                pos = [round(ix * cell + cell / 2, 2), 0.0, round(iz * cell + cell / 2, 2)]
                break
        if pos:
            break
    if pos is None:
        return None
    n = sum(1 for o in scene["objects"] if o["class"] == cls) + 1
    scene["objects"].append({
        "id": f"{cls}_{n:02d}", "class": cls,
        "asset": candidates[0].name,
        "asset_variants": [c.name for c in candidates[:3]],
        "position": pos, "rotation_y_deg": 0,
        "target_dimensions": {"width": 0.5, "height": 0.8, "depth": 0.5},
        "must_touch_floor": True, "locked": False,
        "provenance": {"source": "repair:add_object", "prompt": cls},
        "quality_score": None,
    })
    return f"{cls}_{n:02d} を {pos} に追加(欠落補充)※target_dimensions要確認"

# TODO 9月: 巻き戻し時の_failed_repairs照合がrelocateのmsg形式で効いているか検証
def relocate_blocker(scene, v):
    """入口/動線を塞ぐオブジェクトを、歩行グリッドの空き領域へ移動する"""
    # 対象特定: violationにobject_idがあればそれ、なければ入口に最も近い可動物
    oid = v.get("object_id")
    ent = scene["room"].get("entrance", {}).get("position", [0.2, 0.2])
    if oid:
        target = _obj(scene, oid)
    else:
        movables = [o for o in scene["objects"]
                    if not _is_locked(o) and not o.get("rests_on") and not o.get("walkable_over")]
        if not movables:
            return None
        target = min(movables, key=lambda o: (o["position"][0] - ent[0]) ** 2
                                            + (o["position"][2] - ent[1]) ** 2)
    if target is None or _is_locked(target):
        return None
    # 移動先: 対象を除いた歩行グリッドで、入口から遠い空きセルを選ぶ
    rest = {**scene, "objects": [o for o in scene["objects"] if o["id"] != target["id"]]}
    aabbs = mc.collect_aabbs(rest)
    grid, cell, nx, nz = mc.walkability_grid(rest, aabbs)
    b = scene["room"]["bounds"]
    MARGIN = 0.5  # 壁際・隅を避ける(孤立防止)
    best, best_d = None, -1
    for ix in range(nx):
        for iz in range(nz):
            if not grid[ix][iz]:
                continue
            x, z = ix * cell + cell / 2, iz * cell + cell / 2
            if not (MARGIN <= x <= b["width"] - MARGIN and MARGIN <= z <= b["depth"] - MARGIN):
                continue
            # 周囲セルも空いている「開けた場所」を優先(押し込まれ孤立の防止)
            openness = sum(1 for dx in (-1, 0, 1) for dz in (-1, 0, 1)
                           if 0 <= ix + dx < nx and 0 <= iz + dz < nz and grid[ix + dx][iz + dz])
            if openness < 9:
                continue
            d = (x - ent[0]) ** 2 + (z - ent[1]) ** 2
            if d > best_d:
                best, best_d = (x, z), d
    if best is None:
        # 制約を満たすセルが無ければ従来基準(最遠の空きセル)に落とす
        for ix in range(nx):
            for iz in range(nz):
                if not grid[ix][iz]:
                    continue
                x, z = ix * cell + cell / 2, iz * cell + cell / 2
                d = (x - ent[0]) ** 2 + (z - ent[1]) ** 2
                if d > best_d:
                    best, best_d = (x, z), d
    if best is None:
        return None
    old = list(target["position"])
    target["position"][0], target["position"][2] = round(best[0], 2), round(best[1], 2)
    _clamp_obj(scene, target)
    return f"{target['id']}: [{old[0]:.1f},{old[2]:.1f}]→[{target['position'][0]:.1f},{target['position'][2]:.1f}](動線確保のため移動)"

def swap_variant(scene, worst):
    """VLMが指摘した最低品質オブジェクトのアセットを次のバリアントに差し替え"""
    oid = (worst or {}).get("id")
    obj = _obj(scene, oid) if oid else None
    if obj is None or _is_locked(obj):
        return None
    pool = obj.get("asset_variants") or []
    if len(pool) < 2:
        return None
    cur = obj["asset"]
    tried = set(obj.get("_tried_variants", [cur]))
    remaining = [a for a in pool if a not in tried]
    if not remaining:
        return None  # 全バリアント試行済み → 9月の再生成対象
    obj["_tried_variants"] = sorted(tried | {remaining[0]})
    obj["asset"] = remaining[0]
    return f"{obj['id']}: {cur}→{obj['asset']}(バリアント差し替え)"


# ---------- 一括適用 ----------

def apply_repairs(scene, violations, worst_object=None, assets_dir="assets"):
    """違反リスト(+VLMのworst_object)に修正を適用した新しいシーンを返す。
    戻り値: (new_scene, applied: [str])
    """
    new = copy.deepcopy(scene)
    applied = []
    aabbs = mc.collect_aabbs(new)
     # 過去に悪化を招いた修正は再試行しない(オブジェクトID+オペレータで照合)
    failed = set()
    for msg in new.get("_failed_repairs", []):
        oid = msg.split(":")[0].strip()
        failed.add(oid)
    for v in violations:
        op = v.get("suggested_repair")
        target_id = v.get("object_id") or (v.get("object_ids") or [None])[0]
        if target_id in failed:
            continue
        msg = None
        if op == "snap_to_floor":
            msg = snap_to_floor(new, v)
        elif op == "snap_to_parent":
            msg = snap_to_parent(new, v)
        elif op == "push_apart" and v.get("object_ids"):
            msg = push_apart(new, v, aabbs)
            aabbs = mc.collect_aabbs(new)  # 位置が動いたので再計算
        elif op == "push_apart" and not v.get("object_ids") and v.get("type") == "walkability":
            msg = relocate_blocker(new, v)
            aabbs = mc.collect_aabbs(new)
        elif op == "clamp_into_room":
            msg = clamp_into_room(new, v)
        elif op == "rescale":
            msg = rescale(new, v)
        elif op == "add_object":
            msg = add_object(new, v, assets_dir)
       
        if msg:
            applied.append(msg)
    # VLM指摘の低品質オブジェクト(機械検査違反が無い時だけ動かす=修正は1テーマずつ)
    # retexture/relight は9月実装。8月は代替としてバリアント差し替えを試みる
    VLM_OPS = ("swap_variant", "retexture", "relight")
    if not applied and worst_object and worst_object.get("suggested_repair") in VLM_OPS:
        if worst_object.get("id") in failed:
            return new, applied   # 悪化実績のあるオブジェクトへの差し替えは再試行しない
        msg = swap_variant(new, worst_object)
        if msg:
            requested = worst_object.get("suggested_repair")
            if requested != "swap_variant":
                msg += f" ※VLM要求={requested}(未実装のため代替)"
            applied.append(msg)
    return new, applied
