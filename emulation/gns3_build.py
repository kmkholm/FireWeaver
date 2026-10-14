"""Build the FireWeaver testbed as a real GNS3 project through the GNS3 server REST API (v2).

Routers  : Docker nodes from image fw-frr:1 (FRR 10.2.1 + iptables), one adapter per link + one per attached zone.
Zone hosts: Docker nodes from the same image (only used as end hosts), one adapter.
Links    : one GNS3 link per topology edge and per zone attachment.
Layout   : Kamada-Kawai on the topology graph (deterministic), hosts placed next to their router.
Writes runs/<sid>/gns3_plan.json with node ids, adapter plan and addressing for gns3_config.py.
usage: python gns3_build.py <scenario_id>
"""
import os, sys, json, time, urllib.request
import networkx as nx

HERE = os.path.dirname(os.path.abspath(__file__))
API = "http://192.168.56.101/v2"
IMG = "fw-frr:1"


def call(method, path, body=None):
    req = urllib.request.Request(API + path, method=method, data=json.dumps(body).encode() if body is not None else None,
                                 headers={"Content-Type": "application/json"})
    with urllib.request.urlopen(req, timeout=300) as r:
        t = r.read(); return json.loads(t) if t else None


def main(sid):
    spec = json.load(open(os.path.join(HERE, "runs", sid, "spec.json")))
    n = spec["n_routers"]; E = [tuple(e) for e in spec["edges"]]; Z = list(spec["zones"])
    for p in call("GET", "/projects"):
        if p["name"] == f"FireWeaver-{sid}": call("DELETE", f"/projects/{p['project_id']}")
    proj = call("POST", "/projects", {"name": f"FireWeaver-{sid}", "auto_close": False, "scene_width": 2400, "scene_height": 1400})
    pid = proj["project_id"]
    G = nx.Graph(); G.add_edges_from(E)
    pos = nx.kamada_kawai_layout(G)
    xs = [p[0] for p in pos.values()]; ys = [p[1] for p in pos.values()]
    sx = lambda v: int(-700 + 1400 * (v - min(xs)) / (max(xs) - min(xs)))
    sy = lambda v: int(-420 + 840 * (v - min(ys)) / (max(ys) - min(ys)))
    # adapter plan
    adapters = {r: [] for r in range(n)}            # router -> list of ("link", k, peer) / ("zone", j)
    for k, (a, b) in enumerate(E):
        adapters[a].append(("link", k, b)); adapters[b].append(("link", k, a))
    for j, z in enumerate(Z):
        adapters[spec["zones"][z]["router"]].append(("zone", j))
    nodes = {}
    for r in range(n):
        nd = call("POST", f"/projects/{pid}/nodes", {
            "name": f"R{r}", "node_type": "docker", "compute_id": "local", "symbol": ":/symbols/classic/router.svg",
            "x": sx(pos[r][0]), "y": sy(pos[r][1]),
            "properties": {"image": IMG, "adapters": len(adapters[r]), "console_type": "none"}})
        nodes[f"R{r}"] = nd["node_id"]
    for j, z in enumerate(Z):
        r = spec["zones"][z]["router"]; x, y = sx(pos[r][0]), sy(pos[r][1])
        nd = call("POST", f"/projects/{pid}/nodes", {
            "name": f"Z{j}-{z}", "node_type": "docker", "compute_id": "local", "symbol": ":/symbols/classic/computer.svg",
            "x": x + (70 if x < 0 else -110), "y": y + 70,
            "properties": {"image": IMG, "adapters": 1, "console_type": "none"}})
        nodes[f"Z{j}"] = nd["node_id"]
    # links
    def adapter_of(r, item): return adapters[r].index(item)
    for k, (a, b) in enumerate(E):
        call("POST", f"/projects/{pid}/links", {"nodes": [
            {"node_id": nodes[f"R{a}"], "adapter_number": adapter_of(a, ("link", k, b)), "port_number": 0},
            {"node_id": nodes[f"R{b}"], "adapter_number": adapter_of(b, ("link", k, a)), "port_number": 0}]})
    for j, z in enumerate(Z):
        r = spec["zones"][z]["router"]
        call("POST", f"/projects/{pid}/links", {"nodes": [
            {"node_id": nodes[f"R{r}"], "adapter_number": adapter_of(r, ("zone", j)), "port_number": 0},
            {"node_id": nodes[f"Z{j}"], "adapter_number": 0, "port_number": 0}]})
    plan = dict(sid=sid, project_id=pid, nodes=nodes, adapters={str(r): a for r, a in adapters.items()})
    json.dump(plan, open(os.path.join(HERE, "runs", sid, "gns3_plan.json"), "w"), indent=1)
    t = time.time(); call("POST", f"/projects/{pid}/nodes/start", {})
    print(json.dumps(dict(project=pid, nodes=len(nodes), links=len(E) + len(Z), start_s=round(time.time() - t, 1))))


if __name__ == "__main__":
    main(sys.argv[1])
