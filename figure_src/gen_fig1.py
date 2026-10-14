"""Figure 1 (draw.io) - FireWeaver overview, original layout (not the stage-band template):
an L-shaped "loom": the intent plane runs left->right along the top, the network plane (placement on a router graph
with two ECMP paths and capacity bars) fills the right, the deployment/verification plane closes the loop along the
bottom, and two feedback threads (red, dashed) return counterexamples to the LLM repair and to the placement.
python gen_fig1.py  -> figures/Figure1.drawio/.pdf/.png"""
import os, subprocess
from figlib import Fig, FONT

HERE = os.path.dirname(os.path.abspath(__file__)); OUT = os.path.join(HERE, "..", "figures"); os.makedirs(OUT, exist_ok=True)
f = Fig(page_w=1880, page_h=1000, scale=0.76, name="Figure1")

INK, GREY, RED = "#1b1b1b", "#5f6b7a", "#c0392b"
NAVY, NAVY_L = "#1f3b73", "#e3eaf7"
TEAL, TEAL_L = "#0f766e", "#dff3f1"
AMB, AMB_L = "#b45309", "#fdf0dc"
PLUM, PLUM_L = "#6b3fa0", "#efe7f8"
OK, OK_L, NO, NO_L, UN_L = "#2e7d32", "#dcefdc", "#b71c1c", "#f8dcdc", "#eeeeee"
BLK = ["#3a7bd5", "#e07a1f", "#2aa198", "#c2185b", "#7b5ea7", "#8d6e3f"]
it = lambda s: f"<i>{s}</i>"


def box(x, y, w, h, label, fill="#ffffff", stroke=INK, fs=14, bold=False, arc=10, dashed=False, sw=1.2, color=INK, align="center"):
    st = (f"rounded=1;arcSize={arc};whiteSpace=wrap;html=1;fillColor={fill};strokeColor={stroke};strokeWidth={sw};"
          f"fontSize={fs};fontColor={color};align={align};spacingLeft=6;spacingRight=6;" + FONT)
    if bold: st += "fontStyle=1;"
    if dashed: st += "dashed=1;"
    return f.vertex(label, st, x, y, w, h)


def plane(x, y, w, h, num, title, col, fill):
    f.vertex("", f"rounded=1;arcSize=3;whiteSpace=wrap;html=1;fillColor={fill};strokeColor={col};strokeWidth=2;" + FONT, x, y, w, h)
    f.vertex(num, f"ellipse;whiteSpace=wrap;html=1;fillColor={col};strokeColor=none;fontColor=#ffffff;fontSize=20;fontStyle=1;" + FONT,
             x + 14, y + 12, 38, 38)
    f.text(x + 60, y + 10, w - 80, 42, title, fs=20, bold=True, align="left", color=col)


def A(pts, color=INK, sw=1.6, dashed=False, head=True):
    f.arrow(pts, head=head, dashed=dashed, sw=sw, color=color)


def lab(x, y, w, h, s, fs=13, align="center", color=INK, bold=False):
    f.text(x, y, w, h, s, fs=fs, align=align, color=color, bold=bold)


def circ(cx, cy, r, label, fill="#ffffff", stroke=INK, fs=13, sw=1.4):
    return f.vertex(label, f"ellipse;whiteSpace=wrap;html=1;fillColor={fill};strokeColor={stroke};strokeWidth={sw};fontSize={fs};" + FONT,
                    cx - r, cy - r, 2 * r, 2 * r)


def line(p, q, color="#9aa5b1", sw=2.0, dashed=False):
    f.arrow([p, q], head=False, sw=sw, color=color, dashed=dashed)


# =====================================================================================================================
# (1) INTENT PLANE  (top, full width up to the network plane)
plane(10, 10, 1470, 470, "1", "Intent plane: one typed object per sentence, compiled deterministically", NAVY, NAVY_L)
# NL intents (stacked "documents")
for k in range(3):
    f.vertex("", f"shape=document;whiteSpace=wrap;html=1;boundedLbl=1;size=0.08;fillColor=#ffffff;strokeColor={GREY};" + FONT,
             40 + 10 * k, 80 + 10 * k, 330, 300)
