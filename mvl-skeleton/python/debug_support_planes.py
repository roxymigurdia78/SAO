import contact_offset as co
from pathlib import Path
import numpy as np

for name in ['shelf_v1.glb', 'shelf_v2.glb', 'shelf_v3.glb']:
    p = Path('../scene/assets') / name
    verts, faces = co.load_mesh(p)
    pts, normals = co.sample_surface_points_with_normals(verts, faces, max_samples=200000)
    prof, y_min, y_max = co.spread_profile(pts, co.N_SLABS)
    y = pts[:, 1]
    idx = np.clip(((y - y_min) / (y_max - y_min) * (co.N_SLABS - 1)).astype(np.int64), 0, co.N_SLABS - 1)
    order = np.argsort(idx, kind='stable')
    idx_s, n_s = idx[order], normals[order]
    bounds = np.searchsorted(idx_s, np.arange(co.N_SLABS + 1))
    up_counts = []
    for j in range(co.N_SLABS):
        a, b = bounds[j], bounds[j + 1]
        up_counts.append(0 if b - a < 3 else (n_s[a:b, 1] > 0.9).sum())
    max_up = max(1, max(up_counts))
    up_frac = np.array([float(v) / float(max_up) for v in up_counts], dtype=np.float64)
    print(name)
    print('  y_min,y_max', y_min, y_max)
    print('  prof max', max(prof))
    print('  first 20 prof', prof[:20])
    print('  first 20 up_frac', up_frac[:20])
    print('  slab indices with up_frac>=0.35', [i for i,v in enumerate(up_frac) if v>=0.35])
    c, s, diag = co.estimate_offsets(pts, normals=normals)
    print('  contact', c, 'support', s)
    print('  planes', len(diag['support_planes']))
    for plane in diag['support_planes']:
        print('   ', plane)
    print('---')
