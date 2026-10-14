#!/usr/bin/env python3
"""FireWeaver emulated multi-router testbed (runs ON the GNS3 VM; python3 standard library only).

Routers : one Docker container per router (FRR 10.2.1 + iptables, image fw-frr:1), OSPFv2 on every point-to-point
          link (hello 1 s / dead 4 s), equal-cost multipath with L4 hashing (fib_multipath_hash_policy=1),
          rp_filter off (asymmetric ECMP), FORWARD chain loaded with iptables-restore.
Zones   : one network namespace per zone ("host"), attached to its router by a veth pair; it owns the first address
          of every zone prefix (on lo); the router has static routes for the zone prefixes (redistributed into OSPF).
Probes  : every host runs an AF_PACKET sniffer; the source host sends UDP datagrams / TCP SYNs / ICMP echo from a
          zone address and a chosen source port; delivery = the probe is captured at the destination host.

usage:  python3 testbed.py up spec.json | deploy spec.json cfgset | probe spec.json probes.json out.json | down
"""
import json, os, subprocess, sys, time, threading, ipaddress as ipa

IMG = "fw-frr:1"


def sh(cmd, check=True, inp=None):
    r = subprocess.run(cmd, shell=True, capture_output=True, text=True, input=inp)
    if check and r.returncode: raise RuntimeError(f"{cmd}\n{r.stderr}")
    return r.stdout


def pid(i): return sh(f"docker inspect -f '{{{{.State.Pid}}}}' fw_r{i}").strip()


def nse(i, cmd, check=True): return sh(f"nsenter -t {pid(i)} -n {cmd}", check)


def frr_conf(i, n_links):
    return f"""frr defaults traditional
hostname r{i}
log syslog informational
!
router ospf
 ospf router-id 10.255.{i // 256}.{i % 256}
 redistribute static
 maximum-paths 64
 network 172.16.0.0/12 area 0
!
""" + "".join(f"interface e{k}\n ip ospf network point-to-point\n ip ospf hello-interval 1\n ip ospf dead-interval 4\n!\n" for k in range(n_links))


DAEMONS = "zebra=yes\nospfd=yes\nbgpd=no\nstaticd=yes\nvtysh_enable=yes\nzebra_options=\"  -A 127.0.0.1 -s 90000000\"\nospfd_options=\"  -A 127.0.0.1\"\nstaticd_options=\"-A 127.0.0.1\"\n"


