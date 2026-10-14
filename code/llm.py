"""LLM front end of FireWeaver (local Qwen3-8B Q4_K_M via llama.cpp server, OpenAI-compatible API).

Modes
  ir      : each NL intent -> one typed intent object (IR) in JSON; the compiler (scenario.compile_intents) produces
            the first-match rules deterministically.
  rules   : the whole intent list -> raw ordered rule list in JSON (ablation: no IR, the LLM must handle precedence).
The response is constrained to JSON with a grammar-free instruction + validation; invalid outputs are re-asked with
the validator's message (bounded retries).
"""
import json, re, time, urllib.request

URL = "http://127.0.0.1:8088/v1/chat/completions"
SVCS = None


def chat(messages, max_tokens=700, temperature=0.0, think=False, seed=0):
    msgs = [dict(m) for m in messages]
    if not think: msgs[-1]["content"] = "/no_think " + msgs[-1]["content"]
    body = dict(messages=msgs, temperature=temperature, max_tokens=max_tokens if not think else max_tokens + 2000, seed=seed)
    t = time.time()
    r = urllib.request.urlopen(urllib.request.Request(URL, data=json.dumps(body).encode(),
                               headers={"Content-Type": "application/json"}), timeout=600)
    j = json.loads(r.read()); txt = j["choices"][0]["message"]["content"]
    txt = re.sub(r"<think>.*?</think>", "", txt, flags=re.S).strip()
    return txt, dict(s=time.time() - t, prompt=j["usage"]["prompt_tokens"], completion=j["usage"]["completion_tokens"])


def extract_json(txt):
    m = re.search(r"```(?:json)?\s*(.*?)```", txt, re.S)
    if m: txt = m.group(1)
    i = min([k for k in (txt.find("{"), txt.find("[")) if k >= 0], default=-1)
    if i < 0: raise ValueError("no JSON found")
    return json.loads(txt[i:txt.rfind("}" if txt[i] == "{" else "]") + 1])


def system_prompt(sc, services, fewshot=True):
    base = _sysprompt(sc, services)
    return base if fewshot else base.split("Choosing the type")[0] + "Answer with JSON only."


def _sysprompt(sc, services):
    zl = "\n".join(f"- {z}" for z in sc["zones"])
    sl = "\n".join(f"- {k}: {v[0]} {v[1]}-{v[2]}" for k, v in services.items())
    return f"""You translate network security intents into a typed intermediate representation (IR) for a firewall compiler.
Zones (use these exact names):
{zl}
Services (use these exact names; 'any' = all traffic):
{sl}
IR types (JSON objects):
  {{"type":"allow","src":Z,"dst":Z,"svcs":[S,...]}}             src may reach dst on these services
  {{"type":"allow_except","src":Z,"dst":Z,"broad":S,"ex":[S,...]}} broad service allowed except the listed ones
  {{"type":"block","src":Z,"dst":Z}}                             all traffic src->dst denied, overriding public services
  {{"type":"isolate","src":Z,"allowed":[[Z,S],...]}}              src may only reach the listed (zone, service) pairs
  {{"type":"public","dst":Z,"svcs":[S,...]}}                     every zone may reach dst on these services
Choosing the type (decide this first):
- the sentence lists services that ARE allowed and nothing is excluded -> allow
- a broad service/port range is allowed BUT some services inside it are blocked ("except", "but deny", "the rest is allowed") -> allow_except
- ALL traffic between two zones is forbidden, overriding other rules -> block
- a zone may ONLY reach some destinations, everything else it sends is dropped ("only", "apart from ... dropped", "isolated") -> isolate
- every zone may reach one destination -> public
Examples (placeholder zones zA, zB, zC):
"zA may use any TCP port towards zB, except Telnet (TCP 23), which must be blocked." -> {{"type":"allow_except","src":"zA","dst":"zB","broad":"any-tcp","ex":["telnet"]}}
"Block SNMP (UDP 161) from zA to zB; the rest of any UDP port between them is allowed." -> {{"type":"allow_except","src":"zA","dst":"zB","broad":"any-udp","ex":["snmp"]}}
"Permit TCP ports 1024-65535 from zA to zB but deny RDP (TCP 3389)." -> {{"type":"allow_except","src":"zA","dst":"zB","broad":"high-tcp","ex":["rdp"]}}
"Apart from zB on HTTPS (TCP 443), all traffic originating in zA must be dropped." -> {{"type":"isolate","src":"zA","allowed":[["zB","https"]]}}
"zB must accept NTP (UDP 123) from zA." -> {{"type":"allow","src":"zA","dst":"zB","svcs":["ntp"]}}
"No packet from zA may enter zB, even for services open to everyone." -> {{"type":"block","src":"zA","dst":"zB"}}
"Make DNS over UDP 53 on zC reachable from all internal zones." -> {{"type":"public","dst":"zC","svcs":["dns"]}}
Answer with JSON only."""


