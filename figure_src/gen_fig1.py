"""Figure 1 (draw.io, stage-flow style of the paper2drawio-v2 skill) - FireWeaver methodology.
Row 1: Stage 1 inputs -> Stage 2 per-sentence LLM translation -> Stage 3 compiler + rule blocks
Row 2: Stage 4 capacity-aware ECMP placement -> Stage 5 render + network-wide verification -> testbed evaluation
Row 3: zoom-in detail panels: placement ILP (equations + toy graph) and network-wide Z3 check (equations).
Short labels only; numbers copied from the paper.   python gen_fig1.py -> figures/Figure1.drawio/.pdf/.png"""
import os, subprocess
from figlib import Fig, FONT

HERE = os.path.dirname(os.path.abspath(__file__)); OUT = os.path.join(HERE, "..", "figures"); os.makedirs(OUT, exist_ok=True)
f = Fig(page_w=1540, page_h=800, scale=0.6, name="Figure1")      # designed on a 2560 x 1300 canvas
it = lambda s: f"<i>{s}</i>"


def T(x, y, w, h, s, fs=17, bold=False, align="center", color="#000000"):
    return f.text(x, y, w, h, s, fs=fs, bold=bold, align=align, color=color)


def A(pts, head=True, dashed=False, sw=1.8, color="#000000"):
    return f.arrow(pts, head=head, dashed=dashed, sw=sw, color=color)


def pill(x, y, w, h, s, role, fs=17):
    return f.box(x, y, w, h, s, role, fs=fs, arc=45)


# ===================================================================== ROW 1
# ---- Stage 1: inputs
f.stage(8, 10, 540, 390, "Stage 1: Intent Input", "green")
f.box(30, 80, 495, 92, "Natural-language intents<br>(one sentence per intent)", "gray", fs=18)
f.box(30, 190, 495, 86, "Zone inventory<br>(zone → router, prefixes)", "gray", fs=18)
f.box(30, 294, 495, 86, "Topology <i>G</i> = (<i>R</i>, <i>E</i>)<br>(Topology Zoo, ClassBench prefixes)", "gray", fs=18)
A([(548, 205), (688, 205)])
T(552, 112, 132, 86, "<b>Output:</b><br>" + it("s") + "<sub>1</sub> … " + it("s") + "<sub><i>n</i></sub>", fs=17)

# ---- Stage 2: per-sentence LLM translation
f.stage(688, 10, 872, 390, "Stage 2: Per-Sentence LLM Translation", "blue")
f.stacked_box(712, 92, 300, 128, "<b>Qwen3-8B</b> (Q4_K_M)<br>llama.cpp · greedy<br>JSON output", "blue", n=3, fs=18)
A([(1012, 156), (1045, 156)])
f.box(1045, 112, 222, 90, "Validator<br>type · zones · services", "lightgreen", fs=15)
A([(1152, 202), (1152, 250), (862, 250), (862, 222)], color="#c0392b")
T(880, 252, 270, 30, "invalid → re-ask (≤ 2)", fs=15, color="#c0392b")
T(712, 300, 540, 70, "1 call per sentence<br>7 placeholder examples", fs=16)
A([(1267, 157), (1278, 157), (1278, 216), (1290, 216)])
T(1290, 68, 255, 28, "<b>Typed IR</b>", fs=16)
for i, (lab, role) in enumerate([("allow(" + it("s, d, S") + ")", "green"), ("allow_except(" + it("s, d, b, X") + ")", "lightgreen"),
                                 ("block(" + it("s, d") + ")", "red"), ("isolate(" + it("s, A") + ")", "peach"),
                                 ("public(" + it("d, S") + ")", "lavender")]):
    pill(1290, 98 + 58 * i, 258, 48, lab, role, fs=15)
A([(1560, 205), (1700, 205)])
T(1564, 112, 132, 86, "<b>Output:</b><br>" + it("τ") + "<sub>1</sub> … " + it("τ") + "<sub><i>n</i></sub>", fs=17)

