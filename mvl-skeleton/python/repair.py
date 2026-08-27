# repair.py — 修正オペレータ(違反 → シーンJSONの編集)
# 修正対応表(8月版):
#   欠落            → add_object(バリアントプールから追加配置)
#   貫通            → push_apart(transform修正: 最小重なり軸に沿って押し出し)
#   浮遊/めり込み    → snap_to_floor / snap_to_parent(transform修正)
#   スケール逸脱     → rescale(クラス許容範囲の中央値へ)
#   範囲外          → clamp_into_room
#   低品質(VLM指摘) → swap_variant(バリアント差し替え。再生成は9月=スパコン復帰後)
import copy
import json
import math
import re
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


FAILED_OP_WILDCARD = "*"


def normalize_failed_repair(entry):
    """新旧の_failed_repairs要素を(object_id, op)に正規化する。

    旧形式の修正メッセージはop情報を持たないため、そのIDの
    全opを禁止するワイルドカードとして扱う。
    """
    if isinstance(entry, dict):
        object_id = str(entry.get("object_id") or "").strip()
        op = str(entry.get("op") or FAILED_OP_WILDCARD).strip()
        return (object_id, op) if object_id else None
    if isinstance(entry, str):
        text = entry.strip()
        if not text:
            return None
        if "::" in text:
            object_id, op = (part.strip() for part in text.split("::", 1))
            return (object_id, op or FAILED_OP_WILDCARD) if object_id else None
        object_id = text.split(":", 1)[0].strip().split(" ", 1)[0]
        return (object_id, FAILED_OP_WILDCARD) if object_id else None
    return None


def failed_repair_keys(scene):
    return {key for entry in scene.get("_failed_repairs", [])
            if (key := normalize_failed_repair(entry)) is not None}


def is_repair_failed(scene, object_id, op):
    if not object_id:
        return False
    keys = failed_repair_keys(scene)
    return ((object_id, op) in keys
            or (object_id, FAILED_OP_WILDCARD) in keys)


def add_failed_repairs(scene, records):
    """構造化した禁止キーを重複なしで追加し、追加分を返す。"""
    failed = scene.setdefault("_failed_repairs", [])
    existing = failed_repair_keys(scene)
    added = []
    for record in records or []:
        key = normalize_failed_repair(record)
        if key is None or key in existing:
            continue
        item = {"object_id": key[0], "op": key[1]}
        failed.append(item)
        added.append(item)
        existing.add(key)
    return added


def merge_repair_memory(target_scene, source_scene):
    """巻き戻し先に禁止キーと試行済みバリアントを引き継ぐ。"""
    target_scene["_failed_repairs"] = copy.deepcopy(
        source_scene.get("_failed_repairs", []))
    for target in target_scene.get("objects", []):
        source = _obj(source_scene, target.get("id"))
        if source and "_tried_variants" in source:
            target["_tried_variants"] = list(source["_tried_variants"])
    return target_scene


def repair_record(scene, message, op, fallback_object_id=None):
    """ログ文字列とは別に、禁止判定用の修正情報を作る。"""
    object_id = fallback_object_id
    if message:
        for obj in scene.get("objects", []):
            oid = str(obj.get("id") or "")
            if oid and (message.startswith(oid + ":")
                        or message.startswith(oid + " ")):
                object_id = oid
                break
    if not object_id:
        return None
    return {"object_id": object_id, "op": op, "message": message}


def _failed_ids_for_op(scene, op):
    return {object_id for object_id, failed_op in failed_repair_keys(scene)
            if failed_op in (op, FAILED_OP_WILDCARD)}


# ---------- 各オペレータ ----------

