# FireWeaver

LLM-driven network-wide firewall policy synthesis with header-space verification and capacity-aware rule placement,
validated in an emulated multi-router testbed.

Natural-language security intents are translated one sentence at a time into typed objects by a local LLM
(Qwen3-8B Q4_K_M via llama.cpp), compiled deterministically into a zone-level first-match policy, split into
disjoint prefix-pair rule blocks, placed on routers by an integer linear program under per-router capacity so that
every equal-cost (ECMP) path is covered, rendered to `iptables-restore` files, and verified network-wide with Z3
over source/destination address, protocol and port on every equal-cost path. The deployment runs on FRR routers
(OSPF, ECMP) with iptables in an emulated testbed inside the GNS3 VM.

## Layout
| Path | Content |
|---|---|
| `code/scenario.py` | FireWeaver-Bench generator (Topology Zoo + ClassBench prefixes, 5 intent types, 3 phrasings) |
| `code/llm.py` | LLM front end (typed IR per sentence, validator, direct-rules ablation) |
| `code/policy.py` | zone policy semantics, Z3 equivalence, blocks |
| `code/placement.py` | capacity-aware ILP (SciPy/HiGHS) and greedy / ingress / egress baselines |
| `code/netverify.py` | iptables rendering, independent parser, network-wide Z3 verification, fault injection |
| `code/verify_repair.py` | probe self-check and conservative repair (evaluated variant, not used by FireWeaver) |
| `code/eval_*.py` | experiments: synthesis, placement sweep, deployment verification, NetConfEval, incremental update |
| `emulation/testbed.py` | testbed driver run on the GNS3 VM (FRR 10.2.1 + iptables containers, zone namespaces, probes) |
| `emulation/emu_run.py`, `code/emu_prepare.py` | per-scenario testbed runs |
| `data/scenarios/` | the 60 FireWeaver-Bench scenarios (intents, natural language, ground truth, zones) |
| `results/` | all result files used in the paper |
| `figure_src/`, `figures/` | figure generators and figures |

## Data sources (redistributed unchanged, with attribution)
* Internet Topology Zoo, Knight et al., IEEE JSAC 2011: not redistributed; the scenarios store the links they use. To regenerate the scenarios, clone the mirror: `git clone https://github.com/sk2/topologyzoo data/topologyzoo`
* ClassBench seed filters, Taylor and Turner, IEEE/ACM ToN 2007 (1k sets): `data/classbench/1k_1/`
* NetConfEval tasks (`NetConfEval/NetConfEval` on Hugging Face, MIT): `data/netconfeval/`

## Reproduce
```
pip install z3-solver scipy networkx numpy matplotlib
# LLM: llama-server -m Qwen3-8B-Q4_K_M.gguf -ngl 99 -c 16384 --port 8088 --jinja
cd code
python scenario.py 60          # regenerates data/scenarios (identical output)
python eval_synthesis.py 60    # translation variants
python eval_placement.py 60    # capacity sweep
python eval_deploy.py 60       # rendering + network-wide verification + fault injection
python eval_netconfeval.py     # NetConfEval translation and conflict detection
python emu_prepare.py <scenario> ; python ../emulation/emu_run.py <scenario>   # testbed (GNS3 VM, Docker)
```
The testbed image is `FROM quay.io/frrouting/frr:10.2.1` plus `apk add iptables tcpdump`.
