"""Stage-4 experiment: render -> parse -> network-wide verification, plus fault-injection detection.

Per scenario (prefix-pair blocks, ILP at the smallest capacity factor in FACTORS that is feasible):
  1. clean deployment must verify (all zone pairs x all equal-cost paths);
  2. device faults (rule-order swap, port off-by-one, destination-prefix typo), 3 random instances each:
     detected by network-wide verification?  by a per-device consistency check?
  3. placement fault 'ecmp-1': placement computed on ONE shortest path per pair (what path-agnostic tools assume),
     rendered consistently, then verified against all equal-cost paths.
A mutation that the complete verifier accepts is semantically equivalent (equivalent mutant) and is reported as such.
"""
import os, sys, json, glob, time, random, itertools
import networkx as nx
from policy import rule_from_dict, blocks
import placement as PL
from netverify import deploy, verify_network, mutate, local_check

ROOT = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..")
FACTORS = [1.5, 2.0, 3.0, 4.0, 6.0, 8.0, 12.0]


def place_feasible(B, P, zones, tot, n_r):
    for f in FACTORS:
        place, info = PL.ilp(B, P, zones, f * tot / n_r, time_limit=30)
        if place is not None: return place, f
    return None, None


def run(sc, rng):
    G = nx.Graph(); G.add_edges_from(map(tuple, sc["edges"]))
    zones = {z: dict(router=v["router"], prefixes=v["prefixes"]) for z, v in sc["zones"].items()}
    gt = [rule_from_dict(r) for r in sc["gt"]]
    P = PL.paths_for(G, zones); B = PL.prefix_blocks(blocks(gt, list(zones)), zones)
    tot = sum(PL.block_cost(B[b], zones, *b) for b in B); n_r = G.number_of_nodes()
    place, f = place_feasible(B, P, zones, tot, n_r)
    row = dict(id=sc["id"], n_routers=n_r, n_zones=len(zones), n_blocks=len(B), factor=f)
    if place is None: row["status"] = "no feasible placement"; return row
    cfg = deploy(place, B, zones, list(G.nodes()))
    nrules = {r: sum(l.startswith("-A FORWARD -s") for l in t.splitlines()) for r, t in cfg.items()}
    ok, cex, dt, n = verify_network(gt, zones, P, cfg)
    row.update(clean_ok=ok, clean_cex=cex, verify_s=dt, checks=n, rules_total=sum(nrules.values()),
               rules_max=max(nrules.values()), lines_total=sum(len(t.splitlines()) for t in cfg.values()))
    muts = []
    for kind in ("swap", "port", "prefix"):
        for k in range(3):
            mc, desc = mutate(cfg, place, B, P, kind, rng)
            if mc is None: muts.append(dict(kind=kind, injected=False, why=desc)); break
            ok_m, cex_m, dt_m, _ = verify_network(gt, zones, P, mc)
            muts.append(dict(kind=kind, injected=True, desc=desc, net_detect=not ok_m, local_detect=not local_check(mc, place, B, zones),
                             verify_s=dt_m))
    # placement fault: single shortest path per pair
    P1 = {k: v[:1] for k, v in P.items()}
    if any(len(v) > 1 for v in P.values()):
        p1, _ = PL.ilp(B, P1, zones, (f or 12.0) * tot / n_r, time_limit=30)
        if p1 is not None:
            c1 = deploy(p1, B, zones, list(G.nodes()))
            ok1, cex1, dt1, _ = verify_network(gt, zones, P, c1)
            muts.append(dict(kind="ecmp-1", injected=True, net_detect=not ok1, local_detect=not local_check(c1, p1, B, zones),
                             cover_all_paths=PL.check_cover(p1, P, B), verify_s=dt1, cex=cex1))
    else: muts.append(dict(kind="ecmp-1", injected=False, why="single path everywhere"))
    row["mutations"] = muts; row["status"] = "ok"
    return row


def main(n):
    rng = random.Random(7)
    fs = [f for f in sorted(glob.glob(os.path.join(ROOT, "data", "scenarios", "*.json"))) if "_index" not in f][:n]
    out = os.path.join(ROOT, "results", "deploy_verify.json")
    rows = json.load(open(out)) if os.path.exists(out) else []; done = {r["id"] for r in rows}
    for k, fp in enumerate(fs):
        sc = json.load(open(fp))
        if sc["id"] in done: continue
        rng = random.Random(7 + k); t = time.time(); r = run(sc, rng); r["wall_s"] = time.time() - t; rows.append(r)
        m = r.get("mutations", [])
        print(f"{sc['id']:28s} f={r.get('factor')} clean={r.get('clean_ok')} checks={r.get('checks')} rules={r.get('rules_total')} "
              f"verify={r.get('verify_s', 0):.1f}s | net-detect {sum(x.get('net_detect', 0) for x in m)}/{sum(x['injected'] for x in m)} "
              f"local {sum(x.get('local_detect', 0) for x in m)} | {r['wall_s']:.0f}s", flush=True)
        json.dump(rows, open(os.path.join(ROOT, "results", "deploy_verify.json"), "w"), indent=0, default=str)


if __name__ == "__main__":
    main(int(sys.argv[1]) if len(sys.argv) > 1 else 60)
