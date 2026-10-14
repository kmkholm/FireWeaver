"""Results figures (Figure 2-6) and LaTeX tables from results/.  python fig_results.py"""
import os, json, glob, collections
import numpy as np
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
from matplotlib.patches import Patch

HERE = os.path.dirname(os.path.abspath(__file__)); ROOT = os.path.join(HERE, ".."); RES = os.path.join(ROOT, "results")
FIG = os.path.join(ROOT, "figures"); TAB = os.path.join(ROOT, "paper"); os.makedirs(FIG, exist_ok=True)
plt.rcParams.update({"font.family": "DejaVu Sans", "font.size": 9, "axes.titlesize": 9.5, "axes.labelsize": 9,
                     "axes.spines.top": False, "axes.spines.right": False, "legend.fontsize": 8, "legend.frameon": False,
                     "pdf.fonttype": 42, "savefig.dpi": 400})
C = dict(rules="#9c3d54", ir0="#e09f3e", ir="#1b998b", fw="#7d7d7d", ilp="#1b998b", greedy="#2a6f97", ingress="#e09f3e",
         egress="#9c3d54", none="#7d7d7d", ecmp1="#e09f3e", fireweaver="#1b998b", batch="#9c3d54")
NAMES = dict(rules="Direct rules", ir0="IR zero-shot", ir="FireWeaver", fw="+ self-repair", ilp="FireWeaver ILP", greedy="Greedy first-fit",
             ingress="Ingress-only", egress="Egress-only", fireweaver="FireWeaver", ecmp1="Single-path placement", none="No ACL")


def save(fig, name):
    for ext in ("pdf", "png"): fig.savefig(os.path.join(FIG, f"{name}.{ext}"), bbox_inches="tight")
    plt.close(fig); print("saved", name)


def panel(ax, s): ax.text(-0.13, 1.06, s, transform=ax.transAxes, fontsize=11, fontweight="bold", va="bottom")


# ------------------------------------------------------------------ synthesis
def synthesis():
    R = [json.load(open(f)) for f in sorted(glob.glob(os.path.join(RES, "synth", "*.json")))]
    if not R: return None
    V = ["rules", "ir0", "ir", "fw"]
    fig, ax = plt.subplots(1, 3, figsize=(7.6, 2.6), gridspec_kw=dict(wspace=0.62))
    TL = ["Direct\nrules", "Zero-\nshot IR", "Fire-\nWeaver", "Self-\nrepair"]
    eq = [100 * np.mean([r[v]["eq"] for r in R]) for v in V]
    ax[0].bar(range(4), eq, color=[C[v] for v in V], width=0.65)
    for i, e in enumerate(eq): ax[0].text(i, e + 1.5, f"{e:.0f}", ha="center", fontsize=8)
    ax[0].set_xticks(range(4)); ax[0].set_xticklabels(TL, fontsize=7)
    ax[0].set_ylabel("scenarios equivalent to\nground truth (%)"); ax[0].set_ylim(0, 110); panel(ax[0], "(a)")
    for i, v in enumerate(V):
        y = np.array([100 * r[v]["mismatch"] for r in R]); x = i + np.random.default_rng(i).uniform(-0.18, 0.18, len(y))
        ax[1].scatter(x, np.maximum(y, 1e-3), s=9, color=C[v], alpha=0.75, lw=0)
        ax[1].plot([i - 0.25, i + 0.25], [max(np.median(y), 1e-3)] * 2, color="k", lw=1.2)
    ax[1].set_yscale("log"); ax[1].set_xticks(range(4)); ax[1].set_xticklabels(TL, fontsize=7)
    ax[1].set_ylabel("misclassified probes (%)\n(0 drawn at 10$^{-3}$)"); panel(ax[1], "(b)")
    for v in V:
        t = [r[v]["s"] for r in R]; n = [r["n_intents"] for r in R]
        ax[2].scatter(n, t, s=10, color=C[v], label=NAMES[v], alpha=0.8, lw=0)
    ax[2].set_xlabel("intent sentences"); ax[2].set_ylabel("wall time per scenario (s)"); ax[2].legend(loc="upper left", fontsize=7); panel(ax[2], "(c)")
    save(fig, "Figure2")
    # table
    rows = []
    for v in V:
        rows.append((NAMES[v], 100 * np.mean([r[v]["eq"] for r in R]), 100 * np.mean([r[v]["mismatch"] for r in R]),
                     100 * np.mean([r[v].get("intent_acc", np.nan) for r in R]) if v != "rules" else np.nan,
                     np.mean([r[v]["calls"] for r in R]), np.mean([r[v].get("completion", np.nan) for r in R]) if v != "fw" else np.nan,
                     np.median([r[v]["s"] for r in R])))
    with open(os.path.join(TAB, "tab_synth.tex"), "w") as f:
        f.write("\\begin{tabular}{lcccccc}\n\\toprule\nVariant & Equivalent (\\%) & Mismatch (\\%) & Intent acc. (\\%) & Calls & Gen. tokens & Time (s) \\\\\n\\midrule\n")
        for n, a, b, c, d, e, g in rows:
            f.write(f"{n} & {a:.1f} & {b:.3f} & {'--' if np.isnan(c) else f'{c:.1f}'} & {d:.1f} & {'--' if np.isnan(e) else f'{e:.0f}'} & {g:.0f} \\\\\n")
        f.write("\\bottomrule\n\\end{tabular}\n")
    # per-type accuracy of IR and FireWeaver
    from_types = collections.defaultdict(lambda: [0, 0, 0])
    import sys; sys.path.insert(0, os.path.join(ROOT, "code"))
    from scenario import compile_intents
    from policy import equivalent
    for r in R:
        sc = json.load(open(os.path.join(ROOT, "data", "scenarios", r["id"] + ".json"))); Z = list(sc["zones"])
        for k, gt in enumerate(sc["intents"]):
            for j, key in enumerate(("ir_out", "fw_out")):
                it = r[key][k]
                ok = it is not None and equivalent(compile_intents([it]), compile_intents([gt]), Z)[0]
                from_types[gt["type"]][j] += ok
            from_types[gt["type"]][2] += 1
    return R, rows, dict(from_types)


