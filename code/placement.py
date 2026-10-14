"""Capacity-aware placement of per-zone-pair rule blocks on routers (FireWeaver stage 3).

Block b = (s, d) with TCAM cost c_b = (#rules) * |prefixes(s)| * |prefixes(d)|.  Routing: all equal-cost shortest
paths between the routers of s and d (ECMP, all equal-cost paths).  A block may be installed on several routers; correctness
requires that EVERY path of b crosses at least one router holding it (blocks never overlap in header space and are
idempotent, so duplicates are harmless).

ILP (scipy.optimize.milp / HiGHS):
  x_{b,r} in {0,1} for r on some path of b
  cover:     sum_{r in pi} x_{b,r} >= 1                 for every path pi of b
  capacity:  sum_b c_b x_{b,r} <= C_r                    for every router r
  objective: sum_{b,r} c_b x_{b,r} * (1 + alpha * hop_b(r))   -> few duplicates, early drop of denied traffic
Baselines: ingress-only, egress-only, greedy first-fit along the path (ingress first).
"""
import time, itertools
import numpy as np
import networkx as nx
from scipy.optimize import milp, LinearConstraint, Bounds
from scipy.sparse import lil_matrix

KPATH = None   # ALL equal-cost shortest paths (ECMP may use any of them; a cap would leave paths unfiltered).
#               FireWeaver-Bench: 1.5 % of zone pairs have > 4 equal-cost paths, max 28.


def paths_for(G, zones):
    P = {}
    for s, zs in zones.items():
        for d, zd in zones.items():
            if s == d: continue
            P[(s, d)] = list(itertools.islice(nx.all_shortest_paths(G, zs["router"], zd["router"]), KPATH))
    return P


def block_cost(block, zones, s, d):
    """TCAM entries of a block; s / d may be zone names or (zone, prefix) tuples for prefix-pair blocks"""
    ns = 1 if isinstance(s, tuple) else len(zones[s]["prefixes"]); nd = 1 if isinstance(d, tuple) else len(zones[d]["prefixes"])
    return len(block) * ns * nd


def prefix_blocks(blocks, zones):
    """split every zone-pair block into independent (src prefix, dst prefix) blocks (disjoint in header space)"""
    out = {}
    for (s, d), bl in blocks.items():
        for ps in zones[s]["prefixes"]:
            for pd in zones[d]["prefixes"]:
                out[((s, ps), (d, pd))] = bl
    return out


def zone_of(k): return k[0] if isinstance(k, tuple) else k


def _paths(P, b): return P[(zone_of(b[0]), zone_of(b[1]))]


def ilp(blocks, P, zones, cap, alpha=0.05, time_limit=60):
    B = list(blocks); var = []
    P = {b: _paths(P, b) for b in B}
    for b in B:
        rs = sorted({r for pi in P[b] for r in pi})
        for r in rs: var.append((b, r))
    idx = {v: i for i, v in enumerate(var)}; n = len(var)
    cost = np.array([block_cost(blocks[b], zones, *b) for b, _ in var], float)
    hop = np.array([min(pi.index(r) for pi in P[b] if r in pi) for b, r in var], float)
    c = cost * (1 + alpha * hop)
    rows_cov = [(b, pi) for b in B for pi in P[b]]
    routers = sorted({r for _, r in var})
    A = lil_matrix((len(rows_cov) + len(routers), n)); lo = np.zeros(A.shape[0]); hi = np.zeros(A.shape[0])
    for i, (b, pi) in enumerate(rows_cov):
        for r in set(pi): A[i, idx[(b, r)]] = 1
        lo[i], hi[i] = 1, np.inf
    for j, r in enumerate(routers):
        k = len(rows_cov) + j
        for (b, rr), i in idx.items():
            if rr == r: A[k, i] = cost[i]
        lo[k], hi[k] = 0, cap if np.isscalar(cap) else cap[r]
    t = time.time()
    res = milp(c, constraints=LinearConstraint(A.tocsr(), lo, hi), integrality=np.ones(n), bounds=Bounds(0, 1),
               options=dict(time_limit=time_limit, disp=False))
    dt = time.time() - t
    if res.x is None: return None, dict(status=res.status, msg=res.message, solve_s=dt)
    place = {}
    for i, v in enumerate(var):
        if res.x[i] > 0.5: place.setdefault(v[0], []).append(v[1])
    return place, dict(status=res.status, solve_s=dt)


def heuristic(blocks, P, zones, cap, mode):
    """ingress | egress | greedy (first router with room along each path, ingress first)"""
    load = {}; place = {}; t = time.time()
    P = {b: _paths(P, b) for b in blocks}
    for b in sorted(blocks, key=lambda b: -block_cost(blocks[b], zones, *b)):
        c = block_cost(blocks[b], zones, *b); chosen = set()
        for pi in P[b]:
            if chosen & set(pi): continue
            order = {"ingress": pi[:1], "egress": pi[-1:], "greedy": pi}[mode]
            ok = False
            for r in order:
                limit = cap if np.isscalar(cap) else cap[r]
                if load.get(r, 0) + c <= limit:
                    load[r] = load.get(r, 0) + c; chosen.add(r); ok = True; break
            if not ok: return None, dict(status="infeasible", solve_s=time.time() - t)
        place[b] = sorted(chosen)
    return place, dict(status="ok", solve_s=time.time() - t)


def metrics(place, blocks, P, zones):
    load = {}; dup = 0; hops = []
    P = {b: _paths(P, b) for b in blocks}
    for b, rs in place.items():
        c = block_cost(blocks[b], zones, *b)
        for r in rs: load[r] = load.get(r, 0) + c
        dup += c * (len(rs) - 1)
        for pi in P[b]:
            hops.append(min(pi.index(r) for r in rs if r in pi) / max(1, len(pi) - 1))
    tot = sum(load.values())
    return dict(entries_total=tot, entries_max=max(load.values()) if load else 0, routers_used=len(load),
                duplicated_entries=dup, drop_position=float(np.mean(hops)) if hops else 0.0)


def check_cover(place, P, blocks):
    """every ECMP path of every block crosses a router holding it"""
    return all(b in place and any(r in place[b] for r in pi) for b in blocks for pi in _paths(P, b))
