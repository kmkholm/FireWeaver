"""Run the FireWeaver measurement inside the GNS3 project built by gns3_build.py (project stays up for screenshots).
usage: python emu_gns3.py <scenario_id>"""
import os, sys, json
import vm_ssh

HERE = os.path.dirname(os.path.abspath(__file__))


def vm(cmd, timeout=3600):
    rc, o, e = vm_ssh.run(cmd, timeout=timeout)
    if rc: raise RuntimeError(f"{cmd}\n{o[-1500:]}\n{e[-2500:]}")
    return o.strip().splitlines()[-1]


def main(sid):
    d = os.path.join(HERE, "runs", sid); rem = f"/home/gns3/fw/gns3_{sid}"
    vm(f"mkdir -p {rem}; echo ok")
    for f in ("spec.json", "probes.json", "gns3_plan.json"): vm_ssh.put(os.path.join(d, f), f"{rem}/{f}")
    for f in ("testbed.py", "gns3_testbed.py"): vm_ssh.put(os.path.join(HERE, f), f"{rem}/{f}")
    base = f"cd {rem} && sudo python3 gns3_testbed.py"
    res = dict(id=sid, platform="GNS3 2.2.61 project (Docker nodes)")
    import urllib.request, time as _t
    pid = json.load(open(os.path.join(d, "gns3_plan.json")))["project_id"]
    api = lambda path: urllib.request.urlopen(urllib.request.Request("http://192.168.56.101/v2/projects/" + pid + path, method="POST", data=b"{}", headers={"Content-Type": "application/json"}), timeout=300).read()
    api("/nodes/stop"); print(vm(f"{base} writeconf spec.json gns3_plan.json"), flush=True)
    t0 = _t.time(); api("/nodes/start"); res["gns3_start_s"] = _t.time() - t0
    res["config"] = json.loads(vm(f"{base} config spec.json gns3_plan.json")); print("config", res["config"], flush=True)
    for cs in ("fireweaver", "ecmp1", "none"):
        res[f"deploy_{cs}"] = json.loads(vm(f"{base} deploy spec.json gns3_plan.json {cs}"))
        res[f"probe_{cs}"] = json.loads(vm(f"{base} probe spec.json gns3_plan.json probes.json probe_{cs}.json"))
        vm_ssh.get(f"{rem}/probe_{cs}.json", os.path.join(d, f"gns3_probe_{cs}.json"))
        print(cs, res[f"deploy_{cs}"], res[f"probe_{cs}"], flush=True)
    # leave the FireWeaver configuration installed for the screenshots
    res["deploy_final"] = json.loads(vm(f"{base} deploy spec.json gns3_plan.json fireweaver"))
    json.dump(res, open(os.path.join(d, "gns3_result.json"), "w"), indent=1)


if __name__ == "__main__":
    main(sys.argv[1])
