"""Probe-based semantic verification and counterexample-guided repair of per-intent IR (no ground truth needed).

For every NL intent:
  1. probes: the zones and services named in the sentence (plus one unnamed service and, for isolation/public
     intents, one unnamed zone) span a small set of (src, dst, service) test packets;
  2. the LLM answers each probe directly from the sentence (allowed / denied / unspecified) - a cheap, independent
     reading of the intent;
  3. the header-space semantics of the candidate IR answer the same probes (3-valued single-intent decision);
  4. disagreements are returned to the LLM as counterexamples and the IR is re-translated (bounded rounds); the final
     IR is the one with the fewest disagreements.
"""
import json, re
from scenario import SERVICES, SVC_TEXT
from policy import Rule, matches
from llm import chat, extract_json, system_prompt, validate_ir

UNNAMED = ["telnet", "smb", "tftp", "high-udp"]


def svc_rule(v, s="x", d="y", a="permit"):
    p, lo, hi = SERVICES[v]; return Rule(s, d, p, lo, hi, a)


def probe_packet(v):
    p, lo, hi = SERVICES[v]
    return ("tcp" if p == "*" else p), (lo if p not in ("icmp",) else 0)


def intent_decision(it, s, d, v):
    """3-valued semantics of a single intent for zone pair (s, d) and service v"""
    proto, port = probe_packet(v)
    hit = lambda w: matches(svc_rule(w, s, d), s, d, proto, port)
    t = it.get("type")
    if t == "block": return "denied" if (it.get("src"), it.get("dst")) == (s, d) else "unspecified"
    if t == "allow":
        return "allowed" if (it.get("src"), it.get("dst")) == (s, d) and any(hit(w) for w in it.get("svcs", [])) else "unspecified"
    if t == "allow_except":
        if (it.get("src"), it.get("dst")) != (s, d): return "unspecified"
        if any(hit(w) for w in it.get("ex", [])): return "denied"
        return "allowed" if hit(it.get("broad", "any")) else "unspecified"
    if t == "isolate":
        if it.get("src") != s: return "unspecified"
        return "allowed" if any(z == d and hit(w) for z, w in it.get("allowed", [])) else "denied"
    if t == "public":
        return "allowed" if it.get("dst") == d and any(hit(w) for w in it.get("svcs", [])) else "unspecified"
    return "unspecified"


def probes_for(sent, zones):
    Z = [z for z in sorted(zones, key=len, reverse=True) if re.search(rf"(?<![\w-]){re.escape(z)}(?![\w-])", sent)]
    named = [k for k, t in SVC_TEXT.items() if t in sent]
    other_z = [z for z in zones if z not in Z][:1]
    svcs = list(dict.fromkeys(named + [u for u in UNNAMED if u not in named][:1]))
    pairs = [(a, b) for a in Z for b in Z if a != b]
    if other_z and Z: pairs += [(Z[0], other_z[0]), (other_z[0], Z[-1])]
    return [(a, b, v) for a, b in pairs for v in svcs]


def ask_probes(sent, probes, seed=0):
    if not probes: return {}
    q = "\n".join(f"{i + 1}. from {a} to {b}, {SVC_TEXT[v]}" for i, (a, b, v) in enumerate(probes))
    msgs = [dict(role="system", content="You read one firewall intent and say, for each listed traffic case, whether the intent "
                                      "ALLOWS it, DENIES it, or is SILENT about it (unspecified). Judge only from this intent."),
            dict(role="user", content=f"Intent: {sent}\nCases:\n{q}\nAnswer JSON only: {{\"1\":\"allowed|denied|unspecified\", ...}}")]
    txt, _ = chat(msgs, max_tokens=40 + 12 * len(probes), seed=seed)
    try: ans = extract_json(txt)
    except Exception: return {}
    out = {}
    for i, p in enumerate(probes):
        a = str(ans.get(str(i + 1), "")).lower()
        if a.startswith("allow"): out[p] = "allowed"
        elif a.startswith("den") or a.startswith("block"): out[p] = "denied"
        elif a.startswith("uns") or a.startswith("sil"): out[p] = "unspecified"
    return out


