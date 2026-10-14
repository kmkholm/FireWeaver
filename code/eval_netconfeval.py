"""Second dataset: NetConfEval (Wang et al., Proc. ACM Netw. 2024) - formal-specification translation and conflict
detection, iteration 0 of both tasks (333 + 336 samples, all batch sizes 1-100 and 1-3 policy types).

batch : the benchmark's own setting - the whole batch of requirements -> spec JSON in one call (conflict task: the
        model must also say whether two requirements contradict each other)
ir    : FireWeaver principle - one typed IR object per requirement sentence (reach / no_reach / waypoint /
        no_waypoint / lb), deterministic merge into the spec format, deterministic conflict check
Same local Qwen3-8B Q4_K_M, greedy decoding.  Resumable: one JSON line per sample in results/netconfeval_*.jsonl.
"""
import os, sys, json, time, re
from llm import chat, extract_json

ROOT = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..")
D = os.path.join(ROOT, "data", "netconfeval")

IR_SYS = """You translate ONE network requirement sentence into one JSON object. Types:
  {"type":"reach","src":L,"prefix":P}                 L can reach prefix P
  {"type":"no_reach","src":L,"prefix":P}              L must NOT reach P
  {"type":"waypoint","src":L,"prefix":P,"via":W}      traffic from L to P passes through location W
  {"type":"no_waypoint","src":L,"prefix":P,"via":W}   traffic from L to P must NOT pass through W
  {"type":"lb","src":L,"prefix":P,"paths":N}          traffic from L to P is balanced over N paths
L and W are location names exactly as written, P is the prefix exactly as written, N is an integer.
Examples (placeholder names):
"Hosts in 10.9.9.0/24 can be reached from oslo." -> {"type":"reach","src":"oslo","prefix":"10.9.9.0/24"}
"madrid is not allowed to reach 10.1.2.0/24." -> {"type":"no_reach","src":"madrid","prefix":"10.1.2.0/24"}
"Packets from rome towards 10.3.0.0/24 traverse paris." -> {"type":"waypoint","src":"rome","prefix":"10.3.0.0/24","via":"paris"}
"Traffic from rome to 10.3.0.0/24 must avoid paris." -> {"type":"no_waypoint","src":"rome","prefix":"10.3.0.0/24","via":"paris"}
"Use 5 equal paths from lyon to 10.7.0.0/24." -> {"type":"lb","src":"lyon","prefix":"10.7.0.0/24","paths":5}
Answer with the JSON object only."""

BATCH_TRANS = """{desc}
Translate the requirements below into JSON with exactly this structure:
{{"reachability": {{location: [prefix, ...]}}, "waypoint": {{"(location,prefix)": [location, ...]}}, "loadbalancing": {{"(location,prefix)": integer}}}}
Use empty objects for unused categories. Answer with the JSON only.
Requirements:
{req}"""

BATCH_CONF = """{desc}
Below are network requirements. First decide whether two of them explicitly contradict each other (a conflict),
then answer with JSON only: {{"conflict": true|false}}.
Requirements:
{req}"""


def ir_one(sent, seed=0):
    msgs = [dict(role="system", content=IR_SYS), dict(role="user", content=sent)]
    for a in range(3):
        txt, st = chat(msgs, max_tokens=120, seed=seed + a)
        try:
            o = extract_json(txt); o = o[0] if isinstance(o, list) else o
            if o.get("type") in ("reach", "no_reach", "waypoint", "no_waypoint", "lb") and "src" in o and "prefix" in o:
                return o, st
        except Exception: pass
        msgs += [dict(role="assistant", content=txt), dict(role="user", content="Invalid. Return one JSON object of the listed types only.")]
    return None, st


def merge(irs):
    spec = {"reachability": {}, "waypoint": {}, "loadbalancing": {}}
    for o in irs:
        if o is None: continue
        s, p = str(o["src"]), str(o["prefix"]); key = f"({s},{p})"
        if o["type"] == "reach":
            spec["reachability"].setdefault(s, [])
            if p not in spec["reachability"][s]: spec["reachability"][s].append(p)
        elif o["type"] == "waypoint" and "via" in o:
            spec["waypoint"].setdefault(key, [])
            if o["via"] not in spec["waypoint"][key]: spec["waypoint"][key].append(str(o["via"]))
        elif o["type"] == "lb" and "paths" in o:
            try: spec["loadbalancing"][key] = int(o["paths"])
            except Exception: pass
    return spec