def up(spec):
    t0 = time.time(); n = spec["n_routers"]; os.makedirs("/tmp/fwcfg", exist_ok=True)
    deg = [0] * n; ifn = {}
    for k, (a, b) in enumerate(spec["edges"]):
        ifn[(k, a)] = f"e{deg[a]}"; deg[a] += 1; ifn[(k, b)] = f"e{deg[b]}"; deg[b] += 1
    for i in range(n):
        open(f"/tmp/fwcfg/frr{i}.conf", "w").write(frr_conf(i, deg[i])); open("/tmp/fwcfg/daemons", "w").write(DAEMONS)
        sh(f"docker create --name fw_r{i} --hostname r{i} --network none --privileged "
           f"--sysctl net.ipv4.ip_forward=1 --sysctl net.ipv4.fib_multipath_hash_policy=1 "
           f"--sysctl net.ipv4.conf.all.rp_filter=0 --sysctl net.ipv4.conf.default.rp_filter=0 {IMG}")
        sh(f"docker cp /tmp/fwcfg/frr{i}.conf fw_r{i}:/etc/frr/frr.conf; docker cp /tmp/fwcfg/daemons fw_r{i}:/etc/frr/daemons")
        sh(f"docker start fw_r{i}")
    P = {i: pid(i) for i in range(n)}
    for k, (a, b) in enumerate(spec["edges"]):
        base = int(ipa.ip_address("172.16.0.0")) + 4 * k
        sh(f"ip link add fwa{k} type veth peer name fwb{k}")
        for end, r, off in (("a", a, 1), ("b", b, 2)):
            sh(f"ip link set fw{end}{k} netns {P[r]}")
            sh(f"nsenter -t {P[r]} -n ip link set fw{end}{k} name {ifn[(k, r)]}")
            sh(f"nsenter -t {P[r]} -n ip addr add {ipa.ip_address(base + off)}/30 dev {ifn[(k, r)]}")
            sh(f"nsenter -t {P[r]} -n ip link set {ifn[(k, r)]} up")
    for j, (z, zd) in enumerate(spec["zones"].items()):
        r = zd["router"]; ns = f"fwh{j}"; rip, hip = f"100.64.{j}.1", f"100.64.{j}.2"
        sh(f"ip netns add {ns}"); sh(f"ip link add fwhr{j} type veth peer name fwhh{j}")
        sh(f"ip link set fwhr{j} netns {P[r]}"); sh(f"ip link set fwhh{j} netns {ns}")
        sh(f"nsenter -t {P[r]} -n ip link set fwhr{j} name z{j}")
        sh(f"nsenter -t {P[r]} -n ip addr add {rip}/30 dev z{j}"); sh(f"nsenter -t {P[r]} -n ip link set z{j} up")
        sh(f"ip netns exec {ns} ip link set fwhh{j} name h0"); sh(f"ip netns exec {ns} ip addr add {hip}/30 dev h0")
        sh(f"ip netns exec {ns} ip link set h0 up; ip netns exec {ns} ip link set lo up")
        sh(f"ip netns exec {ns} ip route add default via {rip}")
        sh(f"ip netns exec {ns} sysctl -qw net.ipv4.conf.all.rp_filter=0 net.ipv4.conf.h0.rp_filter=0")
        for p in zd["prefixes"]:
            net = ipa.ip_network(p); sh(f"ip netns exec {ns} ip addr add {net.network_address + 1}/32 dev lo")
            sh(f"docker exec fw_r{r} vtysh -c 'conf t' -c 'ip route {p} {hip}'")
    t_links = time.time() - t0
    # convergence: every router has a route to every zone prefix
    want = [p for zd in spec["zones"].values() for p in zd["prefixes"]]
    while True:
        ok = 0
        for i in range(n):
            rt = nse(i, "ip route show", check=False)
            ok += all(p in rt for p in want)
        if ok == n or time.time() - t0 > 600: break
        time.sleep(1)
    res = dict(n_routers=n, n_links=len(spec["edges"]), n_zones=len(spec["zones"]), setup_s=t_links,
               converged=ok == n, converge_s=time.time() - t0 - t_links)
    # data-plane warm-up: every zone host must reach the first address of every other zone (no ACLs loaded yet)
    Z = list(spec["zones"]); t1 = time.time()
    first = [str(ipa.ip_network(spec["zones"][z]["prefixes"][0]).network_address + 1) for z in Z]
    while time.time() - t1 < 120:
        bad = [(j, k) for j in range(len(Z)) for k in range(len(Z)) if j != k and
               subprocess.run(f"ip netns exec fwh{j} ping -c 1 -W 1 -I {first[j]} {first[k]}", shell=True, capture_output=True).returncode]
        if not bad: break
        time.sleep(2)
    res["dataplane_ready"] = not bad; res["dataplane_s"] = time.time() - t1
    ecmp = sum(nse(i, "ip route show", check=False).count("nexthop via") for i in range(n))
    res["ecmp_nexthops"] = ecmp
    return res


def deploy(spec, cfgset):
    cfgs = spec["configs"][cfgset]; times = {}
    def one(i):
        t = time.time(); sh(f"docker exec -i fw_r{i} iptables-restore", inp=cfgs[str(i)]); times[i] = time.time() - t
    t0 = time.time(); th = [threading.Thread(target=one, args=(i,)) for i in range(spec["n_routers"])]
    [x.start() for x in th]; [x.join() for x in th]
    rules = {i: int(sh(f"docker exec fw_r{i} sh -c 'iptables -S FORWARD | grep -c -- \"-A FORWARD -s\"'", check=False).strip() or 0)
             for i in range(spec["n_routers"])}
    return dict(cfgset=cfgset, deploy_s=time.time() - t0, per_router_max_s=max(times.values()),
                rules_installed=sum(rules.values()), rules_expected=sum(c.count("-A FORWARD -s") for c in cfgs.values()))


def push(spec, cfgfile):
    """push the iptables-restore files of a subset of routers (incremental update); atomic per router"""
    cfgs = json.load(open(cfgfile)); times = {}
    def one(i):
        t = time.time(); sh(f"docker exec -i fw_r{i} iptables-restore", inp=cfgs[i]); times[i] = time.time() - t
    t0 = time.time(); th = [threading.Thread(target=one, args=(i,)) for i in cfgs]
    [x.start() for x in th]; [x.join() for x in th]
    return dict(routers=len(cfgs), push_s=time.time() - t0, per_router_max_s=max(times.values()) if times else 0.0)


