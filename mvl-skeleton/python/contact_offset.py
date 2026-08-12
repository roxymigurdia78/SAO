# contact_offset.py — GLBの「実質的な接地面」を推定して assets/contact_offsets.json を作る
#
# v2: 面積重み付きサンプリング、複数支持面候補、軸警告、信頼度、内容ハッシュキャッシュ、可視レポート。
#      既存の contact_offset/support_offset の意味は維持しつつ、未知アセットでも壊れない方針で退避する。
import argparse
import base64
import hashlib
import json
import struct
from datetime import datetime
from pathlib import Path

import numpy as np

TABLE_NAME = "contact_offsets.json"
SCHEMA_VERSION = 2
METHOD_NAME = "surface_sampling+spread_profile"
METHOD_PARAMS = {"n_slabs": 64, "tau_body": 0.10, "tau_support": 0.35, "periphery": 0.20}
MAX_SAMPLES = 200000
REPORT_POINTS = 5000

# --- 推定パラメータ ---
N_SLABS = METHOD_PARAMS["n_slabs"]
# contact_offset.py — GLBの「実質的な接地面」を推定して assets/contact_offsets.json を作る
#
# v2: 面積重み付きサンプリング、複数支持面候補、軸警告、信頼度、内容ハッシュキャッシュ、可視レポート。
#      既存の contact_offset/support_offset の意味は維持しつつ、未知アセットでも壊れない方針で退避する。
import argparse
import base64
import hashlib
import json
import struct
from datetime import datetime
from pathlib import Path

import numpy as np

TABLE_NAME = "contact_offsets.json"
SCHEMA_VERSION = 2
METHOD_NAME = "surface_sampling+spread_profile"
METHOD_PARAMS = {"n_slabs": 64, "tau_body": 0.10, "tau_support": 0.35, "periphery": 0.20}
MAX_SAMPLES = 200000
REPORT_POINTS = 5000

# --- 推定パラメータ ---
N_SLABS = METHOD_PARAMS["n_slabs"]
TAU_BODY = METHOD_PARAMS["tau_body"]
TAU_SUPPORT = METHOD_PARAMS["tau_support"]
MIN_RUN = 2
PERIPHERY = METHOD_PARAMS["periphery"]
MAX_CONTACT = 0.25
MAX_SUPPORT = 0.70
EPS_CONTACT = 0.005
EPS_SUPPORT = 0.02

_COMPONENT = {5120: "i1", 5121: "u1", 5122: "i2", 5123: "u2", 5125: "u4", 5126: "f4"}
_NCOMP = {"SCALAR": 1, "VEC2": 2, "VEC3": 3, "VEC4": 4, "MAT4": 16}


def _read_glb(path):
    data = Path(path).read_bytes()
    magic, version, length = struct.unpack_from("<III", data, 0)
    if magic != 0x46546C67:
        raise ValueError(f"{path}: GLBではない(magic不一致)")
    if version != 2:
        raise ValueError(f"{path}: glTF {version} は未対応")
    off = 12
    gltf, binary = None, None
    while off < length:
        clen, ctype = struct.unpack_from("<II", data, off)
        chunk = data[off + 8: off + 8 + clen]
        if ctype == 0x4E4F534A:
            gltf = json.loads(chunk)
        elif ctype == 0x004E4942:
            binary = chunk
        off += 8 + clen + (-clen % 4)
    if gltf is None:
        raise ValueError(f"{path}: JSONチャンクが無い")
    return gltf, [binary] if binary is not None else []


def _resolve_uri(uri, base_path):
    if uri.startswith("data:"):
        header, data = uri.split(",", 1)
        if header.endswith(";base64"):
            return base64.b64decode(data)
        raise ValueError("data URI の形式が未対応")
    return Path(base_path).parent.joinpath(uri).read_bytes()


def _load_gltf(path):
    p = Path(path)
    gltf = json.loads(p.read_text(encoding="utf-8"))
    buffers = []
    for buf in gltf.get("buffers", []):
        uri = buf.get("uri")
        if uri is None:
            raise ValueError(f"{path}: uriのないbufferは未対応")
        buffers.append(_resolve_uri(uri, p))
    return gltf, buffers


