"""Build the testbed spec for one scenario (Windows side): private re-addressing, placement, rendered configurations
(verified FireWeaver deployment + the 'ecmp-1' faulty placement + an empty FORWARD chain), and the probe set.

Re-addressing: ClassBench prefixes include non-routable space (127/8, 240/4, ...), so every zone prefix is mapped
one-to-one to an aligned block of the same length inside 10.0.0.0/8 (zone policy and placement are unchanged).
Probes (per ordered zone pair): destination ports at every boundary of the ground-truth rules of the pair (lo, hi,
lo-1, hi+1) plus a common and a random port per protocol, ICMP echo; each probe is sent from N_SPORT source ports so
that L4-hashed ECMP spreads it over the equal-cost paths; source/destination prefix drawn per probe.
"""
import os, sys, json, random, itertools, ipaddress as ipa
import networkx as nx
from policy import rule_from_dict, blocks, decide, Rule
import placement as PL
from netverify import deploy, verify_network

ROOT = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..")
FACTORS = [1.5, 2.0, 3.0, 4.0, 6.0, 8.0, 12.0]
N_SPORT = 4


def remap(zones):
    allp = sorted({p for z in zones.values() for p in z["prefixes"]}, key=lambda p: int(p.split("/")[1]))
    cur = int(ipa.ip_address("10.0.0.0")); m = {}
    for p in allp:
        L = int(p.split("/")[1]); size = 1 << (32 - L); cur = (cur + size - 1) // size * size
        m[p] = f"{ipa.ip_address(cur)}/{L}"; cur += size
    assert cur <= int(ipa.ip_address("11.0.0.0"))
    return {z: dict(router=v["router"], prefixes=[m[p] for p in v["prefixes"]]) for z, v in zones.items()}, m


def probe_set(gt, zones, rng):
    out = []
    for s, d in itertools.permutations(zones, 2):
        rel = [r for r in gt if r.src in ("*", s) and r.dst in ("*", d)]
        ports = {"tcp": {22, 443, rng.randrange(1024, 65536)}, "udp": {53, 123, rng.randrange(1024, 65536)}}
        for r in rel:
            for pr in (["tcp", "udp"] if r.proto == "*" else [r.proto]):
                if pr not in ports: continue
                for x in (r.dlo, r.dhi, r.dlo - 1, r.dhi + 1):
                    if 1 <= x <= 65535: ports[pr].add(x)
        items = [(pr, p) for pr in ("tcp", "udp") for p in sorted(ports[pr])] + [("icmp", 0)]
        for pr, port in items:
            ps = rng.choice(zones[s]["prefixes"]); pd = rng.choice(zones[d]["prefixes"])
            src = str(ipa.ip_network(ps).network_address + 1); dst = str(ipa.ip_network(pd).network_address + 1)
            want = decide(gt, s, d, pr, port) == "permit"
            for k in range(N_SPORT if pr != "icmp" else 1):
                out.append(dict(src_zone=s, dst_zone=d, src=src, dst=dst, proto={"tcp": 6, "udp": 17, "icmp": 1}[pr],
                                sport=20000 + rng.randrange(40000), dport=port, intended=want))
    return out


def prepare(sid):
    sc = json.load(open(os.path.join(ROOT, "data", "scenarios", sid + ".json")))
    G = nx.Graph(); G.add_edges_from(map(tuple, sc["edges"]))
    G = nx.convert_node_labels_to_integers(G, ordering="sorted"); assert sorted(G.nodes()) == list(range(G.number_of_nodes()))
    zones, m = remap(sc["zones"]); gt = [rule_from_dict(r) for r in sc["gt"]]
    P = PL.paths_for(G, zones); B = PL.prefix_blocks(blocks(gt, list(zones)), zones)
    tot = sum(PL.block_cost(B[b], zones, *b) for b in B); n_r = G.number_of_nodes()
    for f in FACTORS:
        place, info = PL.ilp(B, P, zones, f * tot / n_r, time_limit=30)
        if place is not None: break
    P1 = {k: v[:1] for k, v in P.items()}
    p1, _ = PL.ilp(B, P1, zones, f * tot / n_r, time_limit=30)
    cfg = {"fireweaver": deploy(place, B, zones, list(G.nodes())), "ecmp1": deploy(p1, B, zones, list(G.nodes()))}
    cfg["none"] = {r: "*filter\n:INPUT ACCEPT [0:0]\n:FORWARD ACCEPT [0:0]\n:OUTPUT ACCEPT [0:0]\nCOMMIT\n" for r in G.nodes()}
    ver = {k: verify_network(gt, zones, P, v)[:2] for k, v in cfg.items() if k != "none"}
    spec = dict(id=sid, n_routers=n_r, edges=[list(e) for e in G.edges()], zones=zones, factor=f, remap=m,
                configs={k: {str(r): t for r, t in v.items()} for k, v in cfg.items()},
                z3={k: dict(ok=v[0], cex=v[1]) for k, v in ver.items()},
                multipath_pairs=sum(len(v) > 1 for v in P.values()), n_pairs=len(P))
    probes = probe_set(gt, zones, random.Random(11))
    d = os.path.join(ROOT, "emulation", "runs", sid); os.makedirs(d, exist_ok=True)
    json.dump(spec, open(os.path.join(d, "spec.json"), "w")); json.dump(probes, open(os.path.join(d, "probes.json"), "w"))
    return spec, probes


if __name__ == "__main__":
    spec, probes = prepare(sys.argv[1])
    print(spec["id"], "routers", spec["n_routers"], "f", spec["factor"], "multipath pairs", spec["multipath_pairs"], "/", spec["n_pairs"],
          "| z3", {k: v["ok"] for k, v in spec["z3"].items()}, "| probes", len(probes), "intended permit", sum(p["intended"] for p in probes))