SNIFF = r'''
import socket, struct, sys, time, json
s = socket.socket(socket.AF_PACKET, socket.SOCK_RAW, socket.ntohs(0x0800)); s.settimeout(0.5)
out = open(sys.argv[1], "w"); end = time.time() + float(sys.argv[2])
while time.time() < end:
    try: pkt, addr = s.recvfrom(65535)
    except socket.timeout: continue
    if addr[2] == socket.PACKET_OUTGOING: continue
    ip = pkt[14:] if len(pkt) > 14 and pkt[12:14] == b"\x08\x00" else pkt
    if len(ip) < 20 or ip[0] >> 4 != 4: continue
    ihl = (ip[0] & 15) * 4; pr = ip[9]; src = socket.inet_ntoa(ip[12:16]); dst = socket.inet_ntoa(ip[16:20])
    sp = dp = 0
    if pr in (6, 17) and len(ip) >= ihl + 4: sp, dp = struct.unpack("!HH", ip[ihl:ihl + 4])
    if pr == 6 and len(ip) >= ihl + 14 and (ip[ihl + 13] & 0x12) != 0x02: continue   # only pure SYNs
    if pr == 1 and len(ip) > ihl and ip[ihl] != 8: continue                            # only echo requests
    out.write(f"{src} {dst} {pr} {sp} {dp}\n"); out.flush()
'''

SEND = r'''
import socket, sys, json, time, subprocess
for p in json.load(open(sys.argv[1])):
    src, dst, pr, sp, dp = p["src"], p["dst"], p["proto"], p["sport"], p["dport"]
    try:
        if pr == 17:
            s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM); s.bind((src, sp)); s.sendto(b"fw", (dst, dp)); s.close()
        elif pr == 6:
            s = socket.socket(socket.AF_INET, socket.SOCK_STREAM); s.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
            s.bind((src, sp)); s.setblocking(False)
            try: s.connect((dst, dp))
            except BlockingIOError: pass
            time.sleep(0.002); s.close()
        elif pr == 1:
            subprocess.run(["ping", "-c", "1", "-W", "1", "-I", src, dst], capture_output=True)
    except OSError as e:
        print("ERR", p, e, file=sys.stderr)
    time.sleep(0.001)
'''


def probe(spec, probes, out):
    open("/tmp/fw_sniff.py", "w").write(SNIFF); open("/tmp/fw_send.py", "w").write(SEND)
    Z = list(spec["zones"]); dur = 7200   # sniffers are stopped explicitly after the senders finish
    snif = [subprocess.Popen(f"ip netns exec fwh{j} python3 /tmp/fw_sniff.py /tmp/fw_cap{j}.txt {dur}", shell=True)
            for j in range(len(Z))]
    time.sleep(2); t0 = time.time(); by_src = {}
    for p in probes: by_src.setdefault(Z.index(p["src_zone"]), []).append(p)
    procs = []
    for j, ps in by_src.items():
        json.dump(ps, open(f"/tmp/fw_probe{j}.json", "w"))
        procs.append(subprocess.Popen(f"ip netns exec fwh{j} python3 /tmp/fw_send.py /tmp/fw_probe{j}.json", shell=True))
    [p.wait() for p in procs]; t_send = time.time() - t0
    time.sleep(3)
    for s in snif: s.terminate()
    sh("pkill -f fw_sniff.py", check=False); time.sleep(1)
    got = set()
    for j in range(len(Z)):
        for l in open(f"/tmp/fw_cap{j}.txt"):
            a = l.split(); got.add((a[0], a[1], int(a[2]), int(a[3]) if a[2] != "1" else 0, int(a[4]) if a[2] != "1" else 0))
    res = []
    for p in probes:
        key = (p["src"], p["dst"], p["proto"], p["sport"] if p["proto"] != 1 else 0, p["dport"] if p["proto"] != 1 else 0)
        res.append(dict(p, delivered=key in got))
    json.dump(dict(send_s=t_send, probes=res), open(out, "w"))
    return dict(n=len(res), delivered=sum(r["delivered"] for r in res), send_s=t_send)


def down():
    ids = sh("docker ps -aq --filter name=fw_r", check=False).split()
    if ids: sh("docker rm -f " + " ".join(ids), check=False)
    for ns in sh("ip netns list", check=False).split("\n"):
        if ns.startswith("fwh"): sh(f"ip netns del {ns.split()[0]}", check=False)
    return dict(removed=len(ids))


if __name__ == "__main__":
    c = sys.argv[1]
    if c == "down": print(json.dumps(down()))
    else:
        spec = json.load(open(sys.argv[2]))
        if c == "up": print(json.dumps(up(spec)))
        elif c == "deploy": print(json.dumps(deploy(spec, sys.argv[3])))
        elif c == "probe": print(json.dumps(probe(spec, json.load(open(sys.argv[3])), sys.argv[4])))
        elif c == "push": print(json.dumps(push(spec, sys.argv[3])))