def _read_accessor(gltf, buffers, index):
    acc = gltf["accessors"][index]
    if "sparse" in acc:
        base = _read_accessor(gltf, buffers, index)
        sparse = acc["sparse"]
        idx_acc = sparse["indices"]
        val_acc = sparse["values"]
        idx = _read_accessor(gltf, buffers, idx_acc["bufferView"]) if isinstance(idx_acc, dict) else _read_accessor(gltf, buffers, idx_acc)
        idx = idx.astype(np.int64).ravel()
        vals = _read_accessor(gltf, buffers, val_acc["bufferView"]) if isinstance(val_acc, dict) else _read_accessor(gltf, buffers, val_acc)
        base[idx] = vals
        return base
    dtype = np.dtype(_COMPONENT[acc["componentType"]]).newbyteorder("<")
    ncomp = _NCOMP[acc["type"]]
    count = acc["count"]
    if "bufferView" not in acc:
        return np.zeros((count, ncomp), dtype=np.float64)
    bv = gltf["bufferViews"][acc["bufferView"]]
    buffer_data = buffers[bv["buffer"]]
    base = bv.get("byteOffset", 0) + acc.get("byteOffset", 0)
    stride = bv.get("byteStride") or dtype.itemsize * ncomp
    if stride == dtype.itemsize * ncomp:
        arr = np.frombuffer(buffer_data, dtype=dtype, count=count * ncomp, offset=base)
        return arr.reshape(count, ncomp).astype(np.float64)
    raw = np.frombuffer(buffer_data, dtype=np.uint8, count=stride * count, offset=base)
    raw = raw.reshape(count, stride)[:, : dtype.itemsize * ncomp]
    out = np.ascontiguousarray(raw).view(dtype).reshape(count, ncomp)
    return out.astype(np.float64)


def _node_matrix(node):
    if "matrix" in node:
        return np.array(node["matrix"], dtype=np.float64).reshape(4, 4).T
    m = np.eye(4, dtype=np.float64)
    if "scale" in node:
        m = np.diag(list(node["scale"]) + [1.0]) @ m
    if "rotation" in node:
        x, y, z, w = node["rotation"]
        r = np.array([
            [1 - 2 * (y * y + z * z), 2 * (x * y - z * w), 2 * (x * z + y * w), 0],
            [2 * (x * y + z * w), 1 - 2 * (x * x + z * z), 2 * (y * z - x * w), 0],
            [2 * (x * z - y * w), 2 * (y * z + x * w), 1 - 2 * (x * x + y * y), 0],
            [0, 0, 0, 1]], dtype=np.float64)
        m = r @ m
    if "translation" in node:
        t = np.eye(4, dtype=np.float64)
        t[:3, 3] = node["translation"]
        m = t @ m
    return m


def _has_trimesh():
    try:
        import trimesh  # noqa: F401
        return True
    except Exception:
        return False


def _load_with_trimesh(path):
    try:
        import trimesh
        mesh = trimesh.load(str(path), force="mesh", skip_materials=True)
        if mesh is None:
            raise ValueError("trimesh で読み込めませんでした")
        if hasattr(mesh, "geometry") and mesh.geometry:
            mesh = trimesh.util.concatenate(tuple(mesh.geometry.values()))
        if not hasattr(mesh, "vertices") or not hasattr(mesh, "faces"):
            raise ValueError("trimesh から頂点/面が得られませんでした")
        verts = np.asarray(mesh.vertices, dtype=np.float64)
        faces = np.asarray(mesh.faces, dtype=np.int64)
        return verts, faces
    except Exception as exc:
        raise RuntimeError(f"trimesh で読み込み失敗: {exc}")


def _is_compressed_gltf(gltf):
    if "extensionsUsed" in gltf:
        if any(ext in gltf["extensionsUsed"] for ext in ("KHR_draco_mesh_compression", "EXT_meshopt_compression")):
            return True
    for mesh in gltf.get("meshes", []):
        for prim in mesh.get("primitives", []):
            if "extensions" in prim and any(ext in prim["extensions"] for ext in ("KHR_draco_mesh_compression", "EXT_meshopt_compression")):
                return True
    return False


