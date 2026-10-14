"""Policy model, ClassBench statistics and header-space (bit-vector SMT) verification for FireWeaver.

Zone-level policy: ordered first-match list of rules (src_zone, dst_zone, proto, dport_lo, dport_hi, action) with
'*' wildcards; implicit default DENY between zones.  A zone is a named set of IPv4 prefixes (inventory).
Compilation to the device level splits the policy into per-zone-pair BLOCKS (the sub-list that can match s->d plus an
explicit trailing deny).  Blocks of different zone pairs never overlap in header space, so a block can be installed
on ANY router of the s->d path without changing first-match semantics - this is what makes placement an assignment
problem.  Verification encodes the 5-tuple header space as Z3 bit-vectors.
"""
import re, json, itertools
from dataclasses import dataclass, asdict, field
import numpy as np
import z3

PROTO = {"tcp": 6, "udp": 17, "icmp": 1, "*": None}


@dataclass(frozen=True)
class Rule:
    src: str            # zone name or '*'
    dst: str
    proto: str          # 'tcp' | 'udp' | 'icmp' | '*'
    dlo: int            # destination port range (0..65535); ignored for icmp/*-proto when full range
    dhi: int
    action: str         # 'permit' | 'deny'

    def as_dict(self): return asdict(self)


def rule_from_dict(d):
    return Rule(str(d["src"]), str(d["dst"]), str(d.get("proto", "*")).lower(), int(d.get("dlo", 0)),
                int(d.get("dhi", 65535)), str(d["action"]).lower())


# ---------------------------------------------------------------- ClassBench statistics
CB_LINE = re.compile(r"@(\S+)/(\d+)\s+(\S+)/(\d+)\s+(\d+)\s*:\s*(\d+)\s+(\d+)\s*:\s*(\d+)\s+0x(\w+)/0x(\w+)")


def read_classbench(path):
    out = []
    for line in open(path):
        m = CB_LINE.match(line.strip())
        if not m: continue
        s, sl, d, dl, slo, shi, dlo, dhi, pv, pm = m.groups()
        out.append(dict(src=f"{s}/{sl}", dst=f"{d}/{dl}", sport=(int(slo), int(shi)), dport=(int(dlo), int(dhi)),
                        proto=int(pv, 16) if int(pm, 16) else None))
    return out


def classbench_profile(paths):
    """empirical pools from real ClassBench seeds: prefixes (by length), destination-port ranges, protocols"""
    pref, dports, protos = [], [], []
    for p in paths:
        for r in read_classbench(p):
            pref += [r["src"], r["dst"]]; dports.append(r["dport"]); protos.append(r["proto"])
    return dict(prefixes=sorted(set(pref)), dports=dports, protos=protos)


# ---------------------------------------------------------------- semantics on the zone level
def matches(rule, s, d, proto, port):
    return ((rule.src == "*" or rule.src == s) and (rule.dst == "*" or rule.dst == d) and
            (rule.proto == "*" or rule.proto == proto) and
            (rule.proto in ("icmp", "*") and rule.dlo == 0 and rule.dhi == 65535 or rule.dlo <= port <= rule.dhi))


def decide(policy, s, d, proto, port):
    for r in policy:
        if matches(r, s, d, proto, port): return r.action
    return "deny"


def blocks(policy, zones, include_deny=True):
    """per ordered zone pair: the sub-list of rules that can match it (wildcards resolved), plus a trailing deny.
    Routers forward unmatched transit traffic, so a pair without any permitted service needs an explicit one-entry
    deny block (include_deny=True) - otherwise a distributed deployment would silently let it through."""
    out = {}
    for s in zones:
        for d in zones:
            if s == d: continue
            sub = [Rule(s, d, r.proto, r.dlo, r.dhi, r.action) for r in policy
                   if (r.src in ("*", s)) and (r.dst in ("*", d))]
            # drop trailing denies (implicit) and everything after an any-service rule
            cut = []
            for r in sub:
                cut.append(r)
                if r.proto == "*" and r.dlo == 0 and r.dhi == 65535: break
            while cut and cut[-1].action == "deny" and not (cut[-1].proto == "*" and cut[-1].dlo == 0 and cut[-1].dhi == 65535):
                cut.pop()
            if any(r.action == "permit" for r in cut):
                if not (cut[-1].proto == "*" and cut[-1].dlo == 0 and cut[-1].dhi == 65535):
                    cut.append(Rule(s, d, "*", 0, 65535, "deny"))
                out[(s, d)] = cut
            elif include_deny:
                out[(s, d)] = [Rule(s, d, "*", 0, 65535, "deny")]
    return out