# ---- Stage 3: compiler + blocks
f.stage(1700, 10, 852, 390, "Stage 3: Compiler and Rule Blocks", "teal")
f.box(1722, 88, 330, 112, "Precedence compiler<br>block ≻ except ≻ allow<br>≻ isolate ≻ public", "teal", fs=17)
A([(2052, 144), (2092, 144)])
f.box(2092, 88, 440, 112, "Zone policy Π<br>(first match, default deny)", "lightteal", fs=18)
A([(2312, 200), (2312, 250)])
f.stacked_box(2092, 252, 440, 118, "Prefix-pair blocks " + it("B") + "<sub><i>p,p</i>′</sub><br>disjoint · idempotent · cost " + it("c<sub>b</sub>"), "teal", n=3, fs=17)
T(1722, 240, 330, 34, "one block per prefix pair", fs=15)
f.strip(1745, 286, n=8, cw=36, ch=34, colors=["#3a7bd5", "#e07a1f", "#2aa198", "#c2185b", "#7b5ea7", "#8d6e3f", "#5f95cc", "#f2b27a"])
A([(2034, 303), (2092, 303)])
T(1722, 330, 340, 50, "+ 1-entry deny block for<br>deny-only pairs", fs=15)

# ---- row 1 -> row 2
A([(2312, 370), (2312, 432), (400, 432), (400, 470)])
T(1000, 402, 1100, 30, "<b>Output:</b> blocks {" + it("B<sub>b</sub>") + ", " + it("c<sub>b</sub>") + "} · all equal-cost paths ℰ(" + it("s, d") + ")", fs=17)

# ===================================================================== ROW 2
# ---- Stage 4: placement
f.stage(8, 470, 892, 390, "Stage 4: ECMP-Aware Placement", "purple")
f.box(30, 545, 390, 90, "All equal-cost paths ℰ(" + it("s, d") + ")<br>(up to 28 per pair)", "lightblue", fs=17)
f.box(30, 655, 390, 90, "Router capacity " + it("C<sub>r</sub>") + "<br>(ACL / TCAM entries)", "lightblue", fs=17)
A([(420, 590), (465, 590)]); A([(420, 700), (465, 700)])
f.stacked_box(465, 548, 410, 190, "<b>Placement ILP</b><br>" + it("x<sub>br</sub>") + " ∈ {0, 1}<br>SciPy · HiGHS (≤ 30 s)", "purple", n=3, fs=20)
T(465, 770, 410, 40, "baselines: greedy · ingress · egress", fs=15)
A([(875, 640), (955, 640), (955, 585), (1035, 585)])
T(902, 650, 104, 50, "<b>Output:</b><br>" + it("x") + "*", fs=15)

# ---- Stage 5: render + verification
f.stage(1010, 470, 752, 390, "Stage 5: Render and Verify", "orange")
f.box(1035, 545, 330, 80, "Render<br>iptables-restore per router", "peach", fs=17)
A([(1200, 625), (1200, 658)])
f.box(1035, 658, 330, 76, "Independent parser<br>(no access to blocks)", "lightgreen", fs=17)
A([(1365, 696), (1400, 696)])
f.box(1400, 545, 340, 190, "<b>Network-wide Z3</b><br>per (" + it("s, d") + ") and path π<br>full 5-tuple header<br><br>unsat → deploy<br>sat → witness", "darkorange", fs=17)
A([(1570, 545), (1570, 450), (760, 450), (760, 540)], color="#c0392b")
T(1300, 451, 260, 20, "witness → re-place", fs=14, color="#c0392b", align="right")
A([(1740, 640), (1842, 640)])
T(1762, 584, 80, 50, "<b>Output:</b><br>verified", fs=14)

# ---- Testbed evaluation
f.stage(1842, 470, 710, 390, "Evaluation: Emulated Testbed", "pink")
f.box(1862, 545, 325, 90, "FRR 10.2.1 routers<br>OSPF · ECMP (L4 hash)", "pink", fs=17)
f.box(2207, 545, 325, 90, "iptables FORWARD<br>per router", "pink", fs=17)
f.box(1862, 655, 325, 80, "Zone hosts<br>(network namespaces)", "pink", fs=17)
f.box(2207, 655, 325, 80, "Probes<br>UDP · TCP-SYN · ICMP", "pink", fs=17)
f.box(1862, 755, 670, 80, "Conformance · leaks · convergence<br>push time · update latency", "white", fs=16)