def load_mesh(path):
    path = Path(path)
    if path.suffix.lower() not in (".glb", ".gltf"):
        raise ValueError(f"{path}: 未対応のファイル形式")
    if path.suffix.lower() == ".glb":
        gltf, buffers = _read_glb(path)
    else:
        gltf, buffers = _load_gltf(path)
    if _is_compressed_gltf(gltf):
        if _has_trimesh():
            return _load_with_trimesh(path)
        raise NotImplementedError("KHR_draco_mesh_compression/EXT_meshopt_compression などの圧縮が未サポート")
    vertices = []
    faces = []
    nodes = gltf.get("nodes", [])
    scene_nodes = gltf.get("scenes", [{}])[gltf.get("scene", 0)].get("nodes", list(range(len(nodes))))
    def walk(idx, parent):
        node = nodes[idx]
        world = parent @ _node_matrix(node)
        if "mesh" in node:
            for prim in gltf["meshes"][node["mesh"]].get("primitives", []):
                if prim.get("mode", 4) != 4:
                    continue
                pos_idx = prim.get("attributes", {}).get("POSITION")
                if pos_idx is None:
                    continue
                v = _read_accessor(gltf, buffers, pos_idx)
                if v.size == 0:
                    continue
                v = v @ world[:3, :3].T + world[:3, 3]
                index = prim.get("indices")
                if index is None:
                    tri = np.arange(len(v), dtype=np.int64)
                else:
                    tri = _read_accessor(gltf, buffers, index).astype(np.int64).ravel()
                if tri.size % 3 != 0:
                    tri = tri[:-(tri.size % 3)]
                if tri.size == 0:
                    continue
                offset = len(vertices)
                faces.append(tri.reshape(-1, 3) + offset)
                vertices.append(v)
        for c in node.get("children", []):
            walk(c, world)
    for r in scene_nodes:
        walk(r, np.eye(4, dtype=np.float64))
    if not vertices or not faces:
        raise ValueError(f"{path}: 頂点/面が取得できませんでした")
    return np.vstack(vertices), np.vstack(faces)


def sample_surface_points(vertices, faces, max_samples=MAX_SAMPLES, rng=None):
    if rng is None:
        rng = np.random.default_rng(0)
    vertices = np.asarray(vertices, dtype=np.float64)
    faces = np.asarray(faces, dtype=np.int64)
    tris = vertices[faces]
    vec = np.cross(tris[:, 1] - tris[:, 0], tris[:, 2] - tris[:, 0])
    areas = np.linalg.norm(vec, axis=1) * 0.5
    mask = areas > 1e-12
    if not mask.any():
        raise ValueError("有効な三角形がありません")
    tris = tris[mask]
    areas = areas[mask]
    total_area = float(areas.sum())
    n_samples = min(max_samples, max(int(len(tris) * 10), 1000))
    probs = areas / total_area
    choice = rng.choice(len(tris), size=n_samples, p=probs)
    selected = tris[choice]
    u = rng.random(n_samples)
    v = rng.random(n_samples)
    over = u + v > 1.0
    u[over] = 1.0 - u[over]
    v[over] = 1.0 - v[over]
    w = 1.0 - u - v
    return (selected[:, 0] * u[:, None] + selected[:, 1] * v[:, None] + selected[:, 2] * w[:, None]).astype(np.float64)


def sample_surface_points_with_normals(vertices, faces, max_samples=MAX_SAMPLES, rng=None):
    """Sample points on surface and return per-sample triangle normals.
    Returns (points, normals) where normals are unit vectors per sampled triangle.
    """
    if rng is None:
        rng = np.random.default_rng(0)
    vertices = np.asarray(vertices, dtype=np.float64)
    faces = np.asarray(faces, dtype=np.int64)
    tris = vertices[faces]
    vec = np.cross(tris[:, 1] - tris[:, 0], tris[:, 2] - tris[:, 0])
    areas = np.linalg.norm(vec, axis=1) * 0.5
    mask = areas > 1e-12
    if not mask.any():
        raise ValueError("有効な三角形がありません")
    tris_masked = tris[mask]
    areas = areas[mask]
    total_area = float(areas.sum())
    n_samples = min(max_samples, max(int(len(tris_masked) * 10), 1000))
    probs = areas / total_area
    choice = rng.choice(len(tris_masked), size=n_samples, p=probs)
    selected = tris_masked[choice]
    u = rng.random(n_samples)
    v = rng.random(n_samples)
    over = u + v > 1.0
    u[over] = 1.0 - u[over]
    v[over] = 1.0 - v[over]
    w = 1.0 - u - v
    pts = (selected[:, 0] * u[:, None] + selected[:, 1] * v[:, None] + selected[:, 2] * w[:, None]).astype(np.float64)
    tri_vec = np.cross(selected[:, 1] - selected[:, 0], selected[:, 2] - selected[:, 0])
    tri_norm = np.zeros_like(tri_vec)
    norms = np.linalg.norm(tri_vec, axis=1)
    safe = norms > 1e-12
    tri_norm[safe] = (tri_vec[safe].T / norms[safe]).T
    return pts, tri_norm


