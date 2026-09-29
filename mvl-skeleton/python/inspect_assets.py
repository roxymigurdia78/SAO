#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
inspect_assets.py -- TRELLIS出力GLBの一括検品 + アセットインベントリ生成

依存: Python標準ライブラリのみ(numpy等の追加インストール不要)

使い方:
    python inspect_assets.py --root D:\\mvl\\assets --out assets_inventory.json --csv report.csv

出力:
    assets_inventory.json  … シーンJSONの asset_id -> path 解決に使うマスタ
    report.csv             … Excelで開いて目視する検品表

検査項目:
    公称AABB(寸法) / 三角形数 / メッシュ・ノード数 / マテリアル / テクスチャ解像度
    法線マップ有無 / Draco圧縮 / 破損 / 単位スケールの異常
"""

import argparse
import base64
import csv
import json
import os
import re
import struct
import sys
from datetime import datetime, timezone

# ---------------------------------------------------------------- GLB 読み込み

GLB_MAGIC = 0x46546C67  # 'glTF'
CHUNK_JSON = 0x4E4F534A
CHUNK_BIN = 0x004E4942


class GlbError(Exception):
    pass


def read_glb(path):
    """GLB/glTFを読み、(gltf_dict, bin_blob) を返す。"""
    with open(path, "rb") as f:
        data = f.read()
    if len(data) < 12:
        raise GlbError("ファイルが小さすぎる(12バイト未満)")

    # .gltf (JSON) も一応受け付ける
    if data[:1] in (b"{", b"\xef"):
        txt = data.decode("utf-8-sig")
        return json.loads(txt), b""

    magic, version, length = struct.unpack("<III", data[:12])
    if magic != GLB_MAGIC:
        raise GlbError("GLBマジックが不正(壊れている可能性)")
    if version != 2:
        raise GlbError("glTF version %d は非対応(2のみ)" % version)
    if length > len(data):
        raise GlbError("ヘッダ長=%d > 実ファイル長=%d(切り詰められている)" % (length, len(data)))

    gltf = None
    binblob = b""
    off = 12
    while off + 8 <= length:
        clen, ctype = struct.unpack("<II", data[off:off + 8])
        off += 8
        if off + clen > len(data):
            raise GlbError("チャンクが途中で切れている")
        chunk = data[off:off + clen]
        off += clen
        if ctype == CHUNK_JSON and gltf is None:
            gltf = json.loads(chunk.decode("utf-8-sig"))
        elif ctype == CHUNK_BIN and not binblob:
            binblob = chunk
    if gltf is None:
        raise GlbError("JSONチャンクが無い")
    return gltf, binblob


# ---------------------------------------------------------------- 行列ユーティリティ

def mat_identity():
    return [1.0, 0, 0, 0, 0, 1.0, 0, 0, 0, 0, 1.0, 0, 0, 0, 0, 1.0]


def mat_mul(a, b):
    """列優先(glTF準拠) 4x4 の積 a*b。"""
    out = [0.0] * 16
    for c in range(4):
        for r in range(4):
            s = 0.0
            for k in range(4):
                s += a[k * 4 + r] * b[c * 4 + k]
            out[c * 4 + r] = s
    return out


def trs_to_mat(t, r, s):
    tx, ty, tz = t
    x, y, z, w = r
    sx, sy, sz = s
    # 回転行列(クォータニオン)
    m00 = 1 - 2 * (y * y + z * z)
    m01 = 2 * (x * y - z * w)
    m02 = 2 * (x * z + y * w)
    m10 = 2 * (x * y + z * w)
    m11 = 1 - 2 * (x * x + z * z)
    m12 = 2 * (y * z - x * w)
    m20 = 2 * (x * z - y * w)
    m21 = 2 * (y * z + x * w)
    m22 = 1 - 2 * (x * x + y * y)
    return [
        m00 * sx, m10 * sx, m20 * sx, 0.0,
        m01 * sy, m11 * sy, m21 * sy, 0.0,
        m02 * sz, m12 * sz, m22 * sz, 0.0,
        tx, ty, tz, 1.0,
    ]


def node_matrix(node):
    if "matrix" in node:
        return list(node["matrix"])
    return trs_to_mat(
        node.get("translation", [0.0, 0.0, 0.0]),
        node.get("rotation", [0.0, 0.0, 0.0, 1.0]),
        node.get("scale", [1.0, 1.0, 1.0]),
    )


def xform_point(m, p):
    x, y, z = p
    return (
        m[0] * x + m[4] * y + m[8] * z + m[12],
        m[1] * x + m[5] * y + m[9] * z + m[13],
        m[2] * x + m[6] * y + m[10] * z + m[14],
    )


# ---------------------------------------------------------------- 画像サイズ判定

def image_size(blob):
    """PNG/JPEG/WebPのバイト列から (w, h) を取る。判別不能はNone。"""
    if len(blob) < 16:
        return None
    if blob[:8] == b"\x89PNG\r\n\x1a\n":
        w, h = struct.unpack(">II", blob[16:24])
        return (w, h)
    if blob[:2] == b"\xff\xd8":  # JPEG
        i = 2
        n = len(blob)
        while i + 9 < n:
            if blob[i] != 0xFF:
                i += 1
                continue
            marker = blob[i + 1]
            if marker in (0xD8, 0x01) or 0xD0 <= marker <= 0xD7:
                i += 2
                continue
            seglen = struct.unpack(">H", blob[i + 2:i + 4])[0]
            if 0xC0 <= marker <= 0xCF and marker not in (0xC4, 0xC8, 0xCC):
                h, w = struct.unpack(">HH", blob[i + 5:i + 9])
                return (w, h)
            i += 2 + seglen
        return None
    if blob[:4] == b"RIFF" and blob[8:12] == b"WEBP":
        if blob[12:16] == b"VP8X":
            w = int.from_bytes(blob[24:27], "little") + 1
            h = int.from_bytes(blob[27:30], "little") + 1
            return (w, h)
        if blob[12:16] == b"VP8L":
            b = blob[21:25]
            v = int.from_bytes(b, "little")
            return ((v & 0x3FFF) + 1, ((v >> 14) & 0x3FFF) + 1)
        if blob[12:16] == b"VP8 ":
            w = struct.unpack("<H", blob[26:28])[0] & 0x3FFF
            h = struct.unpack("<H", blob[28:30])[0] & 0x3FFF
            return (w, h)
    return None


def get_image_bytes(gltf, binblob, img):
    if "uri" in img:
        uri = img["uri"]
        if uri.startswith("data:"):
            head, _, b64 = uri.partition(",")
            if "base64" in head:
                return base64.b64decode(b64)
        return None  # 外部ファイル参照(GLB単体では自己完結していない)
    bv_i = img.get("bufferView")
    if bv_i is None:
        return None
    bv = gltf.get("bufferViews", [])[bv_i]
    off = bv.get("byteOffset", 0)
    ln = bv.get("byteLength", 0)
    return binblob[off:off + ln]


# ---------------------------------------------------------------- 検品本体

COMP_SIZE = {5120: 1, 5121: 1, 5122: 2, 5123: 2, 5125: 4, 5126: 4}


def count_triangles(gltf, mesh):
    tris = 0
    unknown = False
    accessors = gltf.get("accessors", [])
    for prim in mesh.get("primitives", []):
        mode = prim.get("mode", 4)
        if "indices" in prim:
            cnt = accessors[prim["indices"]].get("count", 0)
        else:
            pos = prim.get("attributes", {}).get("POSITION")
            cnt = accessors[pos].get("count", 0) if pos is not None else 0
        if cnt == 0:
            unknown = True
            continue
        if mode == 4:
            tris += cnt // 3
        elif mode in (5, 6):
            tris += max(0, cnt - 2)
        else:
            unknown = True
    return tris, unknown


def inspect(path, cfg):
    rec = {
        "file": os.path.basename(path),
        "path": os.path.abspath(path),
        "file_size_mb": round(os.path.getsize(path) / 1e6, 3),
        "ok": True,
        "warnings": [],
        "errors": [],
    }
    try:
        gltf, binblob = read_glb(path)
    except Exception as e:
        rec["ok"] = False
        rec["errors"].append("読み込み失敗: %s" % e)
        return rec

    ext_req = gltf.get("extensionsRequired", []) or []
    rec["extensions_required"] = ext_req
    draco = "KHR_draco_mesh_compression" in ext_req
    rec["draco"] = draco

    meshes = gltf.get("meshes", []) or []
    nodes = gltf.get("nodes", []) or []
    accessors = gltf.get("accessors", []) or []

    # --- シーングラフを辿って world AABB を出す
    lo = [float("inf")] * 3
    hi = [float("-inf")] * 3
    mesh_nodes = 0
    missing_minmax = False

    scenes = gltf.get("scenes", []) or []
    scene_i = gltf.get("scene", 0)
    if scenes:
        roots = scenes[min(scene_i, len(scenes) - 1)].get("nodes", [])
    else:
        roots = list(range(len(nodes)))

    stack = [(i, mat_identity()) for i in roots]
    seen = 0
    while stack:
        seen += 1
        if seen > 100000:
            rec["warnings"].append("ノード階層が異常に深い/循環の疑い")
            break
        ni, parent = stack.pop()
        if ni >= len(nodes):
            continue
        node = nodes[ni]
        world = mat_mul(parent, node_matrix(node))
        if "mesh" in node and node["mesh"] < len(meshes):
            mesh_nodes += 1
            for prim in meshes[node["mesh"]].get("primitives", []):
                pos_i = prim.get("attributes", {}).get("POSITION")
                if pos_i is None or pos_i >= len(accessors):
                    continue
                acc = accessors[pos_i]
                mn, mx = acc.get("min"), acc.get("max")
                if not mn or not mx:
                    missing_minmax = True
                    continue
                for cx in (mn[0], mx[0]):
                    for cy in (mn[1], mx[1]):
                        for cz in (mn[2], mx[2]):
                            wp = xform_point(world, (cx, cy, cz))
                            for k in range(3):
                                lo[k] = min(lo[k], wp[k])
                                hi[k] = max(hi[k], wp[k])
        for ch in node.get("children", []):
            stack.append((ch, world))

    if lo[0] == float("inf"):
        rec["ok"] = False
        rec["errors"].append("頂点バウンディングボックスを取得できなかった"
                             + ("(accessorにmin/max無し)" if missing_minmax else "(メッシュ無し)"))
        dims = [0.0, 0.0, 0.0]
    else:
        dims = [round(hi[k] - lo[k], 5) for k in range(3)]

    rec["nominal_dims"] = {"x": dims[0], "y": dims[1], "z": dims[2]}
    rec["nominal_height_y"] = dims[1]
    rec["longest_axis_m"] = round(max(dims), 5)
    rec["aabb_min"] = [round(v, 5) for v in lo] if lo[0] != float("inf") else None
    rec["aabb_max"] = [round(v, 5) for v in hi] if lo[0] != float("inf") else None
    # 接地オフセット: 最小Yが0からどれだけずれているか(SceneBuilderの接地補正の参考値)
    rec["min_y"] = round(lo[1], 5) if lo[0] != float("inf") else None

    # --- 三角形数
    tris = 0
    unknown_tris = False
    for m in meshes:
        t, u = count_triangles(gltf, m)
        tris += t
        unknown_tris = unknown_tris or u
    rec["tri_count"] = tris
    rec["mesh_count"] = len(meshes)
    rec["mesh_node_count"] = mesh_nodes
    rec["primitive_count"] = sum(len(m.get("primitives", [])) for m in meshes)

    # --- マテリアル/テクスチャ
    images = gltf.get("images", []) or []
    textures = gltf.get("textures", []) or []
    img_sizes = []
    external_image = False
    for img in images:
        blob = get_image_bytes(gltf, binblob, img)
        if blob is None:
            external_image = True
            img_sizes.append(None)
            continue
        img_sizes.append(image_size(blob))

    def tex_px(texinfo):
        if not texinfo:
            return None
        ti = texinfo.get("index")
        if ti is None or ti >= len(textures):
            return None
        src = textures[ti].get("source")
        if src is None and "extensions" in textures[ti]:
            for v in textures[ti]["extensions"].values():
                if isinstance(v, dict) and "source" in v:
                    src = v["source"]
                    break
        if src is None or src >= len(img_sizes):
            return None
        return img_sizes[src]

    mats = []
    has_normal = False
    has_basecolor_tex = False
    has_mr_tex = False
    max_px = 0
    for m in gltf.get("materials", []) or []:
        pbr = m.get("pbrMetallicRoughness", {}) or {}
        bc = tex_px(pbr.get("baseColorTexture"))
        mr = tex_px(pbr.get("metallicRoughnessTexture"))
        nm = tex_px(m.get("normalTexture"))
        oc = tex_px(m.get("occlusionTexture"))
        em = tex_px(m.get("emissiveTexture"))
        has_basecolor_tex = has_basecolor_tex or bc is not None
        has_mr_tex = has_mr_tex or mr is not None
        has_normal = has_normal or ("normalTexture" in m)
        for s in (bc, mr, nm, oc, em):
            if s:
                max_px = max(max_px, s[0], s[1])
        mats.append({
            "name": m.get("name", ""),
            "basecolor_px": bc,
            "metallicRoughness_px": mr,
            "normal_px": nm,
            "occlusion_px": oc,
            "emissive_px": em,
            "baseColorFactor": pbr.get("baseColorFactor"),
            "metallic": pbr.get("metallicFactor"),
            "roughness": pbr.get("roughnessFactor"),
            "alphaMode": m.get("alphaMode", "OPAQUE"),
            "doubleSided": m.get("doubleSided", False),
        })
    rec["materials"] = mats
    rec["material_count"] = len(mats)
    rec["image_count"] = len(images)
    rec["max_texture_px"] = max_px or None
    rec["has_basecolor_texture"] = has_basecolor_tex
    rec["has_normal_map"] = has_normal
    rec["has_metallicRoughness_texture"] = has_mr_tex

    # --- UV有無(ベイク用UV2はUnity側で生成するが、UV0は必須)
    has_uv = False
    for m in meshes:
        for prim in m.get("primitives", []):
            if "TEXCOORD_0" in prim.get("attributes", {}):
                has_uv = True
    rec["has_uv0"] = has_uv

    # ---------------- 警告判定
    w = rec["warnings"]
    if draco:
        w.append("Draco圧縮: glTFastにDracoパッケージが必要(未導入だとUnityで読めない)")
    if external_image:
        w.append("テクスチャが外部ファイル参照: GLB単体で自己完結していない")
    if unknown_tris:
        w.append("三角形数を確定できないプリミティブがある")
    if not has_uv:
        w.append("UV0が無い: テクスチャもライトマップベイクも成立しない")
    if not has_basecolor_tex:
        w.append("baseColorテクスチャ無し(単色マテリアル)→ B4=2止まりの候補")
    if not has_normal:
        w.append("法線マップ無し(9月のリテクスチャ対象)")
    if max_px and max_px < 512:
        w.append("テクスチャ解像度が低い(%dpx)" % max_px)
    if tris > cfg["tri_warn_high"]:
        w.append("高ポリ(%d tri): デシメーション必須" % tris)
    if 0 < tris < cfg["tri_warn_low"]:
        w.append("低ポリすぎ(%d tri): 生成失敗の疑い" % tris)
    if rec["longest_axis_m"] == 0:
        w.append("寸法ゼロ: 空メッシュ")
    elif not (cfg["dim_min"] <= rec["longest_axis_m"] <= cfg["dim_max"]):
        w.append("公称寸法が想定外(最長辺 %.3f): SceneBuilderの強制スケールで吸収されるが要確認"
                 % rec["longest_axis_m"])
    if mesh_nodes > 1:
        w.append("メッシュノードが%d個: 複数部品構成の可能性(F3=一点集約による配置崩壊に注意)" % mesh_nodes)
    if rec["material_count"] == 0:
        w.append("マテリアル無し")
    if rec["errors"]:
        rec["ok"] = False
    return rec


# ---------------------------------------------------------------- クラス推定

VARIANT_RE = re.compile(
    r"^(?P<cls>.+?)[ _\-]*(?:v(?:ar(?:iant)?)?[ _\-]?(?P<v>\d+)|(?P<v2>\d+))$",
    re.IGNORECASE,
)


def split_class_variant(stem):
    m = VARIANT_RE.match(stem)
    if m:
        v = m.group("v") or m.group("v2")
        cls = m.group("cls").strip(" _-")
        if cls:
            return cls, int(v)
    return stem, None


# ---------------------------------------------------------------- main

def main():
    ap = argparse.ArgumentParser(description="TRELLIS出力GLBの一括検品")
    ap.add_argument("--root", required=True, help="GLBを含むフォルダ(再帰探索)")
    ap.add_argument("--out", default="assets_inventory.json")
    ap.add_argument("--csv", default="report.csv")
    ap.add_argument("--tri-warn-high", type=int, default=200000)
    ap.add_argument("--tri-warn-low", type=int, default=200)
    ap.add_argument("--dim-min", type=float, default=0.05)
    ap.add_argument("--dim-max", type=float, default=20.0)
    ap.add_argument("--expect", type=int, default=0, help="期待ファイル数(例: 48)。不一致なら警告")
    args = ap.parse_args()

    cfg = {
        "tri_warn_high": args.tri_warn_high,
        "tri_warn_low": args.tri_warn_low,
        "dim_min": args.dim_min,
        "dim_max": args.dim_max,
    }

    files = []
    for dirpath, _, names in os.walk(args.root):
        for n in sorted(names):
            if n.lower().endswith((".glb", ".gltf")):
                files.append(os.path.join(dirpath, n))
    files.sort()

    if not files:
        print("GLBが見つからない: %s" % args.root, file=sys.stderr)
        return 2

    assets = []
    for p in files:
        rec = inspect(p, cfg)
        stem = os.path.splitext(os.path.basename(p))[0]
        cls, var = split_class_variant(stem)
        rec["asset_id"] = stem
        rec["class"] = cls
        rec["variant"] = var
        rec["room"] = os.path.basename(os.path.dirname(p))
        assets.append(rec)

    n_ng = sum(1 for a in assets if not a["ok"])
    n_warn = sum(1 for a in assets if a["ok"] and a["warnings"])

    # クラスごとのバリアント数
    by_class = {}
    for a in assets:
        by_class.setdefault((a["room"], a["class"]), []).append(a["asset_id"])

    inv = {
        "generated_at": datetime.now(timezone.utc).astimezone().isoformat(timespec="seconds"),
        "root": os.path.abspath(args.root),
        "count": len(assets),
        "n_error": n_ng,
        "n_warning": n_warn,
        "classes": {"%s/%s" % k: sorted(v) for k, v in sorted(by_class.items())},
        "assets": assets,
    }
    with open(args.out, "w", encoding="utf-8") as f:
        json.dump(inv, f, ensure_ascii=False, indent=2)

    cols = ["room", "class", "variant", "asset_id", "ok", "tri_count",
            "dim_x", "dim_y", "dim_z", "longest_axis_m", "min_y",
            "mesh_node_count", "material_count", "max_texture_px",
            "has_uv0", "has_basecolor_texture", "has_normal_map",
            "draco", "file_size_mb", "warnings", "errors", "path"]
    with open(args.csv, "w", encoding="utf-8-sig", newline="") as f:
        wtr = csv.writer(f)
        wtr.writerow(cols)
        for a in assets:
            d = a.get("nominal_dims", {})
            wtr.writerow([
                a.get("room"), a.get("class"), a.get("variant"), a.get("asset_id"),
                "OK" if a["ok"] else "NG", a.get("tri_count"),
                d.get("x"), d.get("y"), d.get("z"), a.get("longest_axis_m"), a.get("min_y"),
                a.get("mesh_node_count"), a.get("material_count"), a.get("max_texture_px"),
                a.get("has_uv0"), a.get("has_basecolor_texture"), a.get("has_normal_map"),
                a.get("draco"), a.get("file_size_mb"),
                " / ".join(a.get("warnings", [])), " / ".join(a.get("errors", [])),
                a.get("path"),
            ])

    print("=" * 70)
    print("検品結果: %d件 (NG %d / 警告 %d)" % (len(assets), n_ng, n_warn))
    if args.expect and len(assets) != args.expect:
        print("!! 期待%d件に対して%d件しかない" % (args.expect, len(assets)))
    print("=" * 70)
    for a in assets:
        if not a["ok"]:
            print("[NG]   %-34s %s" % (a["asset_id"], "; ".join(a["errors"])))
    for a in assets:
        if a["ok"] and a["warnings"]:
            print("[WARN] %-34s %s" % (a["asset_id"], "; ".join(a["warnings"])))
    print("-" * 70)
    for k, v in sorted(inv["classes"].items()):
        mark = "" if len(v) >= 3 else "   <- バリアント不足"
        print("  %-42s %d個%s" % (k, len(v), mark))
    print("-" * 70)
    print("出力: %s , %s" % (args.out, args.csv))
    return 1 if n_ng else 0


if __name__ == "__main__":
    sys.exit(main())