# position[1] は「AABBの最下端をどこに置くか」であって接地面ではない
# (Unity側 PlaceObject も bounds.min.y を position[1] に合わせている)。
# 接地オフセットを持つアセットでは position[1] = 目標の接地面 − オフセット にする。
def _place_contact_at(scene, obj, v, plane_y, what):
    off = v.get("contact_offset_m", 0.0)
    old = obj["position"][1]
    obj["position"][1] = plane_y - off
    if abs(obj["position"][1] - old) < 1e-4:
        return None
    tail = f", 接地オフセット{off:+.3f}m" if abs(off) > 1e-6 else ""
    return f"{obj['id']}: y {old:.3f}→{obj['position'][1]:.3f}({what}{tail})"


def snap_to_floor(scene, v):
    obj = _obj(scene, v["object_id"])
    if _is_locked(obj) or obj is None:
        return None
    floor_y = v.get("snap_to", scene["room"].get("floor_y", 0.0))
    return _place_contact_at(scene, obj, v, floor_y, "接地")


def snap_to_parent(scene, v):
    obj = _obj(scene, v["object_id"])
    if _is_locked(obj) or obj is None:
        return None
    plane = v.get("snap_to", obj["position"][1] - v.get("gap", 0))
    return _place_contact_at(scene, obj, v, plane, f"{obj.get('rests_on')}の天面へ")


def push_apart(scene, v, aabbs, excluded_ids=None):
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
    excluded_ids = set(excluded_ids or [])
    candidates = [o for o in (a, b)
                  if not _is_locked(o) and o["id"] not in excluded_ids]
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


def has_penetration(scene, object_id):
    aabbs = mc.collect_aabbs(scene)
    violations = mc.check_penetration(scene, aabbs)

    for violation in violations:
        object_ids = violation.get("object_ids", [])

        if object_id in object_ids:
            return True

    return False


def _validated_relocation_position(scene, target, x, z):
    """候補位置を一時適用し、無変化・貫通なしなら補正後の(x, z)を返す。"""
    old = list(target["position"])
    try:
        target["position"][0] = round(x, 2)
        target["position"][2] = round(z, 2)
        _clamp_obj(scene, target)
        candidate = (target["position"][0], target["position"][2])
        unchanged = (abs(old[0] - candidate[0]) < 1e-4
                     and abs(old[2] - candidate[1]) < 1e-4)
        if unchanged or has_penetration(scene, target["id"]):
            return None
        return candidate
    finally:
        target["position"][:] = old


# TODO 9月: 巻き戻し時の_failed_repairs照合がrelocateのmsg形式で効いているか検証
def relocate_blocker(scene, v, excluded_ids=None):
    """入口/動線を塞ぐオブジェクトを、歩行グリッドの空き領域へ移動する"""
    # 対象特定: violationにobject_idがあればそれ、なければ入口に最も近い可動物
    oid = v.get("object_id")
    excluded_ids = set(excluded_ids or [])
    ent = scene["room"].get("entrance", {}).get("position", [0.2, 0.2])
    if oid:
        if oid in excluded_ids:
            return None
        target = _obj(scene, oid)
    else:
        movables = [o for o in scene["objects"]
                    if (not _is_locked(o) and not o.get("rests_on")
                        and not o.get("walkable_over")
                        and o["id"] not in excluded_ids)]
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
            candidate = _validated_relocation_position(scene, target, x, z)
            if candidate is None:
                continue
            x, z = candidate
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
                candidate = _validated_relocation_position(scene, target, x, z)
                if candidate is None:
                    continue
                x, z = candidate
                d = (x - ent[0]) ** 2 + (z - ent[1]) ** 2
                if d > best_d:
                    best, best_d = (x, z), d
    if best is None:
        return None
    old = list(target["position"])
    target["position"][0], target["position"][2] = round(best[0], 2), round(best[1], 2)
    _clamp_obj(scene, target)

    if (abs(old[0] - target["position"][0]) < 1e-4
        and abs(old[2] - target["position"][2]) < 1e-4):
        return None

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