box(70, 104, 300, 262,
    "<b>Natural-language intents</b><br><br><div style='text-align:left'>"
    "• finance may reach database over PostgreSQL (TCP 5432).<br>"
    "• dev-lab may use any TCP port towards ops, except Telnet (TCP 23), which must be blocked.<br>"
    "• cameras is isolated: it may only reach nvr on RTSP (TCP 554), and nothing else.<br>"
    "• guest-wifi must never reach finance, regardless of any other rule.</div>",
    "#ffffff", "none", fs=11, align="center")
lab(30, 405, 360, 50, "zone inventory: zone → router, prefixes<br>(Topology Zoo graph, ClassBench prefixes)", fs=12, color=GREY)
A([(392, 230), (440, 230)], NAVY, 2.2)
# LLM
f.vertex("<b>Qwen3-8B</b><br>(local, llama.cpp,<br>greedy, JSON)", "shape=hexagon;perimeter=hexagonPerimeter2;whiteSpace=wrap;html=1;size=0.18;"
         f"fillColor={NAVY};strokeColor={NAVY};fontColor=#ffffff;fontSize=14;" + FONT, 445, 170, 190, 120)
lab(425, 96, 230, 66, "type-selection rules +<br>7 placeholder examples;<br>one call per sentence", fs=12, color=GREY)
A([(640, 230), (690, 230)], NAVY, 2.2)
# typed IR chips
chips = [("allow(" + it("s, d, S") + ")", OK_L, OK), ("allow_except(" + it("s, d, b, E") + ")", "#e8f0dc", "#558b2f"),
         ("block(" + it("s, d") + ")", NO_L, NO), ("isolate(" + it("s, A") + ")", AMB_L, AMB), ("public(" + it("d, S") + ")", PLUM_L, PLUM)]
lab(660, 72, 300, 30, "<b>typed IR</b> (one per sentence)", fs=14, color=NAVY)
for i, (t, fc, sc) in enumerate(chips):
    box(695, 108 + 56 * i, 240, 44, t, fc, sc, fs=13, arc=40)
A([(945, 230), (990, 230)], NAVY, 2.2)
box(995, 160, 175, 140, "<b>Deterministic compiler</b><br><span style='font-size:12px'>precedence:<br>block ≻ except ≻ allow<br>≻ isolate ≻ public</span>",
    "#ffffff", NAVY, fs=14)
A([(1175, 230), (1215, 230)], NAVY, 2.2)
# zone policy table
lab(1195, 72, 280, 30, "<b>zone policy</b> Π (first match)", fs=14, color=NAVY)
rows = [("guest", "fin", "*", "deny", NO), ("dev", "ops", "tcp/23", "deny", NO), ("fin", "db", "tcp/5432", "permit", OK),
        ("dev", "ops", "tcp/*", "permit", OK), ("cam", "nvr", "tcp/554", "permit", OK), ("cam", "*", "*", "deny", NO)]
for i, (s, d, p, a, c) in enumerate(rows):
    y = 108 + 40 * i
    box(1195, y, 222, 34, f"<span style='font-family:Consolas'>{s} → {d} {p}</span>", "#ffffff", "#b0bccd", fs=11, arc=6, align="left")
    box(1418, y + 5, 42, 24, a[0].upper(), c, c, fs=11, arc=30, color="#ffffff", bold=True)
lab(1195, 352, 270, 26, "implicit default deny between zones", fs=12, color=GREY)

# (2) deterministic validator panel inside the intent plane
box(430, 384, 1030, 84, "", "#ffffff", NAVY, dashed=True, arc=6)
lab(440, 386, 1010, 24, "<b>deterministic validator</b> (no second LLM opinion): every object is checked before compilation", fs=12, color=NAVY, align="left")
for j, (t, c) in enumerate([("type ∈ 5 types", OK_L), ("zones ∈ inventory", OK_L), ("services ∈ catalogue", OK_L), ("fields complete", OK_L)]):
    box(445 + 172 * j, 414, 160, 40, t, c, OK, fs=12, arc=30)
