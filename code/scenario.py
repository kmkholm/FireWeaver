"""FireWeaver-Bench scenario generator.

A scenario = a real Internet Topology Zoo network + security zones attached to routers (address blocks drawn from the
real ClassBench prefix pool) + a set of typed security INTENTS.  Each intent is rendered to natural language (several
phrasing styles) and compiled deterministically to the ground-truth first-match zone policy, so the NL text and the
ground truth are consistent by construction.

Intent types (compiled in this precedence order):
  block(s, d)                      explicit deny of everything s -> d (overrides later wildcard allows)
  allow_except(s, d, broad, ex[])  deny the exception services, then permit the broad service
  allow(s, d, svcs[])              permit each service
  isolate(s, allowed[(d, svc)])    s may only reach the listed (d, svc); everything else from s denied
  public(d, svcs[])                any zone may reach d on svcs
"""
import os, sys, json, glob, re
import numpy as np
import networkx as nx
from policy import Rule, classbench_profile

ROOT = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..")
DATA = os.path.join(ROOT, "data")

SERVICES = {   # name -> (proto, lo, hi)   (ports observed among the most frequent ClassBench destination ranges)
    "ssh": ("tcp", 22, 22), "telnet": ("tcp", 23, 23), "smtp": ("tcp", 25, 25), "dns": ("udp", 53, 53),
    "dns-tcp": ("tcp", 53, 53), "http": ("tcp", 80, 80), "https": ("tcp", 443, 443), "ntp": ("udp", 123, 123),
    "snmp": ("udp", 161, 161), "syslog": ("udp", 514, 514), "tftp": ("udp", 69, 69), "ftp": ("tcp", 21, 21),
    "rdp": ("tcp", 3389, 3389), "mysql": ("tcp", 3306, 3306), "postgres": ("tcp", 5432, 5432),
    "rtsp": ("tcp", 554, 554), "smb": ("tcp", 445, 445), "imap": ("tcp", 143, 143), "ldap": ("tcp", 389, 389),
    "web-alt": ("tcp", 8000, 8999), "high-tcp": ("tcp", 1024, 65535), "high-udp": ("udp", 1024, 65535),
    "icmp": ("icmp", 0, 65535), "any-tcp": ("tcp", 0, 65535), "any-udp": ("udp", 0, 65535), "any": ("*", 0, 65535),
}
SVC_TEXT = {"ssh": "SSH (TCP 22)", "telnet": "Telnet (TCP 23)", "smtp": "SMTP (TCP 25)", "dns": "DNS over UDP 53",
            "dns-tcp": "DNS over TCP 53", "http": "HTTP (TCP 80)", "https": "HTTPS (TCP 443)", "ntp": "NTP (UDP 123)",
            "snmp": "SNMP (UDP 161)", "syslog": "syslog (UDP 514)", "tftp": "TFTP (UDP 69)", "ftp": "FTP (TCP 21)",
            "rdp": "RDP (TCP 3389)", "mysql": "MySQL (TCP 3306)", "postgres": "PostgreSQL (TCP 5432)",
            "rtsp": "RTSP (TCP 554)", "smb": "SMB (TCP 445)", "imap": "IMAP (TCP 143)", "ldap": "LDAP (TCP 389)",
            "web-alt": "TCP ports 8000-8999", "high-tcp": "TCP ports 1024-65535", "high-udp": "UDP ports 1024-65535",
            "icmp": "ICMP", "any-tcp": "any TCP port", "any-udp": "any UDP port", "any": "any traffic"}
ZONE_ROLES = ["finance", "hr", "engineering", "dmz-web", "database", "mail", "cameras", "nvr", "guest-wifi",
              "admin", "voip", "backup", "printers", "scada", "iot-sensors", "dev-lab", "ops", "monitoring",
              "dns-servers", "ntp-servers", "vpn-users", "student-lab", "library", "research", "partners", "edge-cache"]


def load_topologies(nmin=12, nmax=90):
    out = {}
    for f in sorted(glob.glob(os.path.join(DATA, "topologyzoo", "sources", "*.graphml"))):
        try: g = nx.read_graphml(f)
        except Exception: continue
        g = nx.Graph(g); g.remove_edges_from(nx.selfloop_edges(g))
        if g.number_of_nodes() == 0: continue
        cc = max(nx.connected_components(g), key=len); g = g.subgraph(cc).copy()
        if nmin <= g.number_of_nodes() <= nmax: out[os.path.basename(f)[:-8]] = nx.convert_node_labels_to_integers(g)
    return out