# ===================================================================== ROW 3: detail panels
f.stage(8, 900, 1012, 392, "Detailed Placement Program", "lavender")
f.zoom_link((465, 738), (8, 900)); f.zoom_link((875, 738), (1020, 900))
f.box(30, 965, 590, 70, "min Σ<sub><i>b,r</i></sub> " + it("c<sub>b</sub> x<sub>br</sub>") + " (1 + α " + it("h<sub>br</sub>") + ")", "white", fs=20)
f.box(30, 1048, 590, 70, "Σ<sub><i>r</i>∈π</sub> " + it("x<sub>br</sub>") + " ≥ 1 &nbsp; ∀ " + it("b") + ", ∀ π ∈ ℰ(" + it("b") + ")", "lightblue", fs=20)
f.box(30, 1131, 590, 70, "Σ<sub><i>b</i></sub> " + it("c<sub>b</sub> x<sub>br</sub>") + " ≤ " + it("C<sub>r</sub>") + " &nbsp; ∀ " + it("r"), "orange", fs=20)
T(30, 1212, 590, 60, "cover every equal-cost path · respect capacity<br>α = 0.05 · " + it("h") + " = hop index (early drop)", fs=15)
G = {0: (680, 1110), 1: (790, 1020), 2: (790, 1200), 3: (900, 1020), 4: (900, 1200), 5: (990, 1110)}
for a, b in [(0, 1), (1, 3), (3, 5)]: A([G[a], G[b]], head=False, sw=4, color="#3a7bd5")
for a, b in [(0, 2), (2, 4), (4, 5)]: A([G[a], G[b]], head=False, sw=4, color="#e07a1f", dashed=True)
for r, (x, y) in G.items(): f.circle(x, y, 24, f"R{r}", fs=15)
for (x, y), c in [(G[0], "#2aa198"), (G[1], "#c2185b"), (G[2], "#7b5ea7")]:
    f.box(x - 14, y - 58, 28, 26, "", c, arc=25)
T(640, 1258, 370, 30, "<span style='color:#3a7bd5'>━</span> π<sub>1</sub> &nbsp; <span style='color:#e07a1f'>┅</span> π<sub>2</sub> &nbsp; ■ block", fs=15)

f.stage(1050, 900, 1502, 392, "Detailed Network-Wide Verification", "lavender")
f.zoom_link((1400, 735), (1050, 900)); f.zoom_link((1740, 735), (1820, 900))
T(1075, 958, 400, 30, "header " + it("h") + " (bit-vectors)", fs=16, align="left")
x = 1075
for lab, w, c in [("src (32 bit)", 250, "#7fa8d8"), ("dst (32 bit)", 250, "#f2b27a"), ("proto (8)", 118, "#a8d8b0"), ("port (16)", 140, "#c9c0d0")]:
    f.box(x, 992, w, 46, lab, c, fs=14, arc=6); x += w + 6
f.box(1075, 1060, 780, 66, "dev<sub><i>r</i></sub>(" + it("h") + ") = first match of parsed rules of " + it("r") + ", else forward", "lightblue", fs=18)
f.box(1075, 1140, 780, 66, "deliv<sub>π</sub>(" + it("h") + ") = ∧<sub><i>r</i> ∈ π</sub> dev<sub><i>r</i></sub>(" + it("h") + ")", "yellow", fs=19)
f.box(1890, 960, 640, 120, "<b>SAT?</b><br>src ∈ " + it("P") + "(" + it("s") + ") ∧ dst ∈ " + it("P") + "(" + it("d") + ")<br>∧ deliv<sub>π</sub>(" + it("h") + ") ≠ Π(" + it("s, d, h") + ")", "orange", fs=19)
A([(1855, 1173), (1872, 1173), (1872, 1020), (1890, 1020)])
f.box(1890, 1100, 310, 106, "unsat ∀ (" + it("s, d") + "), π<br>⇒ deployment ≡ Π", "green", fs=18)
f.box(2220, 1100, 310, 106, "sat ⇒ witness<br>packet + path π", "red", fs=18)
A([(2045, 1080), (2045, 1100)]); A([(2375, 1080), (2375, 1100)])
T(1075, 1222, 1455, 50, "per zone pair and per equal-cost path · prefix membership as masked equality", fs=15)

path = os.path.join(OUT, "Figure1.drawio"); f.save(path, name="Figure1")
exe = r"C:\Program Files\draw.io\draw.io.exe"
if os.path.exists(exe):
    for fmt in ("png", "pdf"):
        subprocess.run([exe, "-x", "-f", fmt, "-s", "3" if fmt == "png" else "1", "-b", "10", "-o", os.path.join(OUT, f"Figure1.{fmt}"), path], check=False, timeout=180)
    print("exported png/pdf")
