"""Stage 4: device rendering + network-wide header-space verification of the DEPLOYED configuration.

render_router : placed blocks -> iptables-restore text for one router (FORWARD chain, policy ACCEPT for transit,
                conntrack ESTABLISHED/RELATED accepted first so that permitted flows get their replies).
parse_iptables: independent parser of that text back into match tuples (it never sees the block objects, so a
                rendering bug shows up as a verification failure).
verify_network: Z3 over the full new-connection header (src IP 32 bit, dst IP 32 bit, proto 8 bit, dst port 16 bit):
                for every ordered zone pair and EVERY equal-cost path, the packet is delivered iff all routers on the
                path accept it; this must equal the zone policy's first-match decision for all headers whose source
                lies in the source zone and destination in the destination zone.  Returns a concrete counterexample
                packet otherwise.
mutate        : fault injection for the detection experiment (coverage hole, rule-order swap, port off-by-one, wrong
                destination prefix).
"""
import re, time, random, ipaddress as ipa
import z3
from policy import Rule, PROTO, service_fn, _svc_pred
from placement import _paths, zone_of

LINE = re.compile(r"-A FORWARD -s (\S+) -d (\S+)(?: -p (\w+))?(?: --dport (\d+)(?::(\d+))?)? -j (ACCEPT|DROP)$")


def rule_lines(rules, ps, pd):
    out = []
    for r in rules:
        m = f"-A FORWARD -s {ps} -d {pd}"
        if r.proto != "*":
            m += f" -p {r.proto}"
            if r.proto in ("tcp", "udp") and not (r.dlo == 0 and r.dhi == 65535):
                m += f" --dport {r.dlo}" + (f":{r.dhi}" if r.dhi != r.dlo else "")
        out.append(m + (" -j ACCEPT" if r.action == "permit" else " -j DROP"))
    return out


def render_router(router, place, B, zones):
    """iptables-restore text of one router; blocks keyed by (src-key, dst-key) at prefix or zone granularity"""
    lines = ["*filter", ":INPUT ACCEPT [0:0]", ":FORWARD ACCEPT [0:0]", ":OUTPUT ACCEPT [0:0]",
             "-A FORWARD -m conntrack --ctstate ESTABLISHED,RELATED -j ACCEPT"]
    for b, rs in sorted(place.items(), key=lambda kv: str(kv[0])):
        if router not in rs: continue
        s, d = b
        sp = [s[1]] if isinstance(s, tuple) else zones[s]["prefixes"]
        dp = [d[1]] if isinstance(d, tuple) else zones[d]["prefixes"]
        for ps in sp:
            for pd in dp:
                lines += rule_lines(B[b], ps, pd)
    return "\n".join(lines + ["COMMIT", ""])


def parse_iptables(text):
    rules = []
    for l in text.splitlines():
        m = LINE.match(l.strip())
        if not m: continue
        s, d, p, lo, hi, act = m.groups()
        p = p or "*"; lo = int(lo) if lo else 0; hi = int(hi) if hi else (int(lo) if lo else 65535)
        rules.append((ipa.ip_network(s, strict=False), ipa.ip_network(d, strict=False), p, lo, hi, act == "ACCEPT"))
    return rules


def _in_net(X, net):
    if net.prefixlen == 0: return z3.BoolVal(True)
    mask = (0xFFFFFFFF << (32 - net.prefixlen)) & 0xFFFFFFFF
    return (X & mask) == int(net.network_address)


def _dev_decision(rules, S, D, P, T):
    e = z3.BoolVal(True)                                  # unmatched transit traffic is forwarded
    for net_s, net_d, p, lo, hi, acc in reversed(rules):
        c = [_in_net(S, net_s), _in_net(D, net_d)]
        if p != "*": c.append(P == PROTO[p])
        if p in ("tcp", "udp") and not (lo == 0 and hi == 65535): c += [z3.UGE(T, lo), z3.ULE(T, hi)]
        e = z3.If(z3.And(*c), z3.BoolVal(acc), e)
    return e