# ------------------------------------------------------------------ placement
def placement():
    p = os.path.join(RES, "placement_sweep.json")
    if not os.path.exists(p): return None
    R = json.load(open(p)); F = sorted({r["f"] for r in R}); M = ["ilp", "greedy", "ingress", "egress"]
    fig, ax = plt.subplots(1, 3, figsize=(7.4, 2.7), gridspec_kw=dict(wspace=0.62))
    n = len({r["id"] for r in R})
    for m in M:
        y = [100 * sum(r["feasible"] for r in R if r["gran"] == "prefix" and r["method"] == m and r["f"] == f) / n for f in F]
        ax[0].plot(F, y, "-o", ms=3.5, color=C[m], label=NAMES[m])
    for m in ("ilp", "greedy"):
        y = [100 * sum(r["feasible"] for r in R if r["gran"] == "zone" and r["method"] == m and r["f"] == f) / n for f in F]
        ax[0].plot(F, y, "--", lw=1.1, color=C[m], label=NAMES[m] + " (zone blocks)")
    ax[0].set_xscale("log"); ax[0].set_xticks(F); ax[0].set_xticklabels([f"{f:g}" for f in F], fontsize=7)
    ax[0].set_xlabel("capacity factor $f$"); ax[0].set_ylabel("feasible scenarios (%)"); panel(ax[0], "(a)")
    fig.legend(*ax[0].get_legend_handles_labels(), loc="lower center", ncol=3, fontsize=7, bbox_to_anchor=(0.5, -0.2))
    # (b) smallest capacity factor at which each method finds a placement (per scenario); 'never' at the right
    ids = sorted({r["id"] for r in R})
    for j, m in enumerate(M):
        fm = [min([r["f"] for r in R if r["id"] == i and r["gran"] == "prefix" and r["method"] == m and r["feasible"]] or [24.0]) for i in ids]
        xs = np.sort(fm); ys = np.arange(1, len(xs) + 1) / len(xs) * 100
        ax[1].step(xs, ys, where="post", color=C[m], lw=1.6, label=NAMES[m])
    ax[1].set_xscale("log"); ax[1].set_xticks([1.5, 2, 3, 4, 6, 8, 12, 24]); ax[1].set_xticklabels(["1.5", "2", "3", "4", "6", "8", "12", "never"], fontsize=7)
    ax[1].set_xlabel("smallest feasible capacity factor"); ax[1].set_ylabel("scenarios (cumulative %)"); panel(ax[1], "(b)")
    # (c) price of tight capacity: where denied traffic is dropped (0 = ingress), ILP placements
    fs = [f for f in F if any(r["feasible"] for r in R if r["method"] == "ilp" and r["gran"] == "prefix" and r["f"] == f)]
    dpm = [np.mean([r["drop_position"] for r in R if r["method"] == "ilp" and r["gran"] == "prefix" and r["f"] == f and r["feasible"]]) for f in fs]
    ax[2].plot(fs, dpm, "-o", ms=3.5, color=C["ilp"], label="drop position")
    ax2 = ax[2].twinx(); ax2.spines["right"].set_visible(True)
    sv = [np.median([r["solve_s"] for r in R if r["method"] == "ilp" and r["gran"] == "prefix" and r["f"] == f and r["feasible"]]) for f in fs]
    ax2.plot(fs, sv, "--s", ms=3, color="#555555", label="median solve time"); ax2.set_ylabel("ILP solve time (s)", fontsize=8)
    ax[2].set_xscale("log"); ax[2].set_xticks(fs); ax[2].set_xticklabels([f"{f:g}" for f in fs], fontsize=7)
    ax[2].set_xlabel("capacity factor $f$"); ax[2].set_ylabel("mean drop position\n(0 = ingress, 1 = egress)")
    h1, l1 = ax[2].get_legend_handles_labels(); h2, l2 = ax2.get_legend_handles_labels(); ax[2].legend(h1 + h2, l1 + l2, fontsize=6.5, loc="upper right"); panel(ax[2], "(c)")
    dp = dict(zip(fs, dpm)); em = dict(zip(fs, sv))
    from matplotlib.ticker import NullLocator
    for a_ in list(ax) + [ax2]: a_.xaxis.set_minor_locator(NullLocator())
    save(fig, "Figure3")
    return R, dp, em, ids


