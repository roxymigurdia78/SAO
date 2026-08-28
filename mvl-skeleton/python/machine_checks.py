# machine_checks.py — 機械検査(決定的・コードで判定するハード制約)
# シーンJSON(+あればUnityの実測report.json)に対して実行する。
# 検査項目: 欠落 / 貫通 / 浮遊・めり込み / 範囲外 / スケール逸脱 /
#           動線(到達可能性) / 意味的配置(faces・near)
import json
import math
from collections import deque
from functools import lru_cache
from pathlib import Path

import contact_offset as co

FLOOR_TOL = 0.02      # 接地判定の許容差 [m]
PEN_TOL = 0.02        # 貫通とみなす最小めり込み深さ [m]
REST_TOL = 0.06       # rests_on の親上面との許容差 [m]
DEFAULT_FACE_TOLERANCE_DEG = 45.0


# ---------- AABB ----------

def nominal_aabb(obj):
    """target_dimensions と rotation_y_deg から公称AABBを計算(Unity実測が無い場合の代替)"""
    d = obj.get("target_dimensions") or {}
    w, h, dep = d.get("width", 0.1), d.get("height", 0.1), d.get("depth", 0.1)
    th = math.radians(obj.get("rotation_y_deg", 0))
    # 回転後の水平フットプリント
    rw = abs(w * math.cos(th)) + abs(dep * math.sin(th))
    rd = abs(w * math.sin(th)) + abs(dep * math.cos(th))
    x, y, z = obj["position"]
    return ([x - rw / 2, y, z - rd / 2], [x + rw / 2, y + h, z + rd / 2])


def collect_aabbs(scene, report=None):
    """{id: (aabb_min, aabb_max, measured?)} — report.jsonの実測を優先"""
    measured = {}
    if report:
        for r in report.get("objects", []):
            measured[r["id"]] = (r["aabb_min"], r["aabb_max"])
    out = {}
    for obj in scene["objects"]:
        if obj["id"] in measured:
            mn, mx = measured[obj["id"]]
            out[obj["id"]] = (list(mn), list(mx), True)
        else:
            mn, mx = nominal_aabb(obj)
            out[obj["id"]] = (mn, mx, False)
    return out


def overlap_1d(a_min, a_max, b_min, b_max):
    return min(a_max, b_max) - max(a_min, b_min)


def angle_delta_deg(a, b):
    """角度aからbまでの最短符号付き差[-180, 180)。"""
    return (float(b) - float(a) + 180.0) % 360.0 - 180.0


@lru_cache(maxsize=16)
def load_asset_front_offsets(assets_dir):
    """assets_inventory.jsonのfront_offset_degを読む。

    フィールドが無い旧inventoryは従来互換で0度。明示的なnullは
    「未確認」を意味し、orientation検査で0度と仮定しない。
    """
    path = Path(assets_dir) / "assets_inventory.json"
    if not path.is_file():
        return {}
    try:
        with path.open(encoding="utf-8") as f:
            inventory = json.load(f)
    except (OSError, ValueError, TypeError):
        return {}
    offsets = {}
    for asset in inventory.get("assets", []):
        name = asset.get("file") or (
            f"{asset['asset_id']}.glb" if asset.get("asset_id") else None)
        if "front_offset_deg" not in asset:
            offset = 0.0
        elif asset.get("front_offset_deg") is None:
            offset = None
        else:
            try:
                offset = float(asset["front_offset_deg"])
            except (TypeError, ValueError):
                offset = None
        if name:
            offsets[name] = offset
    return offsets


def front_offset_deg(scene, obj, front_offsets=None):
    offsets = (load_asset_front_offsets(str(_assets_dir(scene)))
               if front_offsets is None else front_offsets)
    value = offsets.get(obj.get("asset"), 0.0)
    if value is None:
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return 0.0


def desired_facing_yaw(obj, target):
    """Unityの+Zを正面0度として、obj位置からtargetを向くyawを返す。"""
    dx = float(target["position"][0]) - float(obj["position"][0])
    dz = float(target["position"][2]) - float(obj["position"][2])
    if abs(dx) < 1e-9 and abs(dz) < 1e-9:
        return None
    return math.degrees(math.atan2(dx, dz)) % 360.0


