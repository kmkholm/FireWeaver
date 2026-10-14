"""Run one scenario on the GNS3-VM testbed: up -> (deploy cfgset -> probe) for each cfgset -> down.
usage: python emu_run.py <scenario_id> [cfgsets comma-separated]"""
import os, sys, json, time
import vm_ssh

HERE = os.path.dirname(os.path.abspath(__file__))


def vm(cmd, timeout=3600):
    rc, o, e = vm_ssh.run(cmd, timeout=timeout)
    if rc: raise RuntimeError(f"{cmd}\n{o[-2000:]}\n{e[-3000:]}")
    return o


def main(sid, sets=("fireweaver", "ecmp1", "none")):
    d = os.path.join(HERE, "runs", sid); rem = f"/home/gns3/fw/{sid}"
    vm(f"mkdir -p {rem}")
    for f in ("spec.json", "probes.json"): vm_ssh.put(os.path.join(d, f), f"{rem}/{f}")
    vm_ssh.put(os.path.join(HERE, "testbed.py"), "/home/gns3/fw/testbed.py")
    res = dict(id=sid)
    print(vm("sudo python3 /home/gns3/fw/testbed.py down"), flush=True)
    t = time.time(); res["up"] = json.loads(vm(f"sudo python3 /home/gns3/fw/testbed.py up {rem}/spec.json").strip().splitlines()[-1])
    print("up", res["up"], f"{time.time() - t:.0f}s", flush=True)
    try:
        for cs in sets:
            res[f"deploy_{cs}"] = json.loads(vm(f"sudo python3 /home/gns3/fw/testbed.py deploy {rem}/spec.json {cs}").strip().splitlines()[-1])
            time.sleep(1)
            res[f"probe_{cs}"] = json.loads(vm(f"sudo python3 /home/gns3/fw/testbed.py probe {rem}/spec.json {rem}/probes.json {rem}/probe_{cs}.json").strip().splitlines()[-1])
            vm_ssh.get(f"{rem}/probe_{cs}.json", os.path.join(d, f"probe_{cs}.json"))
            pr = json.load(open(os.path.join(d, f"probe_{cs}.json")))["probes"]
            ok = sum(p["delivered"] == p["intended"] for p in pr)
            leak = sum(p["delivered"] and not p["intended"] for p in pr); blocked = sum(p["intended"] and not p["delivered"] for p in pr)
            res[f"conf_{cs}"] = dict(n=len(pr), conform=ok, leaks=leak, wrongly_blocked=blocked)
            print(cs, res[f"deploy_{cs}"], res[f"conf_{cs}"], flush=True)
    finally:
        print(vm("sudo python3 /home/gns3/fw/testbed.py down"), flush=True)
    json.dump(res, open(os.path.join(d, "result.json"), "w"), indent=1)
    return res


if __name__ == "__main__":
    main(sys.argv[1], tuple(sys.argv[2].split(",")) if len(sys.argv) > 2 else ("fireweaver", "ecmp1", "none"))
