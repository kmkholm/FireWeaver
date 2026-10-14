"""Stage-1/2 evaluation on FireWeaver-Bench (60 scenarios), fixed grid, resumable (one JSON per scenario).

Variants (all with the same local Qwen3-8B Q4_K_M, greedy decoding):
  rules  : the LLM writes the ordered first-match rule list directly (no IR)              -- ablation
  ir0    : per-intent typed IR, zero-shot prompt (no type-selection rules / examples)   -- ablation
  ir     : per-intent typed IR, full prompt (type-selection rules + 7 placeholder examples)
  fw     : ir + probe-based verification and conservative counterexample-guided repair  -- FireWeaver
Metrics per variant: exact header-space equivalence with the ground truth (Z3), mismatch fraction of the header
space, intent-level accuracy (single-intent header-space equivalence), #rules, LLM calls, tokens, wall time.
usage: python eval_synthesis.py [n_scenarios]
"""
import os, sys, json, glob, time
from scenario import SERVICES, compile_intents
from policy import rule_from_dict, equivalent, mismatch_fraction
from llm import translate_ir, translate_rules
from verify_repair import probes_for, confirmed_oracle, disagreements, repair

ROOT = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..")
OUT = os.path.join(ROOT, "results", "synth"); os.makedirs(OUT, exist_ok=True)


def tok(stats): return dict(calls=len(stats), prompt=sum(s["prompt"] for s in stats), completion=sum(s["completion"] for s in stats))


def intent_ok(it, gt_it, zones):
    if it is None: return False
    try: return equivalent(compile_intents([it]), compile_intents([gt_it]), zones)[0]
    except Exception: return False


def score(policy, gt, zones):
    try:
        eq, _ = equivalent(policy, gt, zones); mm = mismatch_fraction(policy, gt, zones)
    except Exception as e:
        return dict(eq=False, mismatch=1.0, err=str(e)[:200])
    return dict(eq=bool(eq), mismatch=float(mm), n_rules=len(policy))


def run(sc):
    Z = list(sc["zones"]); gt = [rule_from_dict(r) for r in sc["gt"]]; res = dict(id=sc["id"], n_intents=len(sc["nl"]),
                                                                                 n_gt_rules=len(gt), n_zones=len(Z))
    # rules (direct)
    t = time.time(); rl, st, f = translate_rules(sc, SERVICES)
    try: pol = [rule_from_dict(r) for r in rl]
    except Exception: pol = []
    res["rules"] = dict(score(pol, gt, Z), fail=f, s=time.time() - t, **tok(st))
    # ir0
    t = time.time(); ir0, st, f = translate_ir(sc, SERVICES, fewshot=False)
    res["ir0"] = dict(score(compile_intents([i for i in ir0 if i]), gt, Z), fail=f, s=time.time() - t, **tok(st),
                      intent_acc=sum(intent_ok(a, b, Z) for a, b in zip(ir0, sc["intents"])) / len(sc["nl"]))
    # ir
    t = time.time(); ir, st, f = translate_ir(sc, SERVICES, fewshot=True); t_ir = time.time() - t; st_ir = tok(st)
    res["ir"] = dict(score(compile_intents([i for i in ir if i]), gt, Z), fail=f, s=t_ir, **st_ir,
                     intent_acc=sum(intent_ok(a, b, Z) for a, b in zip(ir, sc["intents"])) / len(sc["nl"]))
    # fw = ir + verify/repair
    t = time.time(); fixed, extra, flagged, accepted, log = [], 0, 0, 0, []
    for k, (sent, it) in enumerate(zip(sc["nl"], ir)):
        if it is None: fixed.append(None); continue
        orc, nc = confirmed_oracle(sent, probes_for(sent, Z), it, seed=k); extra += nc
        if disagreements(it, orc):
            flagged += 1; new, info = repair(sc, sent, it, orc, seed=k); extra += info["calls"]
            accepted += int(info["accepted"]); log.append(dict(k=k, was_ok=intent_ok(it, sc["intents"][k], Z),
                                                               now_ok=intent_ok(new, sc["intents"][k], Z), **info))
            it = new
        fixed.append(it)
    res["fw"] = dict(score(compile_intents([i for i in fixed if i]), gt, Z), fail=res["ir"]["fail"], s=t_ir + time.time() - t,
                     verify_s=time.time() - t, calls=st_ir["calls"] + extra, verify_calls=extra, flagged=flagged,
                     accepted=accepted, repairs=log,
                     intent_acc=sum(intent_ok(a, b, Z) for a, b in zip(fixed, sc["intents"])) / len(sc["nl"]))
    res["ir_out"] = ir; res["fw_out"] = fixed
    return res


def main(n):
    fs = [f for f in sorted(glob.glob(os.path.join(ROOT, "data", "scenarios", "*.json"))) if "_index" not in f][:n]
    for f in fs:
        sc = json.load(open(f)); o = os.path.join(OUT, sc["id"] + ".json")
        if os.path.exists(o): continue
        t = time.time(); r = run(sc); r["wall_s"] = time.time() - t
        json.dump(r, open(o, "w"), indent=1)
        print(f"{sc['id']:28s} n={r['n_intents']:2d} | " + " | ".join(
            f"{v} eq={int(r[v]['eq'])} mm={r[v]['mismatch']:.4f}" + (f" ia={r[v]['intent_acc']:.2f}" if 'intent_acc' in r[v] else "")
            for v in ("rules", "ir0", "ir", "fw")) + f" | flag {r['fw']['flagged']} acc {r['fw']['accepted']} | {r['wall_s']:.0f}s", flush=True)


if __name__ == "__main__":
    main(int(sys.argv[1]) if len(sys.argv) > 1 else 60)
