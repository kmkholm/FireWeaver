#!/usr/bin/env python3
"""Configure and measure the FireWeaver testbed inside a running GNS3 project (runs ON the GNS3 VM).
Node containers are named GNS3.<node>.<project_id>; addressing and FRR configuration follow testbed.py.
usage: python3 gns3_testbed.py config spec.json plan.json | deploy spec.json plan.json cfgset | probe spec.json plan.json probes.json out.json
"""
import json, sys, time, subprocess, threading, ipaddress as ipa
import testbed as TB                       # reuses frr_conf / DAEMONS / SNIFF / SEND


def sh(cmd, check=True, inp=None):
    r = subprocess.run(cmd, shell=True, capture_output=True, text=True, input=inp)
    if check and r.returncode: raise RuntimeError(f"{cmd}\n{r.stderr}")
    return r.stdout


def cname(plan, node):
    if node.startswith("Z") and "-" not in node: node = f"{node}-{plan['znames'][int(node[1:])]}"
    return f"GNS3.{node}.{plan['project_id']}"


def dx(plan, node, cmd, check=True, inp=None):
    return sh(f"docker exec -i {cname(plan, node)} sh -c '{cmd}'", check, inp)


def writeconf(spec, plan):
    """write frr.conf + daemons into the (stopped) router containers; FRR reads them when GNS3 starts the node"""
    n = spec["n_routers"]; Z = list(spec["zones"])
    for r in range(n):
        ad = plan["adapters"][str(r)]
        conf = TB.frr_conf(r, 0).replace("hostname r", "hostname R")
        conf += "".join(f"interface eth{idx}\n ip ospf network point-to-point\n ip ospf hello-interval 1\n ip ospf dead-interval 4\n!\n"
                        for idx, it in enumerate(ad) if it[0] == "link")
        for j, z in enumerate(Z):
            if spec["zones"][z]["router"] == r:
                conf += "".join(f"ip route {p} 100.64.{j}.2\n" for p in spec["zones"][z]["prefixes"])
        open("/tmp/fw_frr.conf", "w").write(conf); open("/tmp/fw_daemons", "w").write(TB.DAEMONS)
        sh(f"docker cp /tmp/fw_frr.conf {cname(plan, f'R{r}')}:/etc/frr/frr.conf; docker cp /tmp/fw_daemons {cname(plan, f'R{r}')}:/etc/frr/daemons")
    return dict(routers=n)


def config(spec, plan):
    t0 = time.time(); n = spec["n_routers"]; Z = list(spec["zones"])
    for r in range(n):
        node = f"R{r}"; ad = plan["adapters"][str(r)]
        dx(plan, node, "sysctl -qw net.ipv4.ip_forward=1 net.ipv4.fib_multipath_hash_policy=1 net.ipv4.conf.all.rp_filter=0 net.ipv4.conf.default.rp_filter=0")
        for idx, item in enumerate(ad):
            if item[0] == "link":
                k, peer = item[1], item[2]; a, b = spec["edges"][k]
                ip = ipa.ip_address(int(ipa.ip_address("172.16.0.0")) + 4 * k + (1 if r == a else 2))
                dx(plan, node, f"ip addr replace {ip}/30 dev eth{idx}; ip link set eth{idx} up; sysctl -qw net.ipv4.conf.eth{idx}.rp_filter=0")
            else:
                j = item[1]
                dx(plan, node, f"ip addr replace 100.64.{j}.1/30 dev eth{idx}; ip link set eth{idx} up; sysctl -qw net.ipv4.conf.eth{idx}.rp_filter=0")
    for j, z in enumerate(Z):
        node = f"Z{j}"
        dx(plan, node, f"sysctl -qw net.ipv4.conf.all.rp_filter=0 net.ipv4.conf.eth0.rp_filter=0; ip addr replace 100.64.{j}.2/30 dev eth0; ip link set eth0 up; ip route replace default via 100.64.{j}.1")
        for p in spec["zones"][z]["prefixes"]:
            dx(plan, node, f"ip addr replace {ipa.ip_network(p).network_address + 1}/32 dev lo")
    t_cfg = time.time() - t0
    want = [p for zd in spec["zones"].values() for p in zd["prefixes"]]
    while True:
        ok = sum(all(p in dx(plan, f"R{r}", "ip route show", check=False) for p in want) for r in range(n))
        if ok == n or time.time() - t0 > 600: break
        time.sleep(1)
    res = dict(config_s=t_cfg, converged=ok == n, converge_s=time.time() - t0 - t_cfg)
    first = [str(ipa.ip_network(spec["zones"][z]["prefixes"][0]).network_address + 1) for z in Z]; t1 = time.time()
    while time.time() - t1 < 120:
        bad = [(j, k) for j in range(len(Z)) for k in range(len(Z)) if j != k and
               subprocess.run(f"docker exec {cname(plan, f'Z{j}')} ping -c 1 -W 1 -I {first[j]} {first[k]}", shell=True, capture_output=True).returncode]
        if not bad: break
        time.sleep(2)
    res.update(dataplane_ready=not bad, dataplane_s=time.time() - t1,
               ecmp_nexthops=sum(dx(plan, f"R{r}", "ip route show", check=False).count("nexthop via") for r in range(n)))
    return res