def _validate_points(verts):
    verts = np.asarray(verts, dtype=np.float64)
    if verts.size == 0 or verts.shape[1] != 3:
        return False
    if not np.isfinite(verts).all():
        return False
    if np.ptp(verts[:, 0]) < 1e-9 and np.ptp(verts[:, 1]) < 1e-9 and np.ptp(verts[:, 2]) < 1e-9:
        return False
    return True


def spread_profile(verts, n_slabs=N_SLABS):
    y = verts[:, 1]
    y_min, y_max = float(y.min()), float(y.max())
    h = y_max - y_min
    prof = np.zeros(n_slabs, dtype=np.float64)
    if h <= 1e-9:
        return prof, y_min, y_max
    fx = float(verts[:, 0].max() - verts[:, 0].min())
    fz = float(verts[:, 2].max() - verts[:, 2].min())
    total = max(fx * fz, 1e-12)
    idx = np.clip(((y - y_min) / h * (n_slabs - 1)).astype(np.int64), 0, n_slabs - 1)
    order = np.argsort(idx, kind="stable")
    idx_s, v_s = idx[order], verts[order]
    bounds = np.searchsorted(idx_s, np.arange(n_slabs + 1))
    for i in range(n_slabs):
        a, b = bounds[i], bounds[i + 1]
        if b - a < 3:
            continue
        seg = v_s[a:b]
        prof[i] = ((seg[:, 0].max() - seg[:, 0].min()) *
                   (seg[:, 2].max() - seg[:, 2].min())) / total
    return prof, y_min, y_max


def _first_stable(mask, run_len):
    run = 0
    for i, m in enumerate(mask):
        run = run + 1 if m else 0
        if run >= run_len:
            return i - run_len + 1
    return None


def _peripheral_min_frac(verts, y_min, h, periphery=PERIPHERY):
    x, z = verts[:, 0], verts[:, 2]
    cx, cz = (x.max() + x.min()) / 2, (z.max() + z.min()) / 2
    hx, hz = max((x.max() - x.min()) / 2, 1e-9), max((z.max() - z.min()) / 2, 1e-9)
    r = np.maximum(np.abs(x - cx) / hx, np.abs(z - cz) / hz)
    m = r >= periphery
    if not m.any():
        return 0.0
    return float((verts[m, 1].min() - y_min) / h)


def _axis_profile(verts, axis, n_slabs=N_SLABS):
    if axis == "y":
        prof, _, _ = spread_profile(verts, n_slabs)
    elif axis == "x":
        perm = verts[:, [1, 0, 2]]
        prof, _, _ = spread_profile(perm, n_slabs)
    else:
        perm = verts[:, [0, 2, 1]]
        prof, _, _ = spread_profile(perm, n_slabs)
    return float(prof.max())


def support_plane_candidates(verts, y_min, y_max, n_slabs=N_SLABS, normals=None):
    prof, _, _ = spread_profile(verts, n_slabs)
    h = y_max - y_min
    if h <= 1e-9:
        return []
    max_up = 1
    up_counts = None
    if normals is not None:
        y = verts[:, 1]
        idx = np.clip(((y - y_min) / h * (n_slabs - 1)).astype(np.int64), 0, n_slabs - 1)
        order = np.argsort(idx, kind="stable")
        idx_s, n_s = idx[order], normals[order]
        bounds = np.searchsorted(idx_s, np.arange(n_slabs + 1))
        up_counts = []
        for j in range(n_slabs):
            a, b = bounds[j], bounds[j + 1]
            if b - a < 3:
                up_counts.append(0)
            else:
                up_counts.append((n_s[a:b, 1] > 0.9).sum())
        max_up = max(1, max(up_counts))
    planes = []
    up_frac = None
    if normals is not None:
        up_frac = np.array([float(v) / float(max_up) for v in up_counts], dtype=np.float64)
    for i in range(n_slabs):
        if up_frac is not None:
            area_frac = float(up_frac[i])
            if area_frac < 0.10 and prof[i] < TAU_SUPPORT * 0.5:
                continue
        else:
            area_frac = float(prof[i])
            if area_frac < TAU_SUPPORT:
                continue
        if up_frac is not None:
            above = up_frac[i + 1] if i + 1 < n_slabs else 0.0
        else:
            above = prof[i + 1] if i + 1 < n_slabs else 0.0
        if above >= TAU_BODY:
            continue
        y_frac = float(i + 1) / n_slabs
        if up_frac is not None:
            obstruct = next((k for k in range(i + 1, n_slabs) if up_frac[k] >= TAU_BODY), n_slabs)
        else:
            obstruct = next((k for k in range(i + 1, n_slabs) if prof[k] >= TAU_BODY), n_slabs)
        # If nothing obstructs above this slab, treat clearance as large
        if obstruct >= n_slabs:
            # If this is the absolute topmost slab, keep clearance small to preserve hanging detection.
            if i >= n_slabs - 1:
                clearance_frac = 0.0
            else:
                clearance_frac = 1.0
        else:
            clearance_frac = float(max(0.0, (obstruct - i) / n_slabs))
        confidence = 0.9 if clearance_frac >= 0.15 and area_frac >= TAU_SUPPORT else 0.6
        planes.append({
            "y_frac": round(y_frac, 4),
            "area_frac": round(area_frac, 4),
            "clearance_frac": round(min(clearance_frac, 1.0), 4),
            "confidence": round(confidence, 2),
        })
    return sorted(planes, key=lambda x: x["y_frac"], reverse=True)


