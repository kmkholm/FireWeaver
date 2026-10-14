"""Stage-3 evaluation: capacity-aware placement of the ground-truth policy of every FireWeaver-Bench scenario.

Fixed grid: 60 scenarios x capacity factor f in FACTORS x block granularity {prefix-pair (FireWeaver), zone-pair
(ablation)} x method {ILP (FireWeaver), greedy, ingress-only, egress-only}.
Per-router capacity C = f * (sum of block costs) / (#routers): f = 1 means the policy would just fit if it could be
spread perfectly evenly with no duplication.
Metrics: feasible, every-ECMP-path coverage (check_cover), total / max entries, duplicated entries, routers used,
drop position (0 = denied traffic dropped at the first hop), solve time.
"""
import os, sys, json, glob, time
import numpy as np
import networkx as nx
from policy import rule_from_dict, blocks
from placement import paths_for, prefix_blocks, block_cost, ilp, heuristic, metrics, check_cover

ROOT = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..")
FACTORS = [1.0, 1.5, 2.0, 3.0, 4.0, 6.0, 8.0, 12.0]
METHODS = ["ilp", "greedy", "ingress", "egress"]


def run(sc):
    G = nx.Graph(); G.add_edges_from(map(tuple, sc["edges"]))
    zones = {z: dict(router=v["router"], prefixes=v["prefixes"]) for z, v in sc["zones"].items()}
    gt = [rule_from_dict(r) for r in sc["gt"]]
    P = paths_for(G, zones); zb = blocks(gt, list(zones))
    out = []
    for gran, B in (("prefix", prefix_blocks(zb, zones)), ("zone", zb)):
        tot = sum(block_cost(B[b], zones, *b) for b in B); n_r = G.number_of_nodes()
        for f in FACTORS:
            cap = f * tot / n_r
            for m in METHODS:
                if m == "ilp": place, info = ilp(B, P, zones, cap, time_limit=30)
                else: place, info = heuristic(B, P, zones, cap, m)
                row = dict(id=sc["id"], gran=gran, f=f, method=m, n_blocks=len(B), entries_single=tot, n_routers=n_r,
                           cap=cap, solve_s=info["solve_s"], feasible=place is not None)
                if place is not None:
                    row.update(metrics(place, B, P, zones)); row["cover_ok"] = check_cover(place, P, B)
                out.append(row)
    return out


def main(n):
    fs = [f for f in sorted(glob.glob(os.path.join(ROOT, "data", "scenarios", "*.json"))) if "_index" not in f][:n]
    rows = []; t0 = time.time()
    for f in fs:
        sc = json.load(open(f)); t = time.time(); r = run(sc); rows += r
        feas = {m: sum(x["feasible"] for x in r if x["method"] == m and x["gran"] == "prefix") for m in METHODS}
        print(f"{sc['id']:28s} blocks(prefix)={r[0]['n_blocks']:5d} feasible over {len(FACTORS)} factors {feas} | {time.time() - t:.1f}s", flush=True)
    os.makedirs(os.path.join(ROOT, "results"), exist_ok=True)
    json.dump(rows, open(os.path.join(ROOT, "results", "placement_sweep.json"), "w"), indent=0)
    print(f"done {len(rows)} rows in {time.time() - t0:.0f}s")


if __name__ == "__main__":
    main(int(sys.argv[1]) if len(sys.argv) > 1 else 60)
