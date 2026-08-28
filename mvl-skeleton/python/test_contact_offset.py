# test_contact_offset.py — 接地オフセット推定と、それを使う配置計算の回帰テスト
# GLB不要(合成点群で検証)。実行: python test_contact_offset.py
import numpy as np

import contact_offset as co
import machine_checks as mc
import repair


def box_surface(x0, x1, y0, y1, z0, z1, n=4000):
    rng = np.random.default_rng(0)
    return np.column_stack([rng.uniform(x0, x1, n), rng.uniform(y0, y1, n), rng.uniform(z0, z1, n)])


def ring_surface(cx, cz, y, r, n=2000):
    rng = np.random.default_rng(1)
    th = rng.uniform(0, 2 * np.pi, n)
    return np.column_stack([cx + np.cos(th) * r, np.full(n, y), cz + np.sin(th) * r])


def old_vertex_count_contact(verts, n_slabs=64):
    y = verts[:, 1]
    y_min, y_max = float(y.min()), float(y.max())
    h = y_max - y_min
    if h <= 1e-9:
        return 0.0
    idx = np.clip(((y - y_min) / h * (n_slabs - 1)).astype(np.int64), 0, n_slabs - 1)
    counts = np.bincount(idx, minlength=n_slabs).astype(np.float64)
    prof = counts / np.maximum(1.0, counts.max())
    run = 0
    for i, p in enumerate(prof):
        run = run + 1 if p >= 0.10 else 0
        if run >= 2:
            return float(i - run + 1) / n_slabs
    return 0.0


def check(name, cond):
    print(("  OK   " if cond else "  FAIL ") + name)
    return cond


def main():
    ok = True

    # 1) 脚付きテーブル: AABB底面 = 接地面。オフセットは出ない
    legs = [box_surface(x, x + 0.05, 0.0, 0.7, z, z + 0.05)
            for x in (0.0, 0.95) for z in (0.0, 0.45)]
    table = np.vstack(legs + [box_surface(0.0, 1.0, 0.7, 0.75, 0.0, 0.5)])
    c, s, _ = co.estimate_offsets(table)
    ok &= check(f"脚付きテーブル contact={c:.3f} → 0", c == 0.0)
    ok &= check(f"脚付きテーブル support={s:.3f} → 0", s == 0.0)

    # 2) 下向き装飾突起つきランタン: 突起は無視して本体の底を接地面にする
    lantern = np.vstack([
        ring_surface(0.1, 0.1, 0.0, 0.02, n=6000),
        box_surface(0.0, 0.2, 0.05, 0.45, 0.0, 0.2),
        ring_surface(0.1, 0.1, 0.5, 0.02, n=2000),
    ])
    c, s, _ = co.estimate_offsets(lantern)
    ok &= check(f"装飾突起つき contact={c:.3f} → 0.08〜0.12", 0.08 <= c <= 0.12)

    # 3) 低ポリ版: 面積サンプリングで正しく、頂点カウント型は失敗する
    lowpoly = np.vstack([
        box_surface(0.0, 0.4, 0.05, 0.4, 0.0, 0.4),
        ring_surface(0.2, 0.2, 0.0, 0.02, n=12000),
    ])
    c2, _, _ = co.estimate_offsets(lowpoly)
    c1 = old_vertex_count_contact(lowpoly)
    ok &= check("低ポリ装飾付き contact_offset が推定され、頂点型は失敗", 0.08 <= c2 <= 0.12 and c1 == 0.0)

    # 4) 天板より高い背板を持つ机: 天面はAABB上端ではない
    desk = np.vstack([
        box_surface(0.0, 1.0, 0.0, 0.7, 0.0, 0.5),
        box_surface(0.0, 1.0, 0.7, 1.4, 0.0, 0.04),
    ])
    c, s, _ = co.estimate_offsets(desk)
    ok &= check(f"背板つき机 support={s:.3f} → 0.45〜0.55", 0.45 <= s <= 0.55)

    # 5) Z-up 机: Y-up 方向が最適でない場合は axis_warning になる
    z_up_table = desk[:, [2, 1, 0]]
    _, _, diag = co.estimate_offsets(z_up_table)
    ok &= check("Z-up の机 axis_warning=true", diag.get("axis_warning") is True)

    # 6) 吊りランタン: 上端に環だけの形状は hanging と判定され、contact_offset=0
    hanging = np.vstack([
        ring_surface(0.0, 0.0, 1.2, 0.1, n=6000),
        ring_surface(0.0, 0.0, 1.0, 0.05, n=1000),
    ])
    c, _, diag = co.estimate_offsets(hanging)
    ok &= check("吊りランタン ground_type=hanging", diag.get("ground_type") == "hanging")
    ok &= check("吊りランタン contact_offset=0", c == 0.0)

    # 7) 棚板3枚: support_planes が 3 つ以上検出される
    shelves = np.vstack([
        box_surface(0.0, 1.0, 0.1, 0.12, 0.0, 0.4),
        box_surface(0.0, 1.0, 0.5, 0.52, 0.0, 0.4),
        box_surface(0.0, 1.0, 0.9, 0.92, 0.0, 0.4),
    ])
    _, _, diag = co.estimate_offsets(shelves)
    ok &= check("棚板3枚 support_planes>=3", len(diag.get("support_planes", [])) >= 3)

    # 8) 壊れたメッシュ: NaN/無効点でも例外を投げず needs_review=True
    broken = np.array([[np.nan, 0.0, 0.0], [0.0, 0.0, 0.0]])
    c, s, diag = co.estimate_offsets(broken)
    ok &= check("壊れたメッシュ needs_review", diag.get("needs_review") is True)
    ok &= check("壊れたメッシュ contact_offset=0", c == 0.0)
    ok &= check("壊れたメッシュ support_offset=0", s == 0.0)

    # 9) 検査と修正の連携: 接地オフセットぶん position を下げて置く
    scene = {
        "assets_dir": "dummy",
        "room": {"floor_y": 0.0, "bounds": {"width": 4, "depth": 4, "height": 2.5},
                 "entrance": {"position": [0.2, 0.2]}},
        "objects": [
            {"id": "table_01", "class": "table", "asset": "t.glb", "position": [1.0, 0.0, 1.0],
             "target_dimensions": {"width": 1.0, "height": 1.0, "depth": 0.5},
             "support_offset": 0.5, "must_touch_floor": True},
            {"id": "lantern_01", "class": "lantern", "asset": "l.glb", "position": [1.0, 1.0, 1.0],
             "target_dimensions": {"width": 0.2, "height": 0.5, "depth": 0.2},
             "contact_offset": 0.1, "rests_on": "table_01", "must_touch_floor": False},
        ],
    }
    aabbs = mc.collect_aabbs(scene)
    vs = mc.check_floating(scene, aabbs)
    ok &= check(f"浮遊を検出({len(vs)}件)", len(vs) == 1 and vs[0]["object_id"] == "lantern_01")
    if vs:
        ok &= check(f"gap={vs[0]['gap']:+.3f} → +0.55", abs(vs[0]["gap"] - 0.55) < 1e-6)
        new, applied = repair.apply_repairs(scene, vs)
        y = next(o for o in new["objects"] if o["id"] == "lantern_01")["position"][1]
        ok &= check(f"修正後 position.y={y:.3f} → 0.450", abs(y - 0.45) < 1e-6)
        aab2 = mc.collect_aabbs(new)
        ok &= check("修正後は違反ゼロ", len(mc.check_floating(new, aab2)) == 0)

    print("\n" + ("すべて通過" if ok else "失敗あり"))
    return 0 if ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