lab(1135, 410, 320, 50, "on failure: error message back to the model, re-ask ≤ 2", fs=12, align="left", color=GREY)

# =====================================================================================================================
# (2) BLOCKS  (left of the bottom half)
plane(10, 500, 420, 760, "2", "Disjoint rule blocks", TEAL, TEAL_L)
lab(30, 560, 380, 60, "Π restricted to one (source prefix, destination prefix) pair + explicit trailing deny", fs=13, align="left")
for k in range(6):
    y = 630 + 70 * k
    box(40, y, 54, 54, it("b") + f"<sub>{k + 1}</sub>", BLK[k], BLK[k], fs=15, color="#ffffff", bold=True, arc=12)
    lab(104, y, 300, 54, ["10.0.16.0/20 → 10.0.66.0/25 : 3 rules", "10.0.16.0/20 → 10.0.32.0/21 : 1 rule (deny)", "10.0.4.0/22 → 10.0.66.0/25 : 2 rules",
                          "10.0.8.0/22 → 10.0.48.0/20 : 4 rules", "10.0.64.0/26 → 10.0.4.0/22 : 1 rule", "10.0.72.0/24 → 10.0.8.0/22 : 2 rules"][k], fs=12, align="left")
lab(30, 1062, 390, 180, "blocks never overlap in header space and are idempotent ⇒ a block may sit on <b>any</b> router of the pair's paths, "
    "duplicates are harmless; cost " + it("c<sub>b</sub>") + " = #entries", fs=13, align="left", color=TEAL)
A([(220, 482), (220, 500)], TEAL, 2.0)

# =====================================================================================================================
# (3) NETWORK PLANE: capacity-aware placement on the router graph
plane(450, 500, 1030, 430, "3", "Capacity-aware placement over all ECMP paths (ILP)", AMB, AMB_L)
R = {0: (520, 735), 1: (640, 640), 2: (640, 830), 3: (780, 640), 4: (780, 830), 5: (920, 735), 6: (1040, 650), 7: (1040, 830)}
E = [(0, 1), (0, 2), (1, 3), (2, 4), (3, 5), (4, 5), (5, 6), (5, 7), (6, 7), (1, 2)]
for a, b in E: line(R[a], R[b])
line(R[0], R[1], "#3a7bd5", 5); line(R[1], R[3], "#3a7bd5", 5); line(R[3], R[5], "#3a7bd5", 5)
line(R[0], R[2], "#e07a1f", 5, dashed=True); line(R[2], R[4], "#e07a1f", 5, dashed=True); line(R[4], R[5], "#e07a1f", 5, dashed=True)
for r, (x, y) in R.items(): circ(x, y, 26, f"R{r}", "#ffffff", INK, 13, 1.8)
# placed blocks as tiles + capacity bars
tiles = {1: [0, 3], 2: [0], 0: [2, 4], 5: [1], 6: [5], 7: [3]}
for r, bs in tiles.items():
    x, y = R[r]
    for i, b in enumerate(bs):
        box(x - 24 + 25 * i, y - 60, 22, 22, "", BLK[b], BLK[b], arc=20)
    f.vertex("", f"whiteSpace=wrap;html=1;fillColor=#ffffff;strokeColor={GREY};" + FONT, x + 30, y - 22, 10, 44)
    fill = 44 * min(1, 0.35 + 0.3 * len(bs))
    f.vertex("", f"whiteSpace=wrap;html=1;fillColor={AMB};strokeColor=none;" + FONT, x + 30, y + 22 - fill, 10, fill)
