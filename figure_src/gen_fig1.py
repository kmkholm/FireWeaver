"""Figure 1 (draw.io, stage-flow style of the paper2drawio-v2 skill) - FireWeaver methodology, PORTRAIT layout.
Left column: Stage 1 -> Stage 2 -> Stage 3 -> Stage 4 -> Stage 5 -> Evaluation, strictly top to bottom with an
Output label on every arrow.  Right column: zoom-in detail panels next to the stage they detail (typed IR,
placement program, network-wide verification).  python gen_fig1.py -> figures/Figure1.drawio/.pdf/.png"""
import os, subprocess
from figlib import Fig, FONT

HERE = os.path.dirname(os.path.abspath(__file__)); OUT = os.path.join(HERE, "..", "figures"); os.makedirs(OUT, exist_ok=True)
f = Fig(page_w=1080, page_h=1380, scale=0.6, name="Figure1")      # designed on an 1800 x 2300 canvas
it = lambda s: f"<i>{s}</i>"
RED = "#c0392b"


def T(x, y, w, h, s, fs=17, bold=False, align="center", color="#000000"):
    return f.text(x, y, w, h, s, fs=fs, bold=bold, align=align, color=color)


def A(pts, head=True, dashed=False, sw=1.8, color="#000000"):
    return f.arrow(pts, head=head, dashed=dashed, sw=sw, color=color)


def down(y0, y1, label, left=False):
    A([(560, y0), (560, y1)])
    if left: T(60, y0 + 12, 485, y1 - y0 - 24, "<b>Output:</b> " + label, fs=16, align="right")
    else: T(580, y0 + 12, 520, y1 - y0 - 24, "<b>Output:</b> " + label, fs=16, align="left")


# ===================================================================== LEFT COLUMN: stages
f.stage(10, 10, 1100, 230, "Stage 1: Intent Input", "green")
f.box(35, 80, 330, 130, "Natural-language<br>intents<br>(one sentence each)", "gray", fs=17)
f.box(385, 80, 330, 130, "Zone inventory<br>(zone → router,<br>prefixes)", "gray", fs=17)
f.box(735, 80, 350, 130, "Topology <i>G</i> = (<i>R</i>, <i>E</i>)<br>(Topology Zoo,<br>ClassBench prefixes)", "gray", fs=17)
down(240, 330, it("s") + "<sub>1</sub> … " + it("s") + "<sub><i>n</i></sub> and inventory")

f.stage(10, 330, 1100, 330, "Stage 2: Per-Sentence LLM Translation", "blue")
f.stacked_box(35, 400, 330, 150, "<b>Qwen3-8B</b> (Q4_K_M)<br>llama.cpp · greedy<br>JSON output", "blue", n=3, fs=18)
A([(365, 475), (420, 475)])
f.box(420, 425, 250, 100, "Validator<br>type · zones<br>services", "lightgreen", fs=16)
A([(670, 475), (725, 475)])
f.box(725, 400, 360, 150, "One typed object " + it("τ<sub>i</sub>") + "<br>per sentence<br>(5 types)", "lightblue", fs=18)
A([(545, 525), (545, 600), (200, 600), (200, 550)], color=RED)
T(250, 602, 290, 28, "invalid → re-ask (≤ 2)", fs=15, color=RED)
T(725, 562, 360, 60, "1 call per sentence<br>7 placeholder examples", fs=15)
down(660, 750, it("τ") + "<sub>1</sub> … " + it("τ") + "<sub><i>n</i></sub>")

f.stage(10, 750, 1100, 330, "Stage 3: Compiler and Rule Blocks", "teal")
f.box(35, 820, 330, 130, "Precedence<br>compiler", "teal", fs=19)
A([(365, 885), (420, 885)])
f.box(420, 820, 300, 130, "Zone policy Π<br>(first match,<br>default deny)", "lightteal", fs=17)
A([(720, 885), (775, 885)])
f.stacked_box(775, 820, 310, 130, "Prefix-pair blocks<br>" + it("B") + "<sub><i>p,p</i>′</sub> · cost " + it("c<sub>b</sub>"), "teal", n=3, fs=17)
f.strip(35, 990, n=8, cw=36, ch=34, colors=["#3a7bd5", "#e07a1f", "#2aa198", "#c2185b", "#7b5ea7", "#8d6e3f", "#5f95cc", "#f2b27a"])
T(340, 972, 750, 70, "disjoint in header space · idempotent ·<br>1-entry deny block for deny-only pairs", fs=15, align="left")
down(1080, 1170, "blocks {" + it("B<sub>b</sub>") + ", " + it("c<sub>b</sub>") + "} · paths ℰ(" + it("s, d") + ")")