ASPECT_MISMATCH_MIN = math.log(1.35)
ASPECT_IMPROVEMENT_MIN = math.log(1.15)
ASPECT_IMPROVEMENT_RATIO = 0.80


def load_asset_dimensions(assets_dir):
    """inspect_assets.pyが作ったインベントリからGLB寸法を読む。"""
    path = Path(assets_dir) / "assets_inventory.json"
    if not path.is_file():
        return {}
    try:
        with path.open(encoding="utf-8") as f:
            inventory = json.load(f)
    except (OSError, ValueError, TypeError):
        return {}

    dimensions = {}
    for asset in inventory.get("assets", []):
        dims = asset.get("nominal_dims") or {}
        name = asset.get("file") or (
            f"{asset['asset_id']}.glb" if asset.get("asset_id") else None)
        try:
            xyz = (float(dims["x"]), float(dims["y"]), float(dims["z"]))
        except (KeyError, TypeError, ValueError):
            continue
        if name and all(v > 0 for v in xyz):
            dimensions[name] = xyz
    return dimensions


def aspect_ratio_error(target_dimensions, asset_dimensions):
    """Unityの一様スケール後も残る、幅/高さと奥行/高さの誤差。"""
    try:
        tw = float(target_dimensions["width"])
        th = float(target_dimensions["height"])
        td = float(target_dimensions["depth"])
        ax, ay, az = (float(v) for v in asset_dimensions)
    except (KeyError, TypeError, ValueError):
        return None
    if min(tw, th, td, ax, ay, az) <= 0:
        return None
    width_error = abs(math.log((ax / ay) / (tw / th)))
    depth_error = abs(math.log((az / ay) / (td / th)))
    return max(width_error, depth_error)


def total_aspect_ratio_error(scene, asset_dimensions):
    """寸法が取得できる全オブジェクトの縦横比誤差合計。"""
    errors = []
    for obj in sorted(scene.get("objects", []),
                      key=lambda value: value.get("id", "")):
        error = aspect_ratio_error(
            obj.get("target_dimensions") or {},
            asset_dimensions.get(obj.get("asset")))
        if error is not None:
            errors.append(error)
    return math.fsum(errors) if errors else None


def select_aspect_ratio_variant(scene, asset_dimensions, excluded_ids=None):
    """目標形状に明確に近い未試行バリアントを1つ選ぶ。"""
    best_swap = None
    excluded_ids = set(excluded_ids or [])
    for obj in scene.get("objects", []):
        if _is_locked(obj) or obj.get("id") in excluded_ids:
            continue
        current = obj.get("asset")
        pool = obj.get("asset_variants") or []
        target = obj.get("target_dimensions") or {}
        current_error = aspect_ratio_error(target, asset_dimensions.get(current))
        if current_error is None or current_error < ASPECT_MISMATCH_MIN:
            continue

        tried = set(obj.get("_tried_variants", [current]))
        candidates = []
        for candidate in pool:
            if candidate == current or candidate in tried:
                continue
            error = aspect_ratio_error(target, asset_dimensions.get(candidate))
            if error is not None:
                candidates.append((error, candidate))
        if not candidates:
            continue

        candidate_error, candidate = min(candidates)
        improvement = current_error - candidate_error
        if (improvement < ASPECT_IMPROVEMENT_MIN
                or candidate_error > current_error * ASPECT_IMPROVEMENT_RATIO):
            continue
        proposal = (improvement, obj, candidate, current_error, candidate_error)
        if best_swap is None or proposal[0] > best_swap[0]:
            best_swap = proposal
    return best_swap