def validate_ir(it, sc, services):
    Z = set(sc["zones"]); S = set(services)
    t = it.get("type")
    if t not in ("allow", "allow_except", "block", "isolate", "public"): return f"unknown type {t!r}"
    for k in ("src", "dst"):
        if k in it and it[k] not in Z: return f"unknown zone {it[k]!r}"
    if t in ("allow", "allow_except", "block") and not all(k in it for k in ("src", "dst")): return "missing src/dst"
    if t == "isolate" and "src" not in it: return "missing src"
    for s in it.get("svcs", []) + it.get("ex", []) + ([it["broad"]] if "broad" in it else []):
        if s not in S: return f"unknown service {s!r}"
    for p in it.get("allowed", []):
        if len(p) != 2 or p[0] not in Z or p[1] not in S: return f"bad allowed pair {p!r}"
    return None


def translate_ir(sc, services, think=False, retries=2, seed=0, fewshot=True):
    sysmsg = system_prompt(sc, services, fewshot); out, stats, fails = [], [], 0
    for sent in sc["nl"]:
        msgs = [dict(role="system", content=sysmsg), dict(role="user", content=f"Intent: {sent}\nReturn exactly one IR object.")]
        ir = None
        for attempt in range(retries + 1):
            txt, st = chat(msgs, think=think, seed=seed + attempt); stats.append(st)
            try:
                cand = extract_json(txt)
                if isinstance(cand, list): cand = cand[0]
                err = validate_ir(cand, sc, services)
            except Exception as e:
                cand, err = None, f"invalid JSON ({e})"
            if err is None: ir = cand; break
            msgs += [dict(role="assistant", content=txt), dict(role="user", content=f"Invalid: {err}. Fix it and return JSON only.")]
        if ir is None: fails += 1
        out.append(ir)            # aligned with sc["nl"]; None = translation failed after the retries
    return out, stats, fails


def translate_rules(sc, services, think=False, retries=2, seed=0):
    """ablation: ask directly for the ordered first-match rule list"""
    zl = ", ".join(sc["zones"]); sl = "\n".join(f"- {k}: {v[0]} {v[1]}-{v[2]}" for k, v in services.items())
    sysmsg = f"""You write an ordered first-match firewall policy between zones ({zl}).
Services: \n{sl}
Each rule: {{"src":Z or "*","dst":Z or "*","proto":"tcp"|"udp"|"icmp"|"*","dlo":int,"dhi":int,"action":"permit"|"deny"}}.
The first matching rule decides; unmatched traffic is denied. Order rules so that exceptions and overrides win.
Answer with a JSON list only."""
    msgs = [dict(role="system", content=sysmsg), dict(role="user", content="Intents:\n" + "\n".join(f"{i + 1}. {s}" for i, s in enumerate(sc["nl"])))]
    stats = []
    for attempt in range(retries + 1):
        txt, st = chat(msgs, max_tokens=4000, think=think, seed=seed + attempt); stats.append(st)
        try:
            rules = extract_json(txt)
            if isinstance(rules, dict): rules = rules.get("rules", [])
            return rules, stats, 0
        except Exception as e:
            msgs += [dict(role="assistant", content=txt[:2000]), dict(role="user", content=f"Invalid JSON ({e}). Return the JSON list only.")]
    return [], stats, 1