def _faces_constraint(obj):
    faces = obj.get("faces")
    if isinstance(faces, dict):
        target_id = faces.get("target")
        tolerance = faces.get(
            "tolerance_deg", obj.get("faces_tolerance_deg", DEFAULT_FACE_TOLERANCE_DEG))
    else:
        target_id = faces
        tolerance = obj.get("faces_tolerance_deg", DEFAULT_FACE_TOLERANCE_DEG)
    try:
        tolerance = float(tolerance)
    except (TypeError, ValueError):
        tolerance = DEFAULT_FACE_TOLERANCE_DEG
    return target_id, max(0.0, tolerance)


def check_semantic_constraints(scene, front_offsets=None):
    """宣言されたfaces / nearだけを決定的に検査する。"""
    violations = []
    objects = {obj.get("id"): obj for obj in scene.get("objects", [])}
    for obj in scene.get("objects", []):
        target_id, tolerance = _faces_constraint(obj)
        target = objects.get(target_id)
        if target is not None:
            desired = desired_facing_yaw(obj, target)
            if desired is not None:
                offset = front_offset_deg(scene, obj, front_offsets)
                if offset is None:
                    violations.append({
                        "type": "orientation_unverified",
                        "object_id": obj["id"],
                        "target_id": target_id,
                        "detail": (f"{obj['id']} のfront_offset_degが未確認のため "
                                   f"{target_id}への向きを判定できない"),
                        "suggested_repair": None,
                    })
                else:
                    actual_front = (
                        float(obj.get("rotation_y_deg", 0.0)) + offset) % 360.0
                    error = angle_delta_deg(actual_front, desired)
                    if abs(error) > tolerance + 1e-9:
                        violations.append({
                            "type": "orientation",
                            "object_id": obj["id"],
                            "target_id": target_id,
                            "detail": (f"{obj['id']} の正面が {target_id} から "
                                       f"{abs(error):.1f}度ずれている"
                                       f"(許容±{tolerance:g}度)"),
                            "angle_error_deg": error,
                            "desired_rotation_y_deg": (desired - offset) % 360.0,
                            "front_offset_deg": offset,
                            "tolerance_deg": tolerance,
                            "suggested_repair": "orient_to_target",
                        })

        near = obj.get("near")
        if not isinstance(near, dict):
            continue
        near_target_id = near.get("target")
        near_target = objects.get(near_target_id)
        try:
            max_distance = float(near.get("max_distance"))
        except (TypeError, ValueError):
            continue
        if near_target is None or max_distance < 0:
            continue
        dx = float(near_target["position"][0]) - float(obj["position"][0])
        dz = float(near_target["position"][2]) - float(obj["position"][2])
        distance = math.hypot(dx, dz)
        if distance > max_distance + 1e-9:
            violations.append({
                "type": "too_far",
                "object_id": obj["id"],
                "target_id": near_target_id,
                "detail": (f"{obj['id']} と {near_target_id} の距離 {distance:.2f}mが "
                           f"上限 {max_distance:.2f}mを超えている"),
                "distance": distance,
                "max_distance": max_distance,
                "suggested_repair": "move_near",
            })
    return violations


# ---------- 接地面 / 天面 ----------
# 「AABB底面=接地面」「AABB上面=天面」は多くのアセットで成り立たない。
# (下向きの装飾突起、天板より高く伸びる背板 など。2026-08-11の目視で発覚)
# アセットごとの実測オフセット(contact_offsets.json)で補正する。

def _assets_dir(scene):
    return scene.get("assets_dir", "assets")


def contact_y(scene, obj, aabb):
    """そのオブジェクトが「実際に接地する面」のY座標と、AABB底面からのオフセット[m]"""
    mn, mx = aabb[0], aabb[1]
    h = mx[1] - mn[1]
    off = co.lookup(_assets_dir(scene), obj.get("asset"), obj, "contact_offset") * h
    return mn[1] + off, off


def support_y(scene, obj, aabb):
    """そのオブジェクトの「物を載せられる天面」のY座標(机なら天板、椅子なら座面)"""
    mn, mx = aabb[0], aabb[1]
    h = mx[1] - mn[1]
    off = co.lookup(_assets_dir(scene), obj.get("asset"), obj, "support_offset") * h
    return mx[1] - off, off


# ---------- 各検査 ----------

