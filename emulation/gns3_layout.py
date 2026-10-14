"""Re-position the nodes of the GNS3 project for a readable figure (hubs apart, other routers on a ring, zone hosts
outside their router) and hide interface labels.  python gns3_layout.py <scenario_id>"""
import os, sys, json, math, urllib.request
import networkx as nx
HERE = os.path.dirname(os.path.abspath(__file__)); API = "http://192.168.56.101/v2"

def call(m, path, body=None):
    r = urllib.request.Request(API + path, method=m, data=json.dumps(body).encode() if body is not None else None, headers={"Content-Type": "application/json"})
    t = urllib.request.urlopen(r, timeout=120).read(); return json.loads(t) if t else None

sid = sys.argv[1]; d = os.path.join(HERE, "runs", sid)
spec = json.load(open(os.path.join(d, "spec.json"))); plan = json.load(open(os.path.join(d, "gns3_plan.json")))
pid = plan["project_id"]; G = nx.Graph(); G.add_edges_from(map(tuple, spec["edges"])); n = spec["n_routers"]
deg = dict(G.degree()); hubs = sorted(G.nodes(), key=lambda r: -deg[r])[:2]
others = [r for r in G.nodes() if r not in hubs]
kk = nx.kamada_kawai_layout(G)
others.sort(key=lambda r: math.atan2(kk[r][1], kk[r][0]))
pos = {hubs[0]: (-260, 0), hubs[1]: (260, 0)}
for i, r in enumerate(others):
    a = 2 * math.pi * i / len(others); pos[r] = (int(820 * math.cos(a)), int(470 * math.sin(a)))
for r, (x, y) in pos.items():
    call("PUT", f"/projects/{pid}/nodes/{plan['nodes'][f'R{r}']}", {"x": x - 25, "y": y - 20})
for j, z in enumerate(spec["zones"]):
    r = spec["zones"][z]["router"]; x, y = pos[r]; L = math.hypot(x, y) or 1
    hx, hy = int(x + 150 * x / L), int(y + 110 * y / L)
    call("PUT", f"/projects/{pid}/nodes/{plan['nodes'][f'Z{j}']}", {"x": hx - 25, "y": hy - 20})
call("PUT", f"/projects/{pid}", {"show_interface_labels": False})
print("hubs", hubs, "moved", len(pos) + len(spec["zones"]))