def conflicts(irs):
    """deterministic: a requirement and its explicit negation on the same (src, prefix[, via]), or two different
    path counts for the same (src, prefix)"""
    pos, neg, lb = set(), set(), {}
    for o in irs:
        if o is None: continue
        k = (str(o["src"]), str(o["prefix"]))
        if o["type"] == "reach": pos.add(("r",) + k)
        elif o["type"] == "no_reach": neg.add(("r",) + k)
        elif o["type"] == "waypoint": pos.add(("w",) + k + (str(o.get("via")),))
        elif o["type"] == "no_waypoint": neg.add(("w",) + k + (str(o.get("via")),))
        elif o["type"] == "lb":
            lb.setdefault(k, set()).add(str(o.get("paths")))
    return bool(pos & neg) or any(len(v) > 1 for v in lb.values())


def norm(spec):
    """order-insensitive comparison form"""
    if not isinstance(spec, dict): return None
    try:
        return (frozenset((k, frozenset(v)) for k, v in (spec.get("reachability") or {}).items() if v),
                frozenset((k.replace(" ", ""), frozenset(v)) for k, v in (spec.get("waypoint") or {}).items() if v),
                frozenset((k.replace(" ", ""), int(v)) for k, v in (spec.get("loadbalancing") or {}).items()))
    except Exception: return None


def items(spec):
    n = norm(spec)
    if n is None: return set()
    return {("r", k, p) for k, v in n[0] for p in v} | {("w", k, w) for k, v in n[1] for w in v} | {("l", k, v) for k, v in n[2]}


def run_task(task):
    fin = os.path.join(D, f"step_1_spec_{task}.jsonl"); fout = os.path.join(ROOT, "results", f"netconfeval_{task}.jsonl")
    R = [json.loads(l) for l in open(fin)]; R = [r for r in R if r["iteration"] == 0]
    done = sum(1 for _ in open(fout)) if os.path.exists(fout) else 0
    with open(fout, "a") as fo:
        for i, r in enumerate(R):
            if i < done: continue
            sents = [s for s in r["human_language"].split("\n") if s.strip()]
            row = dict(i=i, batch_size=r["batch_size"], n_types=r["n_policy_types"], n_sent=len(sents))
            # batch
            t = time.time(); tmpl = BATCH_TRANS if task == "translation" else BATCH_CONF
            txt, st = chat([dict(role="user", content=tmpl.format(desc=r["description"], req=r["human_language"]))],
                           max_tokens=6000 if task == "translation" else 300)
            try: out = extract_json(txt)
            except Exception: out = None
            row["batch_s"] = time.time() - t; row["batch_tok"] = st["completion"]
            # ir
            t = time.time(); irs, ntok = [], 0
            for k, s in enumerate(sents):
                o, st2 = ir_one(s, seed=k); irs.append(o); ntok += st2["completion"]
            row["ir_s"] = time.time() - t; row["ir_tok"] = ntok; row["ir_fail"] = sum(o is None for o in irs)
            if task == "translation":
                exp = json.loads(r["expected"]); E = items(exp)
                for name, spec in (("batch", out), ("ir", merge(irs))):
                    P = items(spec); tp = len(P & E)
                    row[f"{name}_exact"] = norm(spec) == norm(exp)
                    row[f"{name}_prec"] = tp / len(P) if P else 0.0; row[f"{name}_rec"] = tp / len(E) if E else 1.0
            else:
                row["label"] = bool(r["conflict_exist"])
                row["batch_pred"] = bool(out.get("conflict")) if isinstance(out, dict) and "conflict" in out else None
                row["ir_pred"] = conflicts(irs)
            fo.write(json.dumps(row) + "\n"); fo.flush()
            if i % 20 == 0: print(task, i, {k: v for k, v in row.items() if k.endswith(("exact", "pred", "label", "_s"))}, flush=True)


if __name__ == "__main__":
    for t in (sys.argv[1:] or ["translation", "conflict"]): run_task(t)