def ask_single(sent, probe, seed=0):
    """independent re-read: one probe per question, different wording and answer format than ask_probes
    (greedy decoding makes a seed change alone useless as a second opinion)"""
    a, b, v = probe
    msgs = [dict(role="system", content="You are auditing a firewall requirement. Read it literally; do not assume anything "
                                      "that is not written."),
            dict(role="user", content=f"Requirement: \"{sent}\"\nQuestion: according to this requirement alone, a packet "
                                      f"sent from {a} to {b} using {SVC_TEXT[v]} is (A) explicitly permitted, (B) explicitly "
                                      f"forbidden (including 'nothing else' / 'all other traffic dropped' clauses), or "
                                      f"(C) not addressed. Answer with a single letter.")]
    txt, _ = chat(msgs, max_tokens=8, seed=seed)
    c = txt.strip().upper()[:1]
    return {"A": "allowed", "B": "denied", "C": "unspecified"}.get(c)


STRONG = {("allowed", "denied"), ("denied", "allowed")}


def disagreements(ir, oracle):
    """only STRONG conflicts (allowed vs denied); 'unspecified' readings are too noisy to act on"""
    return [(p, oracle[p], intent_decision(ir, *p)) for p in oracle if (oracle[p], intent_decision(ir, *p)) in STRONG]


def confirmed_oracle(sent, probes, ir, seed=0):
    """ask once; re-ask only the probes that conflict with the IR and keep answers that agree across both reads"""
    o1 = ask_probes(sent, probes, seed=seed)
    bad = [p for p, _, _ in disagreements(ir, o1)]
    if not bad: return o1, 1
    o2 = ask_probes(sent, bad, seed=seed + 101)
    for p in bad:
        if o2.get(p) != o1.get(p): o1.pop(p, None)
    return o1, 2


def repair(sc, sent, ir, oracle, rounds=2, think=False, seed=0):
    """re-translate with counterexamples; a candidate replaces the IR only if it (i) has strictly fewer strong
    conflicts with the confirmed oracle and (ii) wins a differential re-read: the probes on which the old and the new
    IR decide differently are asked again with a fresh seed, and the new IR must match strictly more of those answers
    than the old one. A correct IR therefore survives a wrong oracle unless the LLM errs twice in the same way."""
    best, best_d = ir, disagreements(ir, oracle); history = [len(best_d)]; calls = 0
    if not best_d: return best, dict(history=history, calls=0, accepted=False)
    sysmsg = system_prompt(sc, SERVICES); cur = ir; cand_best = None
    for r in range(rounds):
        d = disagreements(cur, oracle)
        if not d: break
        cx = "\n".join(f"- traffic from {a} to {b} on {SVC_TEXT[v]}: the intent says {want}, your IR makes it {got}"
                       for (a, b, v), want, got in d[:8])
        msgs = [dict(role="system", content=sysmsg),
                dict(role="user", content=f"Intent: {sent}\nYour IR: {json.dumps(cur)}\nA header-space check found these "
                                          f"counterexamples:\n{cx}\nChoose the IR type that matches the intent and return one corrected IR object, JSON only.")]
        txt, _ = chat(msgs, think=(think and r == rounds - 1), seed=seed + 10 + r); calls += 1
        try:
            cand = extract_json(txt); cand = cand[0] if isinstance(cand, list) else cand
            if validate_ir(cand, sc, SERVICES) is None: cur = cand
        except Exception: pass
        dd = disagreements(cur, oracle); history.append(len(dd))
        if len(dd) < len(best_d) and cur != ir: cand_best, best_d = cur, dd
    if cand_best is None: return ir, dict(history=history, calls=calls, accepted=False)
    probes = list(oracle) + [p for p in probes_for(sent, sc["zones"]) if p not in oracle]
    diff = [p for p in probes if intent_decision(ir, *p) != intent_decision(cand_best, *p)]
    fresh = {p: ask_single(sent, p, seed=seed + 202) for p in diff[:6]}; calls += len(fresh); diff = diff[:6]
    win_new = sum(fresh.get(p) == intent_decision(cand_best, *p) for p in diff)
    win_old = sum(fresh.get(p) == intent_decision(ir, *p) for p in diff)
    ok = win_new > win_old
    return (cand_best if ok else ir), dict(history=history, calls=calls, accepted=ok, diff=len(diff), win_new=win_new, win_old=win_old)