def classify_ground_type(verts, contact_offset, planes, axis_warning):
    prof, y_min, y_max = spread_profile(verts, N_SLABS)
    h = y_max - y_min
    if h <= 1e-9:
        return "unknown"
    bottom_area = float(prof[0])
    top_area = float(prof[-1])
    x_span = float(verts[:, 0].max() - verts[:, 0].min())
    z_span = float(verts[:, 2].max() - verts[:, 2].min())
    footprint = x_span * z_span
    height_frac = float((verts[:, 1].mean() - y_min) / h)
    if contact_offset == 0.0 and (len(planes) == 0 or planes[0]["clearance_frac"] < 0.05) and top_area > 0.15 and height_frac > 0.6:
        return "hanging"
    if contact_offset == 0.0 and bottom_area >= TAU_BODY * 0.8:
        return "tabletop" if h < 0.75 or footprint < 0.25 else "floor"
    if h < 0.85 or footprint < 0.15:
        return "tabletop"
    return "unknown"


def _confidence_from_diag(diag):
    if diag.get("needs_review"):
        if diag.get("ground_type") in ("hanging", "unknown"):
            return 0.0
        return 0.65
    conf = 1.0
    if diag.get("axis_warning"):
        conf -= 0.2
    if diag.get("support_planes") and diag["support_planes"][0].get("clearance_frac", 0) < 0.1:
        conf -= 0.1
    return round(max(0.0, min(conf, 1.0)), 2)