def render(it, style):
    s = it["type"]
    if s == "allow":
        sv = " and ".join(SVC_TEXT[x] for x in it["svcs"])
        return [f"Hosts in {it['src']} may reach {it['dst']} over {sv}.",
                f"Allow {it['src']} to connect to {it['dst']} using {sv}.",
                f"{it['dst']} must accept {sv} from {it['src']}."][style % 3]
    if s == "allow_except":
        ex = ", ".join(SVC_TEXT[x] for x in it["ex"])
        return [f"{it['src']} may use {SVC_TEXT[it['broad']]} towards {it['dst']}, except {ex}, which must be blocked.",
                f"Permit {SVC_TEXT[it['broad']]} from {it['src']} to {it['dst']} but deny {ex}.",
                f"Block {ex} from {it['src']} to {it['dst']}; the rest of {SVC_TEXT[it['broad']]} between them is allowed."][style % 3]
    if s == "block":
        return [f"{it['src']} must never reach {it['dst']}, regardless of any other rule.",
                f"Deny all traffic from {it['src']} to {it['dst']} (this overrides any public service).",
                f"No packet from {it['src']} may enter {it['dst']}, even for services open to everyone."][style % 3]
    if s == "isolate":
        al = "; ".join(f"{d} on {SVC_TEXT[v]}" for d, v in it["allowed"])
        return [f"{it['src']} is isolated: it may only reach {al}, and nothing else.",
                f"Restrict {it['src']} so that its only permitted destinations are {al}; drop all other traffic it originates.",
                f"Apart from {al}, all traffic originating in {it['src']} must be dropped."][style % 3]
    if s == "public":
        sv = " and ".join(SVC_TEXT[x] for x in it["svcs"])
        return [f"{it['dst']} offers {sv} to every zone.",
                f"Any zone may connect to {it['dst']} over {sv}.",
                f"Make {sv} on {it['dst']} reachable from all internal zones."][style % 3]
    raise ValueError(s)


def compile_intents(intents):
    """deterministic intent -> first-match zone policy (precedence documented in the module docstring)"""
    R = lambda s, d, v, a: Rule(s, d, SERVICES[v][0], SERVICES[v][1], SERVICES[v][2], a)
    out = []
    for it in intents:
        if it["type"] == "block": out.append(R(it["src"], it["dst"], "any", "deny"))
    for it in intents:
        if it["type"] == "allow_except": out += [R(it["src"], it["dst"], v, "deny") for v in it["ex"]]
    for it in intents:
        if it["type"] == "allow": out += [R(it["src"], it["dst"], v, "permit") for v in it["svcs"]]
        if it["type"] == "allow_except": out.append(R(it["src"], it["dst"], it["broad"], "permit"))
    for it in intents:
        if it["type"] == "isolate": out += [R(it["src"], d, v, "permit") for d, v in it["allowed"]]
    for it in intents:
        if it["type"] == "isolate": out.append(R(it["src"], "*", "any", "deny"))
    for it in intents:
        if it["type"] == "public": out += [R("*", it["dst"], v, "permit") for v in it["svcs"]]
    return out


def disjoint_prefixes(zones, pool, seed):
    """post-pass: a prefix that overlaps a prefix of an EARLIER zone is redrawn from the pool until the address plan
    is disjoint across zones (non-conflicting prefixes are left untouched, so the draw stays reproducible)"""
    import ipaddress as ipa
    rng = np.random.default_rng(10_000 + seed); taken = []
    for z in zones:
        new = []
        for p in zones[z]["prefixes"]:
            net = ipa.ip_network(p, strict=False)
            while any(net.overlaps(t) for t in taken):
                p = str(pool[rng.integers(len(pool))]); net = ipa.ip_network(p, strict=False)
            new.append(p)
        zones[z]["prefixes"] = new; taken += [ipa.ip_network(p, strict=False) for p in new]
    return zones