def check_missing(scene):
    v = []
    counts = {}
    for obj in scene["objects"]:
        counts[obj["class"]] = counts.get(obj["class"], 0) + 1
    for req in scene.get("spec", {}).get("required_objects", []):
        have = counts.get(req["class"], 0)
        need = req.get("min_count", 1)
        if have < need:
            v.append({"type": "missing", "object_class": req["class"],
                      "detail": f"必須 {req['class']} が {have}/{need}",
                      "suggested_repair": "add_object"})
    return v


def check_penetration(scene, aabbs):
    v = []
    objs = {o["id"]: o for o in scene["objects"]}
    ids = [o["id"] for o in scene["objects"]]
    for i in range(len(ids)):
        for j in range(i + 1, len(ids)):
            a, b = objs[ids[i]], objs[ids[j]]
            # 載っている関係(ランプ←→机)と敷物は貫通扱いしない
            if a.get("rests_on") == b["id"] or b.get("rests_on") == a["id"]:
                continue
            if a.get("walkable_over") or b.get("walkable_over"):
                continue
            (amn, amx, _), (bmn, bmx, _) = aabbs[a["id"]], aabbs[b["id"]]
            depths = [overlap_1d(amn[k], amx[k], bmn[k], bmx[k]) for k in range(3)]
            if all(d > PEN_TOL for d in depths):
                v.append({"type": "penetration", "object_ids": [a["id"], b["id"]],
                          "detail": f"めり込み深さ x/y/z = {[round(d, 3) for d in depths]}",
                          "overlap": depths,
                          "aabbs": {a["id"]: [amn, amx], b["id"]: [bmn, bmx]},
                          "suggested_repair": "push_apart"})
    return v


def check_floating(scene, aabbs):
    v = []
    objs = {o["id"]: o for o in scene["objects"]}
    floor_y = scene["room"].get("floor_y", 0.0)
    for obj in scene["objects"]:
        mn, mx, _ = aabbs[obj["id"]]
        c_y, c_off = contact_y(scene, obj, (mn, mx))
        review = co.needs_review(_assets_dir(scene), obj.get("asset"), obj)
        note = f"(接地オフセット{c_off:+.3f}m)" if abs(c_off) > 1e-6 else ""
        if review:
            note = note[:-1] + " + 未確定)" if note else "(接地オフセット未確定)"
        tol = REST_TOL * 2 if review else REST_TOL
        if obj.get("rests_on"):
            parent = objs.get(obj["rests_on"])
            if parent is None:
                v.append({"type": "floating", "object_id": obj["id"],
                          "detail": f"rests_on先 {obj['rests_on']} が存在しない",
                          "contact_offset_m": c_off,
                          "suggested_repair": "snap_to_floor"})
                continue
            p_mn, p_mx, _ = aabbs[parent["id"]]
            p_top, s_off = support_y(scene, parent, (p_mn, p_mx))
            if abs(s_off) > 1e-6:
                note += f"(親の天面はAABB上端より{s_off:.3f}m下)"
            gap = c_y - p_top
            if abs(gap) > tol:
                detail = f"{obj['rests_on']} の天面から {gap:+.3f}m {note}".rstrip()
                if review:
                    detail += " (オフセット未確定)"
                v.append({"type": "floating", "object_id": obj["id"],
                          "detail": detail,
                          "gap": gap, "snap_to": p_top, "contact_offset_m": c_off,
                          "suggested_repair": "snap_to_parent"})
        elif obj.get("must_touch_floor", True):
            gap = c_y - floor_y
            if gap > FLOOR_TOL:
                detail = f"床から {gap:.3f}m 浮遊 {note}".rstrip()
                if review:
                    detail += " (オフセット未確定)"
                v.append({"type": "floating", "object_id": obj["id"],
                          "detail": detail, "gap": gap,
                          "snap_to": floor_y, "contact_offset_m": c_off,
                          "suggested_repair": "snap_to_floor"})
            elif gap < -FLOOR_TOL:
                detail = f"床に {-gap:.3f}m めり込み {note}".rstrip()
                if review:
                    detail += " (オフセット未確定)"
                v.append({"type": "sunken", "object_id": obj["id"],
                          "detail": detail, "gap": gap,
                          "snap_to": floor_y, "contact_offset_m": c_off,
                          "suggested_repair": "snap_to_floor"})
    return v


