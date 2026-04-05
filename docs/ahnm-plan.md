# Agentic Home Network Monitor (AHNM) — Implementation Plan

**Target system:** GA-78LMT-S2P, Ubuntu 24.04, 8–16 GB RAM
**Network:** 192.168.1.0/24, 29 mapped devices
**Duration:** ~6 weeks, three phases

---

## Hardware Note

The GA-78LMT-S2P does not support AVX-512 and has limited usable RAM (~8 GB under load). For the local LLM layer in Phase 3, use **Ollama with Mistral-7B** (4-bit quantized, ~4.1 GB VRAM/RAM) or **Phi-3-mini** (~2.3 GB). Do not attempt Llama-3-70B or other large models — they will OOM or run unacceptably slowly on this hardware.

---

## Phase 1 — Easy (Week 1): Fix & Watch

**Goal:** Close the four known open vulnerabilities, deploy baseline monitoring, and establish the living device inventory in the wiki.

### 1.1 Fix Router Security Issues (Day 1–2)

These are overdue. Address all four before deploying any monitoring stack:

| Issue | Action |
|---|---|
| Open DNS resolver (port 53 WAN) | Disable WAN-facing DNS in router config; restrict to LAN only |
| Router admin on port 80 (HTTP) | Disable HTTP admin; force HTTPS only |
| Router admin on ports 8080/8443 | Disable alternate admin ports unless explicitly needed |
| Router admin on port 443 (WAN) | Restrict admin access to LAN interface only |

Verify with `nmap -p 53,80,443,8080,8443 <WAN-IP>` from an external host or VPN exit node after changes.

### 1.2 Deploy Prometheus + Grafana (Day 2–3)

Run via Docker Compose on the Ubuntu host. Expose Grafana on `localhost:3000` (not LAN-wide initially).

```yaml
# docker-compose.yml (minimal)
services:
  prometheus:
    image: prom/prometheus:latest
    volumes:
      - ./prometheus.yml:/etc/prometheus/prometheus.yml
    ports:
      - "127.0.0.1:9090:9090"

  grafana:
    image: grafana/grafana:latest
    ports:
      - "127.0.0.1:3000:3000"
    environment:
      - GF_SECURITY_ADMIN_PASSWORD=changeme
```

Add node_exporter on the Ubuntu host for CPU/memory/disk metrics. Add SNMP exporter for devices that support it.

### 1.3 Deploy LibreNMS (Day 3–4)

LibreNMS provides device autodiscovery, SNMP polling, and a web UI for inventory. Install via Docker or the native Ubuntu package.

- Enable SNMP on devices that support it (routers, managed switches, NAS)
- Run initial discovery against 192.168.1.0/24
- Flag 192.168.1.57 (unknown device) and the two Gaoshengda devices (.232 and .249) as "requires investigation" in the device notes
- Enable alerting for new device discovery

### 1.4 Deploy Zeek on Mirrored Interface (Day 4–5)

Zeek captures traffic metadata (not full packet content) and writes structured logs to `/opt/zeek/logs/`.

- Configure a mirror/SPAN port on the router or managed switch
- Bring up a second NIC (or use a USB-Ethernet adapter) as the passive tap interface
- Enable the following Zeek scripts at minimum: `conn`, `dns`, `http`, `ssl`, `files`, `notice`
- Parse `dns.log` to identify what 192.168.1.57 is resolving — this often identifies unknown devices

### 1.5 Wire into SemanticMediaWiki (Day 5–7)

The wiki at `localhost:8080` becomes the authoritative device inventory.

- Create a `Device` template with properties: `IP`, `MAC`, `Hostname`, `Vendor`, `First Seen`, `Last Seen`, `Status`, `Notes`
- Create a page per device (or a batch import from nmap XML output)
- Mark 192.168.1.57, .232, and .249 with `Status=Under Investigation`
- Create `Project:AHNM` page (see companion wiki page file)
- Create issue pages for the four router vulnerabilities

### Phase 1 OSS Manifest

| Tool | Role | Install Method | Port/Interface |
|---|---|---|---|
| Prometheus | Metrics collection and storage | Docker Compose | localhost:9090 |
| Grafana | Metrics visualization | Docker Compose | localhost:3000 |
| node_exporter | Ubuntu host system metrics | Docker or binary | localhost:9100 |
| LibreNMS | Device inventory, SNMP polling, alerts | Docker or apt | localhost:8000 |
| Zeek | Traffic metadata / connection logs | apt (zeek package) | Passive tap NIC |
| nmap | On-demand network scanning | Already installed | CLI |
| masscan | Fast port discovery | Already installed | CLI |
| SemanticMediaWiki | Living device inventory and knowledge base | Already running | localhost:8080 |

---

## Phase 2 — Better (Weeks 2–3): Detect & Alert

**Goal:** Add intrusion detection, a message bus, and the first NanoClaw skill-based agents.

### 2.1 Suricata IDS

Deploy Suricata alongside Zeek on the same tap interface. Use the ET Open ruleset (free). Configure EVE JSON output and ship logs to Prometheus via a log exporter or directly parse in agents.

- Start with the `emerging-threats` and `emerging-scan` rule categories
- Tune false positives aggressively in the first week — home networks generate a lot of benign "scan" traffic
- Alert on: port scans, DNS tunneling, known C2 beacons, unexpected outbound connections on non-standard ports

### 2.2 NATS Message Bus

NATS is the right choice over Kafka for a home lab: single binary, ~10 MB RAM, no ZooKeeper dependency, JetStream for persistence.

```bash
# Run NATS with JetStream enabled
docker run -d --name nats -p 4222:4222 nats:latest -js
```

