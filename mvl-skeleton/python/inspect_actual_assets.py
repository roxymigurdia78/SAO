import json
from pathlib import Path
import contact_offset as co

assets = [
    'crystal_v1.glb',
    'lantern_v1.glb',
    'plant_v1.glb',
    'plant_v2.glb',
    'shelf_v1.glb',
    'shelf_v2.glb',
    'shelf_v3.glb',
    'table_v1.glb',
    'table_v2.glb',
]
base = Path('..') / 'scene' / 'assets'
for name in assets:
    p = base / name
    if not p.exists():
        print(name, 'missing')
        continue
    verts, faces = co.load_mesh(p)
    points = co.sample_surface_points(verts, faces, max_samples=200000)
    contact, support, diag = co.estimate_offsets(points)
    print('---', name)
    for k in ['contact_offset', 'support_offset', 'ground_type', 'confidence', 'needs_review', 'axis_warning', 'note']:
        print(f'{k}:', {'contact_offset': contact, 'support_offset': support}.get(k, diag.get(k)))
    print('support_planes:', diag.get('support_planes'))
    print('body_bottom_slab:', diag.get('body_bottom_slab'))
    print('peripheral_min_frac:', diag.get('peripheral_min_frac'))
    print('profile maxima:', 'x', co._axis_profile(points, 'x'), 'y', co._axis_profile(points, 'y'), 'z', co._axis_profile(points, 'z'))
    print()