def make(seed, topo_name, G, n_zones, n_intents, prof):
    rng = np.random.default_rng(seed)
    deg = dict(G.degree()); nodes = sorted(G.nodes(), key=lambda n: (deg[n], rng.random()))
    hosts = nodes[:n_zones] if len(nodes) >= n_zones else list(rng.choice(nodes, n_zones))
    roles = list(rng.choice(ZONE_ROLES, n_zones, replace=False))
    pool = [p for p in prof["prefixes"] if 16 <= int(p.split("/")[1]) <= 28]
    zones = {}
    for z, h in zip(roles, hosts):
        k = int(rng.integers(1, 4))
        zones[z] = dict(router=int(h), prefixes=[str(x) for x in rng.choice(pool, k, replace=False)])
    zones = disjoint_prefixes(zones, pool, seed)
    Z = list(zones); svc_names = [s for s in SERVICES if s != "any"]
    common = ["https", "http", "ssh", "dns", "ntp", "smtp", "snmp", "syslog", "rdp", "mysql", "postgres", "rtsp", "smb", "ldap", "imap"]
    intents, used = [], set()
    kinds = rng.choice(["allow", "allow", "allow", "allow_except", "block", "isolate", "public"], n_intents)
    for kd in kinds:
        s, d = rng.choice(Z, 2, replace=False)
        if kd == "allow":
            intents.append(dict(type="allow", src=s, dst=d, svcs=list(rng.choice(common, int(rng.integers(1, 4)), replace=False))))
        elif kd == "allow_except":
            broad = rng.choice(["any-tcp", "high-tcp", "web-alt", "any-udp"])
            pool_ex = {"any-tcp": ["telnet", "smb", "rdp", "ftp"], "high-tcp": ["rdp", "mysql", "postgres"],
                       "web-alt": ["web-alt"], "any-udp": ["tftp", "snmp"]}[broad]
            if broad == "web-alt": continue
            intents.append(dict(type="allow_except", src=s, dst=d, broad=str(broad),
                                ex=list(rng.choice(pool_ex, int(rng.integers(1, min(3, len(pool_ex)) + 1)), replace=False))))
        elif kd == "block":
            intents.append(dict(type="block", src=s, dst=d))
        elif kd == "isolate":
            if s in used: continue
            used.add(s)
            al = [(str(rng.choice([z for z in Z if z != s])), str(rng.choice(["dns", "ntp", "https", "syslog"]))) for _ in range(int(rng.integers(1, 3)))]
            intents.append(dict(type="isolate", src=s, allowed=al))
        else:
            intents.append(dict(type="public", dst=d, svcs=list(rng.choice(["https", "dns", "ntp", "http"], int(rng.integers(1, 3)), replace=False))))
    intents = [{k: (str(v) if isinstance(v, np.str_) else v) for k, v in it.items()} for it in intents]
    for it in intents:
        for k in ("svcs", "ex"):
            if k in it: it[k] = [str(x) for x in it[k]]
    nl = [render(it, int(rng.integers(0, 3))) for it in intents]
    gt = compile_intents(intents)
    zone_text = [f"{z}: hosts {', '.join(v['prefixes'])} attached to router R{v['router']}" for z, v in zones.items()]
    return dict(id=f"{topo_name}_s{seed}", topology=topo_name, n_nodes=G.number_of_nodes(), edges=[list(map(int, e)) for e in G.edges()],
                zones=zones, zone_text=zone_text, intents=intents, nl=nl, gt=[r.as_dict() for r in gt])


def main(n_scen=60):
    prof = classbench_profile(glob.glob(os.path.join(DATA, "classbench", "1k_1", "*.rules")))
    topos = load_topologies(); names = sorted(topos)
    rng = np.random.default_rng(2026)
    os.makedirs(os.path.join(DATA, "scenarios"), exist_ok=True)
    meta = []
    for i in range(n_scen):
        t = names[rng.integers(len(names))]
        nz = int(rng.choice([6, 10, 16])); ni = int(rng.choice([8, 16, 32]))
        sc = make(1000 + i, t, topos[t], nz, ni, prof)
        json.dump(sc, open(os.path.join(DATA, "scenarios", f"{sc['id']}.json"), "w"), indent=1)
        meta.append((sc["id"], sc["n_nodes"], nz, len(sc["intents"]), len(sc["gt"])))
    print(f"topologies usable: {len(topos)} | scenarios: {len(meta)}")
    a = np.array([m[1:] for m in meta])
    print("nodes   min/median/max", a[:, 0].min(), int(np.median(a[:, 0])), a[:, 0].max())
    print("zones", sorted(set(a[:, 1])), "| intents median", int(np.median(a[:, 2])), "| GT rules min/median/max", a[:, 3].min(), int(np.median(a[:, 3])), a[:, 3].max())
    json.dump(meta, open(os.path.join(DATA, "scenarios", "_index.json"), "w"), indent=0)


if __name__ == "__main__":
    main(int(sys.argv[1]) if len(sys.argv) > 1 else 60)