def estimate_offsets(verts, n_slabs=N_SLABS, normals=None):
    verts = np.asarray(verts, dtype=np.float64)
    if not _validate_points(verts):
        return 0.0, 0.0, {
            "aabb_height": 0.0,
            "n_slabs": n_slabs,
            "needs_review": True,
            "support_planes": [],
            "axis_warning": False,
            "ground_type": "unknown",
            "confidence": 0.0,
            "note": "頂点データが無効です",
        }
    prof, y_min, y_max = spread_profile(verts, n_slabs)
    h = y_max - y_min
    diag = {"aabb_height": round(float(h), 4), "n_slabs": n_slabs}
    if h <= 1e-9 or prof.max() <= 0:
        return 0.0, 0.0, {
            **diag,
            "note": "高さゼロ or 有効断面なし",
            "needs_review": True,
            "support_planes": [],
            "axis_warning": False,
            "ground_type": "unknown",
            "confidence": 0.0,
        }
    contact = 0.0
    review_c = False
    i0 = _first_stable(prof >= TAU_BODY, MIN_RUN)
    diag["body_bottom_slab"] = i0
    if i0 is not None and i0 > 0:
        contact = float(i0) / n_slabs
        if contact > MAX_CONTACT:
            review_c = True
            diag["rejected_contact"] = round(contact, 4)
    diag["peripheral_min_frac"] = round(_peripheral_min_frac(verts, y_min, h), 4)
    diag["body_contact_frac"] = round(contact, 4)
    planes = support_plane_candidates(verts, y_min, y_max, n_slabs, normals=normals)
    # Fallback: if no planes found, try a weaker threshold to catch thin supports (crystal/lantern/plant)
    if not planes:
        prof, _, _ = spread_profile(verts, n_slabs)
        weak_thresh = TAU_SUPPORT * 0.5
        cand = None
        for i in range(n_slabs - 1, -1, -1):
            if prof[i] >= weak_thresh:
                above = prof[i + 1] if i + 1 < n_slabs else 0.0
                if above < TAU_BODY:
                    cand = i
                    break
        if cand is not None:
            y_frac = float(cand + 0.5) / n_slabs
            area_frac = float(prof[cand])
            obstruct = next((k for k in range(cand + 1, n_slabs) if prof[k] >= TAU_BODY), n_slabs)
            if obstruct >= n_slabs:
                clearance_frac = 0.0 if cand >= n_slabs - 1 else 1.0
            else:
                clearance_frac = float(max(0.0, (obstruct - cand) / n_slabs))
            planes = [{
                "y_frac": round(y_frac, 4),
                "area_frac": round(area_frac, 4),
                "clearance_frac": round(min(clearance_frac, 1.0), 4),
                "confidence": 0.5,
            }]
    # Additional fallback: pick highest local peak where above slab drops sufficiently
    if not planes:
        prof, _, _ = spread_profile(verts, n_slabs)
        weak_thresh = TAU_SUPPORT * 0.5
        cand2 = None
        for i in range(n_slabs - 1, -1, -1):
            if prof[i] >= weak_thresh:
                above = prof[i + 1] if i + 1 < n_slabs else 0.0
                if above < prof[i] * 0.8:
                    cand2 = i
                    break
        if cand2 is not None:
            y_frac = float(cand2 + 0.5) / n_slabs
            area_frac = float(prof[cand2])
            obstruct = next((k for k in range(cand2 + 1, n_slabs) if prof[k] >= TAU_BODY), n_slabs)
            if obstruct >= n_slabs:
                clearance_frac = 0.0 if cand2 >= n_slabs - 1 else 1.0
            else:
                clearance_frac = float(max(0.0, (obstruct - cand2) / n_slabs))
            planes = [{
                "y_frac": round(y_frac, 4),
                "area_frac": round(area_frac, 4),
                "clearance_frac": round(min(clearance_frac, 1.0), 4),
                "confidence": 0.4,
            }]
    support = 0.0
    review_s = False
    if planes:
        valid_top = [p for p in planes if p["clearance_frac"] >= 0.05 and p["y_frac"] < 0.95]
        if valid_top:
            support = round(float(1.0 - valid_top[0]["y_frac"]), 4)
            diag["support_offset_source"] = "highest_shelf_with_clearance"
        else:
            # If we have only weak candidates (from fallback), accept a top plane
            # when its confidence and area meet relaxed criteria.
            top = planes[0]
            if top.get("confidence", 0.0) >= 0.4 and top.get("area_frac", 0.0) >= TAU_SUPPORT * 0.5:
                support = round(float(1.0 - top["y_frac"]), 4)
                diag["support_offset_source"] = "weak_candidate_accepted"
            else:
                review_s = True
                diag["support_offset_source"] = "no_clearance"
    else:
        review_s = True
        diag["note"] = "TAU_SUPPORTを超える断面が無い"
    contact = 0.0 if contact < EPS_CONTACT else round(float(contact), 4)
    support = 0.0 if support < EPS_SUPPORT else round(float(support), 4)
    axis_scores = {
        "x": _axis_profile(verts, "x", n_slabs),
        "y": _axis_profile(verts, "y", n_slabs),
        "z": _axis_profile(verts, "z", n_slabs),
    }
    axis_warning = axis_scores["y"] + 1e-9 < max(axis_scores["x"], axis_scores["z"])
    diag["axis_scores"] = {k: round(float(v), 4) for k, v in axis_scores.items()}
    diag["axis_warning"] = bool(axis_warning)
    ground_type = classify_ground_type(verts, contact, planes, axis_warning)
    diag["ground_type"] = ground_type
    diag["support_planes"] = planes
    diag["needs_review"] = bool(review_c or review_s or axis_warning or ground_type in ("hanging", "unknown"))
    if ground_type in ("hanging", "unknown"):
        contact = 0.0
    diag["confidence"] = _confidence_from_diag({**diag, "contact_offset": contact, "support_planes": planes, "ground_type": ground_type})
    diag["contact_offset"] = contact
    diag["support_offset"] = support
    return contact, support, diag


def _load_table(assets_dir):
    p = Path(assets_dir) / TABLE_NAME
    if not p.exists():
        return {}
    try:
        return json.loads(p.read_text(encoding="utf-8"))
    except Exception:
        return {}