def check_bounds(scene, aabbs):
    v = []
    b = scene["room"]["bounds"]
    for obj in scene["objects"]:
        mn, mx, _ = aabbs[obj["id"]]
        out = (mn[0] < -0.01 or mn[2] < -0.01 or
               mx[0] > b["width"] + 0.01 or mx[2] > b["depth"] + 0.01 or
               mx[1] > b["height"] + 0.01)
        if out:
            v.append({"type": "out_of_bounds", "object_id": obj["id"],
                      "detail": f"AABB {[round(x, 2) for x in mn]}〜{[round(x, 2) for x in mx]} が部屋 "
                                f"{b['width']}x{b['depth']}x{b['height']} を超過",
                                 "aabb_min": list(mn), "aabb_max": list(mx),   # ← この行を追加
                      "suggested_repair": "clamp_into_room"})
    return v


def check_scale(scene, aabbs):
    v = []
    for obj in scene["objects"]:
        rng = obj.get("class_height_range")
        if not rng:
            continue
        mn, mx, measured = aabbs[obj["id"]]
        h = mx[1] - mn[1]
        if h < rng[0] * 0.9 or h > rng[1] * 1.1:
            v.append({"type": "scale", "object_id": obj["id"],
                      "detail": f"高さ {h:.2f}m がクラス許容 {rng} を逸脱"
                                + ("(実測)" if measured else "(公称)"),
                      "measured_height": h,
                      "suggested_repair": "rescale"})
    return v


def walkability_grid(scene, aabbs):
    """歩行可能グリッド(True=歩ける)を返す。障害物AABBのフットプリントをagent_radiusで膨張"""
    b = scene["room"]["bounds"]
    wk = scene.get("walkable", {})
    cell = wk.get("grid_cell", 0.1)
    radius = wk.get("agent_radius", 0.3)
    nx, nz = max(1, int(b["width"] / cell)), max(1, int(b["depth"] / cell))
    grid = [[True] * nz for _ in range(nx)]
    for obj in scene["objects"]:
        if obj.get("walkable_over") or obj.get("rests_on"):
            continue
        mn, mx, _ = aabbs[obj["id"]]
        if mn[1] > 1.9:  # 頭上より高い物(照明等)は障害物でない
            continue
        x0 = int((mn[0] - radius) / cell); x1 = int((mx[0] + radius) / cell)
        z0 = int((mn[2] - radius) / cell); z1 = int((mx[2] + radius) / cell)
        for ix in range(max(0, x0), min(nx, x1 + 1)):
            for iz in range(max(0, z0), min(nz, z1 + 1)):
                grid[ix][iz] = False
    return grid, cell, nx, nz


def walkability_reach_ratio(scene, aabbs=None):
    """入口から到達できる自由セル / 全自由セルを0〜1で返す。

    check_walkabilityの違反有無とは独立に常時取得できるため、修正候補の
    非悪化判定と反復ログの推移記録に使う。
    """
    aabbs = aabbs or collect_aabbs(scene)
    grid, cell, nx, nz = walkability_grid(scene, aabbs)
    free = sum(row.count(True) for row in grid)
    if free == 0:
        return 0.0
    ent = scene["room"].get("entrance", {}).get("position", [0.2, 0.2])
    sx = min(nx - 1, max(0, int(ent[0] / cell)))
    sz = min(nz - 1, max(0, int(ent[1] / cell)))
    if not grid[sx][sz]:
        found = False
        for radius in range(1, 8):
            for dx in range(-radius, radius + 1):
                for dz in range(-radius, radius + 1):
                    x, z = sx + dx, sz + dz
                    if 0 <= x < nx and 0 <= z < nz and grid[x][z]:
                        sx, sz, found = x, z, True
                        break
                if found:
                    break
            if found:
                break
        if not found:
            return 0.0
    seen = [[False] * nz for _ in range(nx)]
    queue = deque([(sx, sz)])
    seen[sx][sz] = True
    reach = 0
    while queue:
        x, z = queue.popleft()
        reach += 1
        for dx, dz in ((1, 0), (-1, 0), (0, 1), (0, -1)):
            xx, zz = x + dx, z + dz
            if (0 <= xx < nx and 0 <= zz < nz and grid[xx][zz]
                    and not seen[xx][zz]):
                seen[xx][zz] = True
                queue.append((xx, zz))
    return reach / free