def swap_aspect_ratio_variant(scene, asset_dimensions, excluded_ids=None):
    """シーン内で縦横比が最も改善する1オブジェクトを差し替える。"""
    proposal = select_aspect_ratio_variant(
        scene, asset_dimensions, excluded_ids=excluded_ids)
    if proposal is None:
        return None
    _, obj, candidate, current_error, candidate_error = proposal
    current = obj["asset"]
    tried = set(obj.get("_tried_variants", [current]))
    obj["_tried_variants"] = sorted(tried | {candidate})
    obj["asset"] = candidate
    before = math.exp(current_error)
    after = math.exp(candidate_error)
    return (f"{obj['id']}: {current}→{candidate}"
            f"(縦横比補正 最大ずれ {before:.2f}倍→{after:.2f}倍)")


def _payload_text(payload):
    if isinstance(payload, dict):
        return " ".join(_payload_text(v) for v in payload.values())
    if isinstance(payload, list):
        return " ".join(_payload_text(v) for v in payload)
    return str(payload or "")


def resolve_object_id(scene, payload):
    """VLMの注釈付き・誤記IDを、シーンに実在するIDへ可能な範囲で解決する。"""
    payload = payload or {}
    raw_id = str(payload.get("id", "")).strip() if isinstance(payload, dict) else ""
    normalized = raw_id.split("(", 1)[0].strip()
    ids = {o["id"] for o in scene["objects"]}
    if raw_id in ids:
        return raw_id
    if normalized in ids:
        return normalized

    text = _payload_text(payload).lower()
    mentioned_ids = [oid for oid in ids if oid.lower() in text]
    if mentioned_ids:
        return max(mentioned_ids, key=len)

    # "machine_01 (printer)" のようなVLMの別名では、括弧内クラスを優先する。
    for label in re.findall(r"\(([a-z0-9_]+)\)", text):
        matches = [o["id"] for o in scene["objects"]
                   if str(o.get("class", "")).lower() == label]
        if len(matches) == 1:
            return matches[0]

    class_matches = []
    for obj in scene["objects"]:
        cls = str(obj.get("class", "")).lower()
        if cls and re.search(rf"(?<![a-z0-9_]){re.escape(cls)}(?![a-z0-9_])", text):
            class_matches.append(obj["id"])
    return class_matches[0] if len(class_matches) == 1 else None


def repair_visual_floating(scene, object_id):
    """VLMの浮遊指摘を接地修正へ変換し、数値上無変化ならバリアントを替える。"""
    obj = _obj(scene, object_id)
    if obj is None or _is_locked(obj):
        return None
    aabbs = mc.collect_aabbs(scene)
    mn, mx, _ = aabbs[obj["id"]]
    contact_y, contact_offset = mc.contact_y(scene, obj, (mn, mx))

    if obj.get("rests_on"):
        parent = _obj(scene, obj["rests_on"])
        if parent is None:
            return None
        p_mn, p_mx, _ = aabbs[parent["id"]]
        plane_y, _ = mc.support_y(scene, parent, (p_mn, p_mx))
        violation = {
            "object_id": obj["id"],
            "snap_to": plane_y,
            "gap": contact_y - plane_y,
            "contact_offset_m": contact_offset,
        }
        msg = snap_to_parent(scene, violation)
    else:
        floor_y = scene["room"].get("floor_y", 0.0)
        violation = {
            "object_id": obj["id"],
            "snap_to": floor_y,
            "gap": contact_y - floor_y,
            "contact_offset_m": contact_offset,
        }
        msg = snap_to_floor(scene, violation)

    if msg:
        return msg + " ※VLM浮遊指摘"

    # AABB上は接地済みなのに見た目で浮く場合、形状/原点の問題として別GLBを試す。
    msg = swap_variant(scene, {"id": obj["id"]})
    return (msg + " ※VLM浮遊指摘・数値上接地済み") if msg else None


# ---------- 一括適用 ----------