Define subjects:
- `ahnm.discovery.new_device`
- `ahnm.threat.alert`
- `ahnm.intel.result`
- `ahnm.wiki.update`

### 2.3 NanoClaw Skill-Based Agents

Three Python scripts registered as NanoClaw scheduled tasks or MCP tools:

**discovery_agent.py**
- Runs nmap scan on 192.168.1.0/24 every 15 minutes
- Compares results against known device list in wiki (via MediaWiki API)
- On new device detection: publishes to `ahnm.discovery.new_device`, triggers anomaly_agent

**anomaly_agent.py**
- Subscribes to `ahnm.discovery.new_device`
- Sends WhatsApp alert via NanoClaw with device IP, MAC, vendor OUI lookup
- Creates draft wiki page for the new device
- Logs event to audit trail

**threat_intel_agent.py**
- Subscribes to Suricata/Zeek external IP alerts
- Queries AbuseIPDB API for confidence score and abuse categories
- Publishes enriched result to `ahnm.threat.alert`
- Posts to WhatsApp if confidence score > 50

### 2.4 ntfy for Self-Hosted Push Notifications

Deploy ntfy as a fallback/secondary notification channel (works without WhatsApp):

```bash
docker run -d --name ntfy -p 127.0.0.1:2586:80 binwiederhier/ntfy serve
```

Subscribe to the `ahnm` topic on mobile via the ntfy app.

### 2.5 Grafana Dashboards

Build out dashboards for all 29 devices:
- Per-device bandwidth (from SNMP + Zeek conn.log)
- DNS query frequency by device (Zeek dns.log)
- Alert history timeline (Suricata EVE + NATS events)
- Device inventory table with last-seen timestamps

---

## Phase 3 — Best (Weeks 4–6): Agentic Layer

**Goal:** Move from scripted alerts to a reasoning system with redundancy, local LLM inference, and human-in-the-loop remediation.

### 3.1 N-Modular Redundancy (2–3 Detection Paths)

Run at least two independent detection mechanisms for each threat class:

| Threat Class | Path 1 | Path 2 | Path 3 (optional) |
|---|---|---|---|
| New device | LibreNMS discovery | nmap diff agent | Zeek new_connection notice |
| Port scan | Suricata ET-scan rules | Zeek scan detector | nmap passive fingerprint |
| DNS anomaly | Zeek dns.log | Suricata DNS rules | query frequency baseline |
| External C2 | Suricata C2 rules | AbuseIPDB enrichment | Zeek SSL cert anomaly |

### 3.2 LangChain Reasoning Agent with Local Ollama

Install Ollama and pull a model appropriate for the hardware:

```bash
# Install Ollama
curl -fsSL https://ollama.com/install.sh | sh

# Pull a model that fits in ~4 GB RAM
ollama pull mistral:7b-instruct-q4_K_M
# or, for lighter footprint:
ollama pull phi3:mini
```

Build a LangChain agent that:
- Receives correlated alerts from NATS
- Has tools: `query_wiki()`, `run_nmap()`, `lookup_abuseipdb()`, `get_zeek_summary()`
- Produces a structured threat assessment: severity, confidence, recommended action
- Routes to human-in-the-loop approval for any remediation action

### 3.3 Byzantine Voting for Critical Alerts

For alerts classified as high severity, require 2-of-3 agreement before escalating to the human operator:

1. Suricata rule match (binary: yes/no)
2. LLM reasoning agent assessment (confidence score > 0.7)
3. Threat intel enrichment (AbuseIPDB score > 50 OR known bad ASN)

If fewer than 2 vote "alert," downgrade to informational log only.

### 3.4 VLAN Segmentation for IoT Devices

Once the threat model is clearer from Phase 2 observations:
- Move the Gaoshengda devices (.232 and .249) and any other IoT devices to a dedicated VLAN (e.g., VLAN 20, 192.168.20.0/24)
- Block IoT VLAN from accessing main LAN except specific allowed ports
- Add Zeek/Suricata rules for inter-VLAN traffic

The GA-78LMT-S2P's router must support VLAN tagging for this to work — verify capability before planning.

### 3.5 Human-in-the-Loop Approval

The LangChain agent never takes remediation actions autonomously. For any action beyond alerting (firewall rule addition, device block, DNS sinkhole), it:

1. Drafts the proposed action with full reasoning
2. Sends a WhatsApp message via NanoClaw with approve/reject options
3. Waits up to 30 minutes for a response
4. If no response: escalates to ntfy push notification, then logs as "pending — no action taken"

### 3.6 Full Audit Log in SMW

Every agent action, alert, vote result, and human decision is written to a structured SMW page under `AuditLog:YYYY-MM-DD/event-id`. Use the `#set` parser function to make all events queryable via SMW inline queries.

---

## Week-by-Week Summary

| Week | Focus | Done When |
|---|---|---|
| 1 | Fix vulns, deploy Prometheus/Grafana/LibreNMS/Zeek, wiki inventory | All 4 router issues closed, 29 devices in wiki, Grafana showing metrics |
| 2 | Suricata + NATS + discovery_agent + anomaly_agent | New device detection end-to-end works, WhatsApp alert received |
| 3 | threat_intel_agent, ntfy, full Grafana dashboards | AbuseIPDB enrichment working, all 29 devices on dashboards |
| 4 | Ollama + LangChain agent skeleton, Byzantine voting logic | LLM produces structured assessment from test alert input |
| 5 | Human-in-the-loop flow, VLAN planning/implementation | Approval workflow tested end-to-end with a simulated alert |
| 6 | Audit log in SMW, redundancy tuning, documentation | All events queryable in wiki, false positive rate acceptable |