lab(470, 893, 620, 30, "<span style='color:#3a7bd5'>━</span> path π<sub>1</sub> &nbsp; <span style='color:#e07a1f'>┅</span> path π<sub>2</sub> (equal cost) &nbsp; ▮ router load / " + it("C<sub>r</sub>") + " &nbsp; ■ placed block", fs=12, align="left")
box(1100, 560, 365, 300,
    "<b>min</b> Σ<sub><i>b,r</i></sub> <i>c<sub>b</sub> x<sub>br</sub></i> (1 + α <i>h<sub>br</sub></i>)<br><br>"
    "Σ<sub><i>r</i>∈π</sub> <i>x<sub>br</sub></i> ≥ 1 &nbsp; ∀ π ∈ ECMP(<i>b</i>)<br>"
    "Σ<sub><i>b</i></sub> <i>c<sub>b</sub> x<sub>br</sub></i> ≤ <i>C<sub>r</sub></i> &nbsp; ∀ <i>r</i><br>"
    "<i>x<sub>br</sub></i> ∈ {0, 1}<br><br><span style='font-size:12px;color:#5f6b7a'>every equal-cost path crosses a holder;<br>"
    "per-router entry budget; early drop (<i>h</i> = hop index)</span>", "#ffffff", AMB, fs=15, align="center")
A([(430, 760), (490, 745)], TEAL, 2.0)

# =====================================================================================================================
# (4) DEPLOY + VERIFY (bottom right)
plane(450, 950, 1030, 310, "4", "Render, verify, emulate", PLUM, PLUM_L)
box(475, 1010, 270, 150, "<span style='font-family:Consolas;font-size:11px'>*filter<br>:FORWARD ACCEPT<br>-A FORWARD -m conntrack ...<br>"
    "-A FORWARD -s 10.0.16.0/20<br>&nbsp;&nbsp;-d 10.0.66.0/25 -p tcp<br>&nbsp;&nbsp;--dport 5432 -j ACCEPT<br>...</span>", "#ffffff", PLUM, fs=11, align="left")
lab(475, 1165, 270, 40, "iptables-restore per router", fs=12, color=GREY)
A([(750, 1085), (790, 1085)], PLUM, 2.0)
box(795, 1010, 330, 150, "<b>Z3, full 5-tuple</b> (src 32 b, dst 32 b, proto 8 b, port 16 b)<br>"
    "∀ <i>s, d</i>, ∀ π ∈ ECMP(<i>s, d</i>):<br>∧<sub><i>r</i>∈π</sub> dev<sub><i>r</i></sub>(<i>h</i>) ≡ Π(<i>h</i>)<br>"
    "<span style='font-size:12px'>unsat ⇒ verified · sat ⇒ packet witness</span>", "#ffffff", PLUM, fs=13)
A([(1130, 1085), (1170, 1085)], PLUM, 2.0)
box(1175, 1010, 290, 150, "<b>GNS3 VM testbed</b><br><span style='font-size:11px'>FRR 10.2 routers: OSPF, ECMP (L4 hash),<br>iptables; zone hosts as namespaces;<br>"
    "UDP, TCP-SYN, ICMP probes<br>captured at the destination</span>", "#ffffff", PLUM, fs=13)
lab(795, 1178, 670, 70, "KPIs: header-space equivalence, feasible capacity, entries / duplicates, drop position, "
    "solve and verification time, deployment latency, probe conformance and leaks", fs=12, align="left", color=PLUM)
A([(960, 930), (960, 1006)], AMB, 2.0)

# feedback threads (red, dashed)
A([(1100, 1008), (1100, 934)], RED, 1.8, dashed=True)
lab(1108, 950, 200, 26, "witness → re-place", fs=12, color=RED, align="left")
A([(540, 384), (540, 292)], RED, 1.8, dashed=True)
lab(408, 312, 128, 50, "invalid →<br>re-ask", fs=12, color=RED, align="right")

path = os.path.join(OUT, "Figure1.drawio"); f.save(path, name="Figure1")
exe = r"C:\Program Files\draw.io\draw.io.exe"
if os.path.exists(exe):
    for fmt in ("png", "pdf"):
        subprocess.run([exe, "-x", "-f", fmt, "-s", "3" if fmt == "png" else "1", "-b", "10", "-o", os.path.join(OUT, f"Figure1.{fmt}"), path], check=False, timeout=180)
    print("exported png/pdf")
