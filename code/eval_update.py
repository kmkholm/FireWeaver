"""Incremental update on the live testbed: intents arrive one at a time; end-to-end latency per stage.

For a scenario already prepared by emu_prepare.py (re-addressed zones, capacity factor f): the last K intents are held
out; the network starts with the policy translated from the other intents.  Each held-out sentence then goes through
  LLM translation (one IR) -> compile -> blocks -> incremental placement (unchanged blocks stay where they are; new or
  changed blocks are placed by the ILP on the residual capacity, full re-solve only if that is infeasible)
  -> render the touched routers -> network-wide Z3 verification -> push the touched routers -> probes on the
  affected zone pairs.
usage: python eval_update.py <scenario_id> [K]
"""
import os, sys, json, time, random, itertools
import networkx as nx
sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "emulation"))
import vm_ssh
from scenario import SERVICES, compile_intents
from policy import blocks, equivalent, rule_from_dict
import placement as PL
from netverify import render_router, verify_network
from llm import translate_ir
from emu_prepare import probe_set

ROOT = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..")


def vm(cmd, timeout=3600):
    rc, o, e = vm_ssh.run(cmd, timeout=timeout)
    if rc: raise RuntimeError(f"{cmd}\n{o[-1500:]}\n{e[-2500:]}")
    return o.strip().splitlines()[-1] if o.strip() else ""


def incremental(Bn, Bo, place_o, P, zones, cap):
    keep = {b: rs for b, rs in place_o.items() if b in Bn and Bn[b] == Bo.get(b)}
    todo = {b: Bn[b] for b in Bn if b not in keep}
    load = {r: 0 for r in cap}
    for b, rs in keep.items():
        for r in rs: load[r] += PL.block_cost(Bn[b], zones, *b)
    t = time.time(); mode = "incremental"
    if todo:
        res = {r: max(0.0, cap[r] - load[r]) for r in cap}
        p2, _ = PL.ilp(todo, P, zones, res, time_limit=30)
        if p2 is None:
            p2, _ = PL.ilp(Bn, P, zones, cap, time_limit=30); mode = "full"; keep = {}
    else: p2 = {}
    place = dict(keep); place.update(p2)
    return place, time.time() - t, mode, len(todo)


def router_view(place, B, r): return sorted((str(b), tuple(B[b])) for b, rs in place.items() if r in rs)