f.stage(10, 1170, 1100, 330, "Stage 4: Capacity-Aware ECMP Placement", "purple")
f.box(35, 1240, 330, 100, "All equal-cost paths<br>ℰ(" + it("s, d") + ") (up to 28)", "lightblue", fs=17)
f.box(35, 1360, 330, 100, "Router capacity " + it("C<sub>r</sub>") + "<br>(ACL / TCAM entries)", "lightblue", fs=17)
A([(365, 1290), (420, 1290)]); A([(365, 1410), (420, 1410)])
f.stacked_box(420, 1250, 400, 190, "<b>Placement ILP</b><br>" + it("x<sub>br</sub>") + " ∈ {0, 1}<br>SciPy · HiGHS (≤ 30 s)", "purple", n=3, fs=20)
T(850, 1290, 240, 90, "baselines:<br>greedy · ingress<br>egress", fs=15)
down(1500, 1590, "placement " + it("x") + "*", left=True)

f.stage(10, 1590, 1100, 330, "Stage 5: Render and Verify", "orange")
f.box(35, 1660, 320, 100, "Render<br>iptables-restore", "peach", fs=17)
A([(195, 1760), (195, 1785)])
f.box(35, 1785, 320, 100, "Independent parser<br>(no access to blocks)", "lightgreen", fs=16)
A([(355, 1835), (420, 1835)])
f.box(420, 1660, 400, 225, "<b>Network-wide Z3 check</b><br>every (" + it("s, d") + ")<br>and every path π<br>full 5-tuple header", "darkorange", fs=18)
A([(820, 1715), (850, 1715)]); A([(820, 1835), (850, 1835)])
f.box(850, 1670, 240, 90, "unsat →<br>deploy", "green", fs=17)
f.box(850, 1790, 240, 90, "sat → packet<br>witness", "red", fs=17)
A([(780, 1660), (780, 1440)], color=RED)
T(790, 1515, 300, 28, "witness → re-place", fs=15, color=RED, align="left")
down(1920, 2010, "verified router configurations")

f.stage(10, 2010, 1100, 280, "Evaluation: Emulated Testbed (GNS3 VM)", "pink")
f.box(35, 2070, 520, 70, "FRR 10.2.1 routers · OSPF · ECMP", "pink", fs=17)
f.box(575, 2070, 510, 70, "iptables FORWARD per router", "pink", fs=17)
f.box(35, 2155, 520, 70, "Zone hosts (one per zone)", "pink", fs=17)
f.box(575, 2155, 510, 70, "Probes: UDP · TCP-SYN · ICMP", "pink", fs=17)
T(35, 2232, 1050, 46, "conformance · leaks · convergence · push time · update latency", fs=15)

# ===================================================================== RIGHT COLUMN: detail panels
f.stage(1160, 330, 630, 480, "Detail: Typed IR", "lavender")
f.zoom_link((1085, 400), (1160, 330)); f.zoom_link((1085, 550), (1160, 810))
for i, (lab, role) in enumerate([("allow(" + it("s, d, S") + ")", "green"), ("allow_except(" + it("s, d, b, X") + ")", "lightgreen"),
                                 ("block(" + it("s, d") + ")", "red"), ("isolate(" + it("s, A") + ")", "peach"),
                                 ("public(" + it("d, S") + ")", "lavender")]):
    f.box(1185, 395 + 70 * i, 580, 58, lab, role, fs=18, arc=45)
T(1185, 748, 580, 52, "precedence: block ≻ except ≻ allow<br>≻ isolate ≻ public", fs=15)

