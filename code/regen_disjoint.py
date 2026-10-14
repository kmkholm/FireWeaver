import os, glob, json, numpy as np
import scenario as S
prof = S.classbench_profile(glob.glob(os.path.join(S.DATA, "classbench", "1k_1", "*.rules")))
topos = S.load_topologies(); names = sorted(topos); rng = np.random.default_rng(2026)
same = changed = 0; new = {}
for i in range(60):
    t = names[rng.integers(len(names))]; nz = int(rng.choice([6, 10, 16])); ni = int(rng.choice([8, 16, 32]))
    sc = S.make(1000 + i, t, topos[t], nz, ni, prof)
    old = json.load(open(os.path.join(S.DATA, "scenarios", sc["id"] + ".json")))
    sc2 = json.loads(json.dumps(sc))
    assert sc2["nl"] == old["nl"] and sc2["gt"] == old["gt"] and sc2["intents"] == old["intents"], sc["id"]
    if sc2["zones"] == old["zones"]: same += 1
    else: changed += 1; print("changed", sc["id"]); new[sc["id"]] = sc2
print("identical", same, "changed", changed)
for k, sc in new.items(): json.dump(sc, open(os.path.join(S.DATA, "scenarios", k + ".json"), "w"), indent=1)