def verify_network(gt, zones, P, configs, timeout_ms=60000):
    """configs: router -> iptables text.  Returns (ok, counterexample or None, seconds, #checks)"""
    t = time.time(); dev = {r: parse_iptables(txt) for r, txt in configs.items()}
    S, D, Pr, T = z3.BitVec("src", 32), z3.BitVec("dst", 32), z3.BitVec("proto", 8), z3.BitVec("dport", 16)
    n = 0
    for s in zones:
        for d in zones:
            if s == d: continue
            rel = [Rule(s, d, r.proto, r.dlo, r.dhi, r.action) for r in gt if r.src in ("*", s) and r.dst in ("*", d)]
            intended = service_fn(rel, Pr, T)
            src_in = z3.Or(*[_in_net(S, ipa.ip_network(p, strict=False)) for p in zones[s]["prefixes"]])
            dst_in = z3.Or(*[_in_net(D, ipa.ip_network(p, strict=False)) for p in zones[d]["prefixes"]])
            for pi in P[(s, d)]:
                delivered = z3.And(*[_dev_decision(dev.get(r, []), S, D, Pr, T) for r in pi])
                sol = z3.Solver(); sol.set("timeout", timeout_ms); n += 1
                sol.add(src_in, dst_in, delivered != intended)
                res = sol.check()
                if res != z3.unsat:
                    if res == z3.unknown: return False, dict(src_zone=s, dst_zone=d, path=pi, reason="timeout"), time.time() - t, n
                    m = sol.model()
                    return False, dict(src_zone=s, dst_zone=d, path=pi, src=str(ipa.ip_address(m.eval(S, model_completion=True).as_long())),
                                       dst=str(ipa.ip_address(m.eval(D, model_completion=True).as_long())), proto=m.eval(Pr, model_completion=True).as_long(),
                                       dport=m.eval(T, model_completion=True).as_long(), intended=bool(z3.is_true(m.eval(intended, model_completion=True)))), time.time() - t, n
    return True, None, time.time() - t, n


def deploy(place, B, zones, routers):
    return {r: render_router(r, place, B, zones) for r in routers}


def mutate(configs, place, B, P, kind, rng):
    """device-level faults (the placement stays as computed): returns (mutated configs, description) or
    (None, reason) when the fault cannot be injected.  Placement-level faults are produced by placing with a
    truncated path set instead (see eval_deploy.py)."""
    cf = dict(configs)
    lines_by_r = {r: t.splitlines() for r, t in cf.items()}
    rule_idx = [(r, i) for r, ls in lines_by_r.items() for i, l in enumerate(ls) if LINE.match(l.strip())]
    if not rule_idx: return None, "no rules"
    if kind == "swap":                 # swap two adjacent rules of the same prefix pair with different actions
        cand = []
        for r, ls in lines_by_r.items():
            for i in range(len(ls) - 1):
                a, b = LINE.match(ls[i].strip()), LINE.match(ls[i + 1].strip())
                if a and b and a.group(1, 2) == b.group(1, 2) and a.group(6) != b.group(6): cand.append((r, i))
        if not cand: return None, "no swappable pair"
        r, i = rng.choice(cand); ls = lines_by_r[r]; ls[i], ls[i + 1] = ls[i + 1], ls[i]
        cf[r] = "\n".join(ls); return cf, f"swap: router {r} lines {i},{i + 1}"
    if kind == "port":                 # off-by-one on a single-port match
        cand = [(r, i) for r, i in rule_idx if re.search(r"--dport (\d+) ", lines_by_r[r][i] + " ")]
        if not cand: return None, "no single port"
        r, i = rng.choice(cand); ls = lines_by_r[r]
        ls[i] = re.sub(r"--dport (\d+)", lambda m: f"--dport {int(m.group(1)) + 1}", ls[i], count=1)
        cf[r] = "\n".join(ls); return cf, f"port+1: router {r} line {i}"
    if kind == "prefix":               # destination prefix typo: last octet of the network changed
        r, i = rng.choice(rule_idx); ls = lines_by_r[r]; m = LINE.match(ls[i].strip())
        net = ipa.ip_network(m.group(2), strict=False)
        new = ipa.ip_network(f"{ipa.ip_address(int(net.network_address) ^ (1 << (32 - net.prefixlen)))}/{net.prefixlen}")
        ls[i] = ls[i].replace(f"-d {m.group(2)} ", f"-d {new} ")
        cf[r] = "\n".join(ls); return cf, f"prefix: router {r} line {i} {m.group(2)}->{new}"
    raise ValueError(kind)


def local_check(configs, place, B, zones):
    """per-device check only (what a device-by-device linter can see): every placed block's rules appear in order
    on each router that should hold it; it cannot see paths, so a removed block counts as 'not placed'"""
    for b, rs in place.items():
        for r in rs:
            want = rule_lines(B[b], b[0][1], b[1][1])
            have = [l for l in configs[r].splitlines() if l in set(want)]
            if have != want: return False
    return True