def main(sid, K=3):
    d = os.path.join(ROOT, "emulation", "runs", sid); spec = json.load(open(os.path.join(d, "spec.json")))
    sc = json.load(open(os.path.join(ROOT, "data", "scenarios", sid + ".json")))
    zones = spec["zones"]; Z = list(zones); n_r = spec["n_routers"]
    G = nx.Graph(); G.add_edges_from(map(tuple, spec["edges"])); P = PL.paths_for(G, zones)
    gt_full = [rule_from_dict(r) for r in sc["gt"]]
    Bfull = PL.prefix_blocks(blocks(gt_full, Z), zones); tot = sum(PL.block_cost(Bfull[b], zones, *b) for b in Bfull)
    cap = {r: spec["factor"] * tot / n_r for r in range(n_r)}
    base_sc = dict(sc, nl=sc["nl"][:-K]); t = time.time()
    ir_base, _, _ = translate_ir(base_sc, SERVICES); t_base_llm = time.time() - t
    irs = [i for i in ir_base if i]
    pol = compile_intents(irs); B = PL.prefix_blocks(blocks(pol, Z), zones)
    place, _ = PL.ilp(B, P, zones, cap, time_limit=30)
    cfg = {str(r): render_router(r, place, B, zones) for r in range(n_r)}
    ok0 = verify_network(pol, zones, P, {int(k): v for k, v in cfg.items()})[0]
    rem = f"/home/gns3/fw/{sid}"; vm(f"mkdir -p {rem}")
    vm_ssh.put(os.path.join(d, "spec.json"), f"{rem}/spec.json"); vm_ssh.put(os.path.join(ROOT, "emulation", "testbed.py"), "/home/gns3/fw/testbed.py")
    vm("sudo python3 /home/gns3/fw/testbed.py down")
    up = json.loads(vm(f"sudo python3 /home/gns3/fw/testbed.py up {rem}/spec.json"))
    out = dict(id=sid, up=up, base=dict(n_intents=len(irs), llm_s=t_base_llm, verified=ok0), updates=[])
    try:
        json.dump(cfg, open(os.path.join(d, "upd_cfg.json"), "w")); vm_ssh.put(os.path.join(d, "upd_cfg.json"), f"{rem}/upd_cfg.json")
        out["base"]["push"] = json.loads(vm(f"sudo python3 /home/gns3/fw/testbed.py push {rem}/spec.json {rem}/upd_cfg.json"))
        for j, sent in enumerate(sc["nl"][-K:]):
            rec = dict(sentence=sent); T0 = time.time()
            t = time.time(); new, st, fail = translate_ir(dict(sc, nl=[sent]), SERVICES); rec["llm_s"] = time.time() - t
            rec["ir"] = new[0]; rec["ir_correct"] = bool(new[0]) and equivalent(compile_intents([new[0]]), compile_intents([sc["intents"][len(sc["nl"]) - K + j]]), Z)[0]
            t = time.time(); irs2 = irs + [i for i in new if i]; pol2 = compile_intents(irs2); B2 = PL.prefix_blocks(blocks(pol2, Z), zones); rec["compile_s"] = time.time() - t
            place2, rec["place_s"], rec["place_mode"], rec["blocks_replaced"] = incremental(B2, B, place, P, zones, cap)
            t = time.time()
            touched = [r for r in range(n_r) if router_view(place2, B2, r) != router_view(place, B, r)]
            cfg2 = {str(r): render_router(r, place2, B2, zones) for r in touched}; rec["render_s"] = time.time() - t
            full = {r: (cfg2[str(r)] if str(r) in cfg2 else cfg[str(r)]) for r in range(n_r)}
            t = time.time(); okv, cex, _, nchk = verify_network(pol2, zones, P, full); rec["verify_s"] = time.time() - t
            rec["verified"] = okv; rec["checks"] = nchk; rec["routers_touched"] = len(touched)
            rec["pipeline_s"] = time.time() - T0
            json.dump(cfg2, open(os.path.join(d, "upd_cfg.json"), "w")); vm_ssh.put(os.path.join(d, "upd_cfg.json"), f"{rem}/upd_cfg.json")
            t = time.time(); rec["push"] = json.loads(vm(f"sudo python3 /home/gns3/fw/testbed.py push {rem}/spec.json {rem}/upd_cfg.json")); rec["push_wall_s"] = time.time() - t
            rec["end_to_end_s"] = time.time() - T0
            # probes on the zone pairs whose decision changed
            gtp = [rule_from_dict(r) for r in sc["gt"]]
            aff = {(s, dd) for s, dd in itertools.permutations(Z, 2) if B2.get(((s, zones[s]["prefixes"][0]), (dd, zones[dd]["prefixes"][0]))) != B.get(((s, zones[s]["prefixes"][0]), (dd, zones[dd]["prefixes"][0])))}
            pr = [p for p in probe_set(pol2, zones, random.Random(5 + j)) if (p["src_zone"], p["dst_zone"]) in aff]
            if pr:
                json.dump(pr, open(os.path.join(d, "upd_probes.json"), "w")); vm_ssh.put(os.path.join(d, "upd_probes.json"), f"{rem}/upd_probes.json")
                vm(f"sudo python3 /home/gns3/fw/testbed.py probe {rem}/spec.json {rem}/upd_probes.json {rem}/upd_probe_out.json")
                vm_ssh.get(f"{rem}/upd_probe_out.json", os.path.join(d, f"upd_probe_{j}.json"))
                res = json.load(open(os.path.join(d, f"upd_probe_{j}.json")))["probes"]
                rec["probes"] = len(res); rec["conform"] = sum(p["delivered"] == p["intended"] for p in res)
            rec["affected_pairs"] = len(aff)
            print(sid, j, {k: (round(v, 2) if isinstance(v, float) else v) for k, v in rec.items() if k not in ("ir", "sentence", "push")}, flush=True)
            out["updates"].append(rec); irs, pol, B, place = irs2, pol2, B2, place2; cfg.update(cfg2)
    finally:
        vm("sudo python3 /home/gns3/fw/testbed.py down")
    json.dump(out, open(os.path.join(d, "update.json"), "w"), indent=1, default=str)
    return out


if __name__ == "__main__":
    main(sys.argv[1], int(sys.argv[2]) if len(sys.argv) > 2 else 3)