# ------------------------------------------------------------------ deployment verification
def deploy():
    p = os.path.join(RES, "deploy_verify.json")
    if not os.path.exists(p): return None
    R = [r for r in json.load(open(p)) if r.get("status") == "ok"]
    fig, ax = plt.subplots(1, 2, figsize=(7.0, 2.5), gridspec_kw=dict(wspace=0.4))
    ax[0].scatter([r["rules_total"] for r in R], [r["verify_s"] for r in R], s=12, color=C["ir"], lw=0, alpha=0.8)
    ax[0].set_xscale("log"); ax[0].set_yscale("log")
    from matplotlib.ticker import NullFormatter
    ax[0].xaxis.set_minor_formatter(NullFormatter()); ax[0].set_xlabel("deployed rules (all routers)"); ax[0].set_ylabel("network-wide verification (s)"); panel(ax[0], "(a)")
    kinds = ["swap", "port", "prefix", "ecmp-1"]; lbl = ["rule-order\nswap", "port\noff-by-one", "prefix\ntypo", "single-path\nplacement"]
    net = [100 * np.mean([m["net_detect"] for r in R for m in r["mutations"] if m["kind"] == k and m["injected"]]) for k in kinds]
    loc = [100 * np.mean([m["local_detect"] for r in R for m in r["mutations"] if m["kind"] == k and m["injected"]]) for k in kinds]
    x = np.arange(4); ax[1].bar(x - 0.2, net, 0.38, color=C["ir"], label="network-wide Z3 check")
    ax[1].bar(x + 0.2, loc, 0.38, color=C["ingress"], label="per-device check")
    ax[1].text(3 + 0.2, 1.5, "0", ha="center", fontsize=8)
    ax[1].set_xticks(x); ax[1].set_xticklabels(lbl, fontsize=7.5); ax[1].set_ylabel("faults flagged (%)"); ax[1].set_ylim(0, 115)
    ax[1].legend(fontsize=7, loc="upper left", ncol=2); panel(ax[1], "(b)")
    save(fig, "Figure4")
    return R