def load_overrides(assets_dir):
    p = Path(assets_dir) / "contact_overrides.json"
    if not p.exists():
        return {}
    try:
        return json.loads(p.read_text(encoding="utf-8"))
    except Exception:
        return {}


def lookup_entry(assets_dir, asset_name):
    table = _load_table(assets_dir)
    return table.get(asset_name) if isinstance(table, dict) else None


def lookup_override(assets_dir, asset_name):
    overrides = load_overrides(assets_dir)
    return overrides.get(asset_name) if isinstance(overrides, dict) else None


def lookup(assets_dir, asset_name, obj=None, key="contact_offset"):
    if obj is not None and obj.get(key) is not None:
        return float(obj[key])
    override = lookup_override(assets_dir, asset_name)
    if isinstance(override, dict) and override.get(key) is not None:
        return float(override[key])
    if asset_name is None:
        return 0.0
    entry = lookup_entry(assets_dir, asset_name)
    if isinstance(entry, dict) and entry.get(key) is not None:
        return float(entry[key])
    if isinstance(entry, (int, float)) and key == "contact_offset":
        return float(entry)
    return 0.0


def needs_review(assets_dir, asset_name, obj=None):
    if obj is not None and obj.get("needs_review"):
        return True
    override = lookup_override(assets_dir, asset_name)
    if isinstance(override, dict) and override.get("needs_review"):
        return bool(override.get("needs_review"))
    entry = lookup_entry(assets_dir, asset_name)
    return bool(isinstance(entry, dict) and entry.get("needs_review"))


def _asset_is_fresh(entry, sha, method):
    return (isinstance(entry, dict) and
            entry.get("sha256") == sha and
            entry.get("schema_version") == SCHEMA_VERSION and
            entry.get("method") == method)


def _sanitize_entry(entry):
    if not isinstance(entry, dict):
        return entry
    return {k: entry[k] for k in entry if k != "_meta"}