# ---------------------------------------------------------------- header-space verification (Z3 bit-vectors)
def _svc_pred(r, P, D):
    c = []
    if r.proto != "*": c.append(P == PROTO[r.proto])
    if not (r.dlo == 0 and r.dhi == 65535) and r.proto not in ("icmp",):
        c.append(z3.And(z3.UGE(D, r.dlo), z3.ULE(D, r.dhi)))
    return z3.And(*c) if c else z3.BoolVal(True)


def service_fn(rules, P, D):
    """first-match decision over the service space of one zone pair -> Z3 Bool (True = permit)"""
    e = z3.BoolVal(False)
    for r in reversed(rules):
        e = z3.If(_svc_pred(r, P, D), z3.BoolVal(r.action == "permit"), e)
    return e


def equivalent(policy_a, policy_b, zones, timeout_ms=20000):
    """zone-level equivalence; returns (True, None) or (False, counterexample dict) for the first differing pair"""
    P, D = z3.BitVec("proto", 8), z3.BitVec("dport", 16)
    for s in zones:
        for d in zones:
            if s == d: continue
            ra = [Rule(s, d, r.proto, r.dlo, r.dhi, r.action) for r in policy_a if r.src in ("*", s) and r.dst in ("*", d)]
            rb = [Rule(s, d, r.proto, r.dlo, r.dhi, r.action) for r in policy_b if r.src in ("*", s) and r.dst in ("*", d)]
            if not ra and not rb: continue
            sol = z3.Solver(); sol.set("timeout", timeout_ms)
            sol.add(service_fn(ra, P, D) != service_fn(rb, P, D))
            if sol.check() == z3.sat:
                m = sol.model()
                return False, dict(src=s, dst=d, proto=m.eval(P).as_long(), dport=m.eval(D).as_long(),
                                   a=bool(z3.is_true(m.eval(service_fn(ra, P, D)))))
    return True, None


def mismatch_fraction(policy_a, policy_b, zones, n=4000, seed=0):
    """share of (zone pair, service) probes on which two policies disagree (common services weighted in)"""
    rng = np.random.default_rng(seed); Z = list(zones)
    common = [("tcp", p) for p in (22, 23, 25, 53, 80, 110, 143, 443, 445, 3306, 3389, 5432, 8080)] + [("udp", 53), ("udp", 123), ("udp", 161), ("icmp", 0)]
    bad = 0
    for _ in range(n):
        s, d = rng.choice(len(Z), 2, replace=False); s, d = Z[s], Z[d]
        if rng.random() < 0.5: pr, pt = common[rng.integers(len(common))]
        else: pr = ["tcp", "udp", "icmp"][rng.integers(3)]; pt = int(rng.integers(0, 65536))
        bad += decide(policy_a, s, d, pr, pt) != decide(policy_b, s, d, pr, pt)
    return bad / n


def shadowed(policy):
    """indices of rules that can never match (fully covered by earlier rules on the zone level)"""
    P, D = z3.BitVec("proto", 8), z3.BitVec("dport", 16)
    out = []
    for i, r in enumerate(policy):
        prev = [q for q in policy[:i] if (q.src in ("*", r.src) or r.src == "*") and (q.dst in ("*", r.dst) or r.dst == "*")]
        if not prev: continue
        cov = [q for q in prev if q.src in ("*", r.src) and q.dst in ("*", r.dst)]
        sol = z3.Solver(); sol.set("timeout", 5000)
        sol.add(_svc_pred(r, P, D), *[z3.Not(_svc_pred(q, P, D)) for q in cov])
        if sol.check() == z3.unsat: out.append(i)
    return out