def check_walkability(scene, aabbs):
    v = []
    grid, cell, nx, nz = walkability_grid(scene, aabbs)
    ent = scene["room"].get("entrance", {}).get("position", [0.2, 0.2])
    sx, sz = min(nx - 1, int(ent[0] / cell)), min(nz - 1, int(ent[1] / cell))
    # 入口セルが塞がっていれば近傍の空きセルを探す
    if not grid[sx][sz]:
        found = False
        for r in range(1, 8):
            for dx in range(-r, r + 1):
                for dz in range(-r, r + 1):
                    x, z = sx + dx, sz + dz
                    if 0 <= x < nx and 0 <= z < nz and grid[x][z]:
                        sx, sz, found = x, z, True
                        break
                if found: break
            if found: break
        if not found:
            v.append({"type": "walkability", "detail": "入口周辺が完全に塞がっている",
                      "suggested_repair": "push_apart"})
            return v
    # BFS
    seen = [[False] * nz for _ in range(nx)]
    q = deque([(sx, sz)])
    seen[sx][sz] = True
    reach = 0
    while q:
        x, z = q.popleft()
        reach += 1
        for dx, dz in ((1, 0), (-1, 0), (0, 1), (0, -1)):
            X, Z = x + dx, z + dz
            if 0 <= X < nx and 0 <= Z < nz and grid[X][Z] and not seen[X][Z]:
                seen[X][Z] = True
                q.append((X, Z))
    free = sum(row.count(True) for row in grid)
    ratio = reach / free if free else 0.0
    if ratio < 0.85:
        v.append({"type": "walkability",
                  "detail": f"自由床面の到達率 {ratio:.0%}(孤立領域あり)",
                  "reach_ratio": ratio, "suggested_repair": "push_apart"})
    # 必須オブジェクトに近づけるか(隣接セルに到達可能セルがあるか)。
    # rests_on子は支持体単位に集約し、机上6点を6件として水増ししない。
    req_classes = {r["class"] for r in scene.get("spec", {}).get("required_objects", [])}
    objs_by_id = {o["id"]: o for o in scene["objects"]}
    required_by_base = {}
    for obj in scene["objects"]:
        if obj.get("class") not in req_classes:
            continue
        base = obj
        hops = 0
        while base.get("rests_on") and base["rests_on"] in objs_by_id and hops < 5:
            base = objs_by_id[base["rests_on"]]
            hops += 1
        required_by_base.setdefault(base["id"], []).append(obj["id"])

    for base_id, included_ids in required_by_base.items():
        base = objs_by_id[base_id]
        mn, mx, _ = aabbs[base["id"]]
        ok = False
        margin = scene.get("walkable", {}).get("agent_radius", 0.3) + 0.25
        x0 = int((mn[0] - margin) / cell); x1 = int((mx[0] + margin) / cell)
        z0 = int((mn[2] - margin) / cell); z1 = int((mx[2] + margin) / cell)
        for ix in range(max(0, x0), min(nx, x1 + 1)):
            for iz in range(max(0, z0), min(nz, z1 + 1)):
                if seen[ix][iz]:
                    ok = True
                    break
            if ok: break
        if not ok:
            children = sorted(oid for oid in included_ids if oid != base_id)
            suffix = f" (上載せ{len(children)}点を含む)" if children else ""
            v.append({"type": "walkability", "object_id": base_id,
                      "included_object_ids": sorted(included_ids),
                      "detail": f"必須オブジェクト {base_id} に入口から到達できない{suffix}",
                      "suggested_repair": "push_apart"})
    return v


# ---------- エントリポイント ----------

def run_all(scene, report=None):
    """全検査を実行して違反リストを返す"""
    aabbs = collect_aabbs(scene, report)
    violations = []
    violations += check_missing(scene)
    violations += check_penetration(scene, aabbs)
    violations += check_floating(scene, aabbs)
    violations += check_bounds(scene, aabbs)
    violations += check_scale(scene, aabbs)
    violations += check_walkability(scene, aabbs)
    violations += check_semantic_constraints(scene)
    return violations


if __name__ == "__main__":
    import argparse
    ap = argparse.ArgumentParser(description="シーンJSONの機械検査")
    ap.add_argument("scene_json")
    ap.add_argument("--report", help="Unityのreport.json(あれば実測AABBを使う)")
    args = ap.parse_args()
    scene = json.loads(Path(args.scene_json).read_text(encoding="utf-8"))
    report = json.loads(Path(args.report).read_text(encoding="utf-8")) if args.report else None
    vs = run_all(scene, report)
    print(json.dumps(vs, ensure_ascii=False, indent=2))
    print(f"\n違反 {len(vs)} 件")