f.stage(1160, 1040, 630, 520, "Detail: Placement ILP", "lavender")
f.zoom_link((820, 1250), (1160, 1110)); f.zoom_link((820, 1440), (1160, 1480))
f.box(1185, 1105, 580, 62, "min Σ<sub><i>b,r</i></sub> " + it("c<sub>b</sub> x<sub>br</sub>") + " (1 + α " + it("h<sub>br</sub>") + ")", "white", fs=19)
f.box(1185, 1180, 580, 62, "Σ<sub><i>r</i>∈π</sub> " + it("x<sub>br</sub>") + " ≥ 1 &nbsp; ∀ " + it("b") + ", ∀ π ∈ ℰ(" + it("b") + ")", "lightblue", fs=19)
f.box(1185, 1255, 580, 62, "Σ<sub><i>b</i></sub> " + it("c<sub>b</sub> x<sub>br</sub>") + " ≤ " + it("C<sub>r</sub>") + " &nbsp; ∀ " + it("r"), "orange", fs=19)
T(1185, 1318, 580, 30, "α = 0.05 · " + it("h") + " = hop index (early drop)", fs=15)
G = {0: (1250, 1468), 1: (1360, 1410), 2: (1360, 1526), 3: (1520, 1410), 4: (1520, 1526), 5: (1630, 1468)}
for a, b in [(0, 1), (1, 3), (3, 5)]: A([G[a], G[b]], head=False, sw=4, color="#3a7bd5")
for a, b in [(0, 2), (2, 4), (4, 5)]: A([G[a], G[b]], head=False, sw=4, color="#e07a1f", dashed=True)
for r, (x, y) in G.items(): f.circle(x, y, 22, f"R{r}", fs=14)
for (x, y), c in [(G[1], "#c2185b"), (G[2], "#7b5ea7")]: f.box(x - 13, y - 52, 26, 24, "", c, arc=25)
T(1660, 1395, 125, 130, "<span style='color:#3a7bd5'>━</span> π<sub>1</sub><br><span style='color:#e07a1f'>┅</span> π<sub>2</sub><br>■ block", fs=15, align="left")

f.stage(1160, 1600, 630, 690, "Detail: Z3 Verification", "lavender")
f.zoom_link((820, 1660), (1160, 1660)); f.zoom_link((820, 1885), (1160, 1900))
T(1185, 1655, 580, 28, "header " + it("h") + " (bit-vectors)", fs=15, align="left")
x = 1185
for lab, w, c in [("src 32 bit", 190, "#7fa8d8"), ("dst 32 bit", 190, "#f2b27a"), ("proto 8", 95, "#a8d8b0"), ("port 16", 90, "#c9c0d0")]:
    f.box(x, 1688, w, 42, lab, c, fs=13, arc=6); x += w + 5
f.box(1185, 1748, 580, 70, "dev<sub><i>r</i></sub>(" + it("h") + ") = first match of the<br>parsed rules of " + it("r") + ", else forward", "lightblue", fs=17)
f.box(1185, 1832, 580, 62, "deliv<sub>π</sub>(" + it("h") + ") = ∧<sub><i>r</i> ∈ π</sub> dev<sub><i>r</i></sub>(" + it("h") + ")", "yellow", fs=19)
A([(1475, 1894), (1475, 1912)])
f.box(1185, 1912, 580, 112, "<b>SAT?</b><br>src ∈ " + it("P") + "(" + it("s") + ") ∧ dst ∈ " + it("P") + "(" + it("d") + ")<br>∧ deliv<sub>π</sub>(" + it("h") + ") ≠ Π(" + it("s, d, h") + ")", "orange", fs=18)
A([(1330, 2024), (1330, 2045)]); A([(1625, 2024), (1625, 2045)])
f.box(1185, 2045, 285, 100, "unsat ∀ (" + it("s, d") + "), π<br>⇒ deployment ≡ Π", "green", fs=16)
f.box(1480, 2045, 285, 100, "sat ⇒ packet<br>witness + path π", "red", fs=16)
T(1185, 2160, 580, 110, "one query per zone pair and per equal-cost path;<br>prefix membership as masked equality", fs=15)

path = os.path.join(OUT, "Figure1.drawio"); f.save(path, name="Figure1")
exe = r"C:\Program Files\draw.io\draw.io.exe"
if os.path.exists(exe):
    for fmt in ("png", "pdf"):
        subprocess.run([exe, "-x", "-f", fmt, "-s", "3" if fmt == "png" else "1", "-b", "10", "-o", os.path.join(OUT, f"Figure1.{fmt}"), path], check=False, timeout=180)
    print("exported png/pdf")