def deploy(spec, plan, cfgset):
    cfgs = spec["configs"][cfgset]; times = {}
    def one(i):
        t = time.time(); dx(plan, f"R{i}", "iptables-restore", inp=cfgs[str(i)]); times[i] = time.time() - t
    t0 = time.time(); th = [threading.Thread(target=one, args=(i,)) for i in range(spec["n_routers"])]
    [x.start() for x in th]; [x.join() for x in th]
    rules = sum(int(dx(plan, f"R{i}", "iptables -S FORWARD | grep -c -- \"-A FORWARD -s\"", check=False).strip() or 0) for i in range(spec["n_routers"]))
    return dict(cfgset=cfgset, deploy_s=time.time() - t0, rules_installed=rules,
                rules_expected=sum(c.count("-A FORWARD -s") for c in cfgs.values()))


def probe(spec, plan, probes, out):
    Z = list(spec["zones"])
    open("/tmp/fw_sniff.py", "w").write(TB.SNIFF); open("/tmp/fw_send.py", "w").write(TB.SEND)
    for j in range(len(Z)):
        sh(f"docker cp /tmp/fw_sniff.py {cname(plan, f'Z{j}')}:/tmp/fw_sniff.py; docker cp /tmp/fw_send.py {cname(plan, f'Z{j}')}:/tmp/fw_send.py")
    snif = [subprocess.Popen(f"docker exec {cname(plan, f'Z{j}')} python3 /tmp/fw_sniff.py /tmp/cap.txt 7200", shell=True) for j in range(len(Z))]
    time.sleep(2); t0 = time.time(); by = {}
    for p in probes: by.setdefault(Z.index(p["src_zone"]), []).append(p)
    procs = []
    for j, ps in by.items():
        json.dump(ps, open(f"/tmp/fw_probe{j}.json", "w")); sh(f"docker cp /tmp/fw_probe{j}.json {cname(plan, f'Z{j}')}:/tmp/fw_probe.json")
        procs.append(subprocess.Popen(f"docker exec {cname(plan, f'Z{j}')} python3 /tmp/fw_send.py /tmp/fw_probe.json", shell=True))
    [p.wait() for p in procs]; t_send = time.time() - t0; time.sleep(3)
    for j in range(len(Z)): sh(f"docker exec {cname(plan, f'Z{j}')} pkill -f fw_sniff.py", check=False)
    [s.wait() for s in snif]
    got = set()
    for j in range(len(Z)):
        for l in sh(f"docker exec {cname(plan, f'Z{j}')} cat /tmp/cap.txt", check=False).splitlines():
            a = l.split(); got.add((a[0], a[1], int(a[2]), int(a[3]) if a[2] != "1" else 0, int(a[4]) if a[2] != "1" else 0))
    res = [dict(p, delivered=(p["src"], p["dst"], p["proto"], p["sport"] if p["proto"] != 1 else 0, p["dport"] if p["proto"] != 1 else 0) in got) for p in probes]
    json.dump(dict(send_s=t_send, probes=res), open(out, "w"))
    return dict(n=len(res), conform=sum(r["delivered"] == r["intended"] for r in res),
                leaks=sum(r["delivered"] and not r["intended"] for r in res), wrongly_blocked=sum(r["intended"] and not r["delivered"] for r in res), send_s=t_send)


if __name__ == "__main__":
    c = sys.argv[1]; spec = json.load(open(sys.argv[2])); plan = json.load(open(sys.argv[3])); plan["znames"] = list(spec["zones"])
    if c == "config": print(json.dumps(config(spec, plan)))
    elif c == "writeconf": print(json.dumps(writeconf(spec, plan)))
    elif c == "deploy": print(json.dumps(deploy(spec, plan, sys.argv[4])))
    elif c == "probe": print(json.dumps(probe(spec, plan, json.load(open(sys.argv[4])), sys.argv[5])))