def apply_repairs(scene, violations, worst_object=None, assets_dir="assets",
                  visual_defects=None, asset_dimensions=None,
                  return_records=False):
    """違反リスト(+VLMのworst_object)に修正を適用した新しいシーンを返す。
    通常の戻り値: (new_scene, applied: [str])
    return_records=True: (new_scene, applied, [{object_id, op, message}])
    """
    new = copy.deepcopy(scene)
    applied = []
    records = []
    aabbs = mc.collect_aabbs(new)
    # 過去に悪化または無進展だった修正はID+op単位で再試行しない。
    for v in violations:
        op = v.get("suggested_repair")
        target_id = v.get("object_id")
        if target_id and is_repair_failed(new, target_id, op):
            continue
        excluded_ids = _failed_ids_for_op(new, op)
        before = copy.deepcopy(new)
        msg = None
        if op == "snap_to_floor":
            msg = snap_to_floor(new, v)
        elif op == "snap_to_parent":
            msg = snap_to_parent(new, v)
        elif op == "push_apart" and v.get("object_ids"):
            msg = push_apart(new, v, aabbs, excluded_ids=excluded_ids)
            aabbs = mc.collect_aabbs(new)  # 位置が動いたので再計算
        elif op == "push_apart" and not v.get("object_ids") and v.get("type") == "walkability":
            msg = relocate_blocker(new, v, excluded_ids=excluded_ids)
            aabbs = mc.collect_aabbs(new)
        elif op == "clamp_into_room":
            msg = clamp_into_room(new, v)
        elif op == "rescale":
            msg = rescale(new, v)
        elif op == "add_object":
            msg = add_object(new, v, assets_dir)
       
        if msg:
            record = repair_record(new, msg, op, fallback_object_id=target_id)
            # object_idを持たない違反でも、実際に動かしたIDを使って禁止できる。
            if record and is_repair_failed(
                    new, record["object_id"], record["op"]):
                new = before
                aabbs = mc.collect_aabbs(new)
                continue
            applied.append(msg)
            if record:
                records.append(record)
    # VLMの浮遊指摘を、実在IDへ解決して接地修正へつなぐ。
    if not applied:
        for defect in visual_defects or []:
            if defect.get("kind") != "floating":
                continue
            object_id = resolve_object_id(new, defect)
            op = "repair_visual_floating"
            if not object_id or is_repair_failed(new, object_id, op):
                continue
            msg = repair_visual_floating(new, object_id)
            if msg:
                applied.append(msg)
                records.append(repair_record(new, msg, op, object_id))
                break

    # SceneBuilderは高さだけから一様スケールするため、形の誤差は
    # rescaleでは直らない。寸法表があり、明確に近い別GLBがある時だけ交換する。
    if not applied:
        dimensions = (load_asset_dimensions(assets_dir)
                      if asset_dimensions is None else asset_dimensions)
        op = "swap_aspect_ratio_variant"
        msg = swap_aspect_ratio_variant(
            new, dimensions, excluded_ids=_failed_ids_for_op(new, op))
        if msg:
            applied.append(msg)
            records.append(repair_record(new, msg, op))

    # VLM指摘の低品質オブジェクト(機械検査違反が無い時だけ動かす=修正は1テーマずつ)
    # retexture/relight は9月実装。8月は代替としてバリアント差し替えを試みる
    VLM_OPS = ("swap_variant", "retexture", "relight")
    POSITION_OPS = ("reposition_on_desk", "reposition_on_support")
    requested = (worst_object or {}).get("suggested_repair")
    if not applied and worst_object and requested in VLM_OPS + POSITION_OPS:
        object_id = resolve_object_id(new, worst_object)
        if object_id and not is_repair_failed(new, object_id, requested):
            if requested in POSITION_OPS:
                msg = repair_visual_floating(new, object_id)
            else:
                msg = swap_variant(new, {"id": object_id})
            if msg:
                if requested in ("retexture", "relight"):
                    msg += f" ※VLM要求={requested}(未実装のため代替)"
                applied.append(msg)
                records.append(repair_record(
                    new, msg, requested, fallback_object_id=object_id))
    if return_records:
        return new, applied, [record for record in records if record]
    return new, applied