# ------------------------------------------------------------------ testbed
def testbed():
    runs = [json.load(open(f)) for f in sorted(glob.glob(os.path.join(ROOT, "emulation", "runs", "*", "result.json")))]
    if not runs: return None
    runs.sort(key=lambda r: r["up"]["n_routers"])
    fig, ax = plt.subplots(1, 2, figsize=(7.2, 2.6), gridspec_kw=dict(wspace=0.35, width_ratios=[1.6, 1]))
    x = np.arange(len(runs)); w = 0.27
    for j, cs in enumerate(("fireweaver", "ecmp1", "none")):
        y = [r[f"conf_{cs}"]["leaks"] for r in runs]
        ax[0].bar(x + (j - 1) * w, np.maximum(y, 0.6), w, color=C[cs], label=NAMES[cs])
        for i, v in enumerate(y):
            if v == 0: ax[0].text(x[i] + (j - 1) * w, 0.75, "0", ha="center", fontsize=6.5)
    ax[0].set_yscale("log"); ax[0].set_xticks(x); ax[0].set_xticklabels([f"{r['id'].split('_')[0]}\n{r['up']['n_routers']} rtr" for r in runs], fontsize=6.5, rotation=40, ha='right')
    ax[0].set_ylabel("leaked probes (delivered\nalthough denied)"); ax[0].legend(fontsize=7, ncol=3, loc="upper left", bbox_to_anchor=(0, 1.13)); panel(ax[0], "(a)")
    ax[1].scatter([r["up"]["n_routers"] for r in runs], [r["up"]["converge_s"] for r in runs], color=C["greedy"], s=16, label="OSPF convergence")
    ax[1].scatter([r["up"]["n_routers"] for r in runs], [r["deploy_fireweaver"]["deploy_s"] for r in runs], color=C["ir"], marker="s", s=16, label="ACL push (parallel)")
    ax[1].set_xlabel("routers"); ax[1].set_ylabel("time (s)"); ax[1].legend(fontsize=7); panel(ax[1], "(b)")
    save(fig, "Figure5")
    return runs


# ------------------------------------------------------------------ NetConfEval
def netconfeval():
    pt, pc = os.path.join(RES, "netconfeval_translation.jsonl"), os.path.join(RES, "netconfeval_conflict.jsonl")
    T = [json.loads(l) for l in open(pt)] if os.path.exists(pt) else []
    Cf = [json.loads(l) for l in open(pc)] if os.path.exists(pc) else []
    if not T: return None
    fig, ax = plt.subplots(1, 3, figsize=(7.6, 2.6), gridspec_kw=dict(wspace=0.75))
    bs = sorted({r["batch_size"] for r in T})
    for v in ("batch", "ir"):
        y = [100 * np.mean([r[f"{v}_exact"] for r in T if r["batch_size"] == b]) for b in bs]
        ax[0].plot(bs, y, "-o", ms=3, color=C["batch"] if v == "batch" else C["ir"], label="whole batch" if v == "batch" else "FireWeaver (per sentence)")
    ax[0].set_xscale("log"); ax[0].set_xlabel("requirements per batch"); ax[0].set_ylabel("exact specification (%)"); ax[0].set_ylim(-5, 115)
    ax[0].legend(fontsize=6.5, loc="upper center", bbox_to_anchor=(0.5, -0.3), ncol=1); panel(ax[0], "(a)")
    if Cf:
        for j, v in enumerate(("batch", "ir")):
            y = [r["label"] for r in Cf]; p = [bool(r[f"{v}_pred"]) for r in Cf]
            cm = np.array([[sum((not a) and (not b) for a, b in zip(y, p)), sum((not a) and b for a, b in zip(y, p))],
                           [sum(a and (not b) for a, b in zip(y, p)), sum(a and b for a, b in zip(y, p))]])
            a = ax[1 + j]; a.imshow(cm, cmap="Greens" if v == "ir" else "Reds", vmin=0, vmax=cm.sum() / 2)
            for (i, k), val in np.ndenumerate(cm): a.text(k, i, str(val), ha="center", va="center", fontsize=9, color="white" if val > cm.sum() / 4 else "black")
            a.set_xticks([0, 1]); a.set_xticklabels(["none", "conflict"], fontsize=7.5); a.set_yticks([0, 1]); a.set_yticklabels(["none", "conflict"], fontsize=7.5)
            a.set_xlabel("predicted"); a.set_ylabel("true"); a.set_title("whole batch" if v == "batch" else "FireWeaver (per sentence)", fontsize=8, pad=8)
            a.spines[:].set_visible(True); a.text(-0.42, 1.12, "(b)" if j == 0 else "(c)", transform=a.transAxes, fontsize=11, fontweight="bold", va="bottom")
    save(fig, "Figure6")
    return T, Cf


if __name__ == "__main__":
    s = synthesis()
    if s: print("synth n", len(s[0]), [(r[0], round(r[1], 1), round(r[3], 1) if r[3] == r[3] else None) for r in s[1]]); print("per type", s[2])
    p = placement()
    d = deploy()
    t = testbed()
    n = netconfeval()
