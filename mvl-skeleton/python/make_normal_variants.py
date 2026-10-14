"""
法線マップ比較用の GLB を3つ作る。

1つの GLB（例: normal_test5/desk_v1.glb）から、法線画像だけが違う3つを作る。
形・UV・色・粗さはすべて同じ。

  <名前>_none.glb     法線マップなし
  <名前>_v2.glb       そのまま（自作 v2）
  <名前>_blender.glb  法線画像だけ Blender で焼いた PNG に差し替え

使い方:
  python make_normal_variants.py --glb desk_v1.glb --normal-png normal_blender.png --out-dir out

標準ライブラリのみ使用（追加インストール不要）。
"""
import argparse
import copy
import json
import shutil
import struct
from pathlib import Path

JSON_CHUNK = 0x4E4F534A
BIN_CHUNK = 0x004E4942


def read_glb(path):
    data = path.read_bytes()
    magic, _, length = struct.unpack_from("<4sII", data, 0)
    if magic != b"glTF":
        raise ValueError(f"{path} は GLB ではありません")
    off, gltf, binary = 12, None, b""
    while off < length:
        clen, ctype = struct.unpack_from("<II", data, off)
        off += 8
        chunk = data[off:off + clen]
        off += clen
        if ctype == JSON_CHUNK:
            gltf = json.loads(chunk)
        elif ctype == BIN_CHUNK:
            binary = bytes(chunk)
    return gltf, binary


def write_glb(path, gltf, binary):
    j = json.dumps(gltf, separators=(",", ":")).encode("utf-8")
    j += b" " * (-len(j) % 4)
    b = binary + b"\0" * (-len(binary) % 4)
    total = 12 + 8 + len(j) + 8 + len(b)
    with open(path, "wb") as f:
        f.write(struct.pack("<4sII", b"glTF", 2, total))
        f.write(struct.pack("<II", len(j), JSON_CHUNK))
        f.write(j)
        f.write(struct.pack("<II", len(b), BIN_CHUNK))
        f.write(b)


def png_size(data):
    if data[:8] != b"\x89PNG\r\n\x1a\n":
        raise ValueError("PNG ではありません")
    return struct.unpack(">II", data[16:24])


def normal_image_view(gltf):
    """法線マップの画像が入っている bufferView の番号を返す。"""
    views = set()
    for mat in gltf.get("materials", []):
        nt = mat.get("normalTexture")
        if nt is None:
            continue
        img = gltf["images"][gltf["textures"][nt["index"]]["source"]]
        views.add(img["bufferView"])
    if len(views) != 1:
        raise RuntimeError(f"法線マップの画像が1枚ではありません（{len(views)}枚）")
    view = views.pop()
    users = [i for i in gltf["images"] if i.get("bufferView") == view]
    if len(users) != 1:
        raise RuntimeError("法線画像が他の画像と共有されています")
    return view


def rebuild_bin(gltf, binary, replace):
    """bufferView を詰め直す。replace = {bufferView番号: 新しい中身}"""
    new = bytearray()
    for i, v in enumerate(gltf["bufferViews"]):
        if v.get("buffer", 0) != 0:
            raise RuntimeError("buffer が複数ある GLB には対応していません")
        start = v.get("byteOffset", 0)
        chunk = replace.get(i, binary[start:start + v["byteLength"]])
        new += b"\0" * (-len(new) % 4)
        v["byteOffset"] = len(new)
        v["byteLength"] = len(chunk)
        new += chunk
    gltf["buffers"][0]["byteLength"] = len(new)
    return bytes(new)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--glb", required=True, type=Path)
    ap.add_argument("--normal-png", required=True, type=Path)
    ap.add_argument("--out-dir", required=True, type=Path)
    args = ap.parse_args()

    args.out_dir.mkdir(parents=True, exist_ok=True)
    stem = args.glb.stem
    gltf, binary = read_glb(args.glb)
    view = normal_image_view(gltf)

    v = gltf["bufferViews"][view]
    old_png = binary[v.get("byteOffset", 0):v.get("byteOffset", 0) + v["byteLength"]]
    new_png = args.normal_png.read_bytes()
    old_size, new_size = png_size(old_png), png_size(new_png)
    print(f"元の法線画像: {old_size[0]}x{old_size[1]}")
    print(f"Blender 画像: {new_size[0]}x{new_size[1]}")
    if old_size != new_size:
        print("※ 解像度が違います（UV が合っていれば動きますが、比較条件がずれます）")

    # 1) なし
    g = copy.deepcopy(gltf)
    for mat in g.get("materials", []):
        mat.pop("normalTexture", None)
    write_glb(args.out_dir / f"{stem}_none.glb", g, binary)

    # 2) 自作 v2（そのまま）
    shutil.copyfile(args.glb, args.out_dir / f"{stem}_v2.glb")

    # 3) Blender
    g = copy.deepcopy(gltf)
    b = rebuild_bin(g, binary, {view: new_png})
    img = next(i for i in g["images"] if i.get("bufferView") == view)
    img["mimeType"] = "image/png"
    write_glb(args.out_dir / f"{stem}_blender.glb", g, b)

    # 確認: 読み直して法線の有無を表示
    for name in ("none", "v2", "blender"):
        p = args.out_dir / f"{stem}_{name}.glb"
        g2, _ = read_glb(p)
        has = any("normalTexture" in m for m in g2.get("materials", []))
        print(f"{p.name}: 法線マップ {'あり' if has else 'なし'}  {p.stat().st_size / 1e6:.1f} MB")


if __name__ == "__main__":
    main()
