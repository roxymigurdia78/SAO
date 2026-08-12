import contact_offset as co
from pathlib import Path

names = [
    "shelf_v1.glb",
    "shelf_v2.glb",
    "shelf_v3.glb",
    "table_v1.glb",
    "table_v2.glb",
    "crystal_v1.glb",
    "lantern_v1.glb",
    "plant_v1.glb",
    "plant_v2.glb",
]
base = Path('..') / 'scene' / 'assets'
for name in names:
    p = base / name
    verts, faces = co.load_mesh(p)
    pts = co.sample_surface_points(verts, faces, max_samples=200000)
    prof, ymin, ymax = co.spread_profile(pts)
    cand = [(i, float(prof[i]), float(prof[i+1]) if i+1 < len(prof) else 0.0)
            for i in range(len(prof)) if prof[i] >= co.TAU_SUPPORT]
    print('---', name)
    print('ymin', ymin, 'ymax', ymax, 'h', ymax-ymin)
    print('max', prof.max())
    print('support slabs', len(cand), cand[:20])
    print('top slabs', [(i, float(prof[i])) for i in range(len(prof)-10, len(prof))])
    print('support planes', co.support_plane_candidates(pts, ymin, ymax, n_slabs=64))
    print()