def generate_report(items, out_path):
    try:
        import matplotlib.pyplot as plt
    except Exception as exc:
        print(f"report を生成できません: matplotlib が必要です ({exc})")
        return
    n = len(items)
    if n == 0:
        print("report: 描画対象なし")
        return
    cols = min(4, n)
    rows = (n + cols - 1) // cols
    fig, axes = plt.subplots(rows, cols, figsize=(cols * 4, rows * 3), squeeze=False)
    for idx, (name, entry, points) in enumerate(items):
        ax = axes[idx // cols][idx % cols]
        if points.size:
            ax.scatter(points[:, 0], points[:, 1], s=1, alpha=0.2, c="black")
        if entry.get("contact_offset") is not None and points.size:
            ymin, ymax = float(points[:, 1].min()), float(points[:, 1].max())
            h = ymax - ymin if ymax > ymin else 1.0
            contact_y = ymin + entry["contact_offset"] * h
            ax.axhline(contact_y, color="blue", linestyle="-", linewidth=1.2, label="contact")
            for plane in entry.get("support_planes", []):
                line_y = ymin + plane["y_frac"] * h
                ax.axhline(line_y, color="green", linestyle="--", linewidth=1.0)
        title = f"{name} [{entry.get('ground_type','?')}] c={entry.get('confidence',0.0):.2f}"
        if entry.get("needs_review"):
            title += " REVIEW"
            for spine in ax.spines.values():
                spine.set_edgecolor("red")
                spine.set_linewidth(2.0)
        ax.set_title(title, fontsize=8)
        ax.set_xlabel("X")
        ax.set_ylabel("Y")
        if points.size:
            ax.set_xlim(points[:, 0].min() - 0.05, points[:, 0].max() + 0.05)
            ax.set_ylim(points[:, 1].min() - 0.02, points[:, 1].max() + 0.02)
    for j in range(idx + 1, rows * cols):
        fig.delaxes(axes[j // cols][j % cols])
    plt.tight_layout()
    Path(out_path).parent.mkdir(parents=True, exist_ok=True)
    fig.savefig(out_path, dpi=200)
    plt.close(fig)
    print(f"[contact_offset] report: {out_path}")


def measure_dir(assets_dir, force=False, only=None, verbose=False, report_path=None):
    assets_dir = Path(assets_dir)
    out_path = assets_dir / TABLE_NAME
    table = _load_table(assets_dir)
    meta = table.get("_meta", {}) if isinstance(table, dict) else {}
    if meta.get("schema_version") != SCHEMA_VERSION or meta.get("method") != METHOD_NAME:
        force = True
    targets = sorted(assets_dir.glob("*.glb")) + sorted(assets_dir.glob("*.gltf"))
    if only:
        targets = [p for p in targets if p.name == only]
    result = {k: v for k, v in table.items() if k != "_meta"}
    report_items = []
    for p in targets:
        sha = hashlib.sha256(p.read_bytes()).hexdigest()[:16]
        old = result.get(p.name, {})
        if not force and _asset_is_fresh(old, sha, METHOD_NAME):
            if verbose:
                print(f"  skip {p.name}(計測済み)")
            if report_path and isinstance(old, dict):
                try:
                    verts, faces = load_mesh(p)
                    points = sample_surface_points(verts, faces, max_samples=REPORT_POINTS)
                    report_items.append((p.name, _sanitize_entry(old), points))
                except Exception:
                    pass
            continue
        try:
            verts, faces = load_mesh(p)
            if not _validate_points(verts):
                raise ValueError("頂点データが無効です")
            # For shelf assets, sample normals and use upward-normal-based area measurement
            if p.name.lower().startswith('shelf'):
                points, normals = sample_surface_points_with_normals(verts, faces)
                contact, support, diag = estimate_offsets(points, normals=normals)
            else:
                points = sample_surface_points(verts, faces)
                contact, support, diag = estimate_offsets(points)
            entry = {
                "sha256": sha,
                "schema_version": SCHEMA_VERSION,
                "contact_offset": float(contact),
                "support_offset": float(support),
                "support_planes": diag.get("support_planes", []),
                "ground_type": diag.get("ground_type", "unknown"),
                "confidence": diag.get("confidence", 0.0),
                "needs_review": bool(diag.get("needs_review")),
                "axis_warning": bool(diag.get("axis_warning")),
                "aabb_height": round(float(diag.get("aabb_height", 0.0)), 4),
                "samples": int(min(len(points), MAX_SAMPLES)),
                "measured_at": datetime.now().strftime("%Y-%m-%d"),
                "method": METHOD_NAME,
            }
            if diag.get("note"):
                entry["note"] = diag["note"]
            if verbose:
                print(f"  {p.name}: contact={contact:.3f} support={support:.3f} "
                      f"(height={entry['aabb_height']:.3f}, samples={entry['samples']})" +
                      (" ← 要確認" if entry["needs_review"] else ""))
            result[p.name] = entry
            if report_path:
                points_viz = points[np.random.default_rng(0).choice(len(points), min(REPORT_POINTS, len(points)), replace=False)]
                report_items.append((p.name, entry, points_viz))
        except NotImplementedError as exc:
            print(f"  ! {p.name}: unsupported {exc}")
            result[p.name] = {
                "sha256": sha,
                "schema_version": SCHEMA_VERSION,
                "contact_offset": 0.0,
                "support_offset": 0.0,
                "support_planes": [],
                "ground_type": "unknown",
                "confidence": 0.0,
                "needs_review": True,
                "method": "unsupported",
                "note": str(exc),
                "measured_at": datetime.now().strftime("%Y-%m-%d"),
            }
        except Exception as exc:
            print(f"  ! {p.name}: 計測失敗 {exc}")
            result[p.name] = {
                "sha256": sha,
                "schema_version": SCHEMA_VERSION,
                "contact_offset": 0.0,
                "support_offset": 0.0,
                "support_planes": [],
                "ground_type": "unknown",
                "confidence": 0.0,
                "needs_review": True,
                "method": "failed",
                "note": str(exc),
                "measured_at": datetime.now().strftime("%Y-%m-%d"),
            }
    out = {"_meta": {
        "schema_version": SCHEMA_VERSION,
        "method": METHOD_NAME,
        "params": METHOD_PARAMS,
        "updated_at": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
    }}
    out.update(result)
    out_path.write_text(json.dumps(out, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"[contact_offset] 出力: {out_path}")
    if report_path:
        generate_report(report_items, report_path)
    return out


if __name__ == "__main__":
    ap = argparse.ArgumentParser(description="GLBの接地オフセットを実測してテーブル化")
    ap.add_argument("assets_dir")
    ap.add_argument("--force", action="store_true", help="計測済みも計測し直す")
    ap.add_argument("--asset", help="特定のGLBだけ計測")
    ap.add_argument("--verbose", action="store_true")
    ap.add_argument("--report", help="結果を可視化したPNGを出力")
    a = ap.parse_args()
    measure_dir(a.assets_dir, force=a.force, only=a.asset, verbose=a.verbose, report_path=a.report)

