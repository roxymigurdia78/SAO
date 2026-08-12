import numpy as np
import math
import contact_offset as co

rng0 = np.random.default_rng(0)
rng1 = np.random.default_rng(1)

def box_surface(x0, x1, y0, y1, z0, z1, n=4000):
    return np.column_stack([rng0.uniform(x0, x1, n), rng0.uniform(y0, y1, n), rng0.uniform(z0, z1, n)])


def ring_surface(cx, cz, y, r, n=2000):
    th = rng1.uniform(0, 2 * math.pi, n)
    return np.column_stack([cx + np.cos(th) * r, np.full(n, y), cz + np.sin(th) * r])


def inspect(name, pts):
    c, s, diag = co.estimate_offsets(pts)
    print('---', name)
    print('contact', c, 'support', s)
    for key in ['body_bottom_slab', 'peripheral_min_frac', 'support_planes', 'axis_scores', 'axis_warning', 'ground_type', 'note', 'needs_review', 'confidence']:
        print(key, diag.get(key))

lantern = np.vstack([
    ring_surface(0.1, 0.1, 0.0, 0.02, n=6000),
    box_surface(0.0, 0.2, 0.05, 0.45, 0.0, 0.2),
    ring_surface(0.1, 0.1, 0.5, 0.02, n=2000),
])
inspect('lantern', lantern)

lowpoly = np.vstack([
    box_surface(0.0, 0.4, 0.05, 0.4, 0.0, 0.4),
    ring_surface(0.2, 0.2, 0.0, 0.02, n=12000),
])
inspect('lowpoly', lowpoly)

desk = np.vstack([
    box_surface(0.0, 1.0, 0.0, 0.7, 0.0, 0.5),
    box_surface(0.0, 1.0, 0.7, 1.4, 0.0, 0.04),
])
inspect('desk', desk)

hanging = np.vstack([
    ring_surface(0.0, 0.0, 1.2, 0.1, n=6000),
    ring_surface(0.0, 0.0, 1.0, 0.05, n=1000),
])
inspect('hanging', hanging)
