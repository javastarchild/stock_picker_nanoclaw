{{Project
| name       = Agentic Home Network Monitor
| status     = Active
| start_date = April 2026
| owner      = javastarchild
}}

== Overview ==

The '''Agentic Home Network Monitor''' (AHNM) is a phased home lab project to build a fully agentic, self-monitoring network security system on top of the existing 29-device home network (192.168.1.0/24). It combines open-source monitoring and detection tools with NanoClaw skill-based agents and a local LLM reasoning layer.

The system progresses from basic visibility and vulnerability remediation (Phase 1) through automated detection and alerting (Phase 2) to a full agentic layer with redundancy, local AI reasoning, and human-in-the-loop remediation approval (Phase 3).

== Phases ==

{| class="wikitable"
! Phase !! Timeframe !! Key Tools !! Status
|-
| Phase 1 — Fix & Watch || Week 1 || Prometheus, Grafana, LibreNMS, Zeek || In Progress
|-
| Phase 2 — Detect & Alert || Weeks 2–3 || Suricata, NATS, NanoClaw agents, ntfy || Planned
|-
| Phase 3 — Agentic Layer || Weeks 4–6 || Ollama, LangChain, Byzantine voting, VLAN segmentation || Planned
|}

== Architecture ==

AHNM is structured around a 7-layer model:

{| class="wikitable"
! Layer !! Name !! Description
|-
| 1 || Data Collection || Raw network traffic capture and SNMP polling (Zeek, LibreNMS, node_exporter)
|-
| 2 || Storage || Time-series metrics (Prometheus) and structured logs (Zeek EVE JSON)
|-
| 3 || Detection || Rule-based intrusion detection (Suricata) and traffic analysis (Zeek scripts)
|-
| 4 || Message Bus || Async event routing between agents via NATS JetStream
|-
| 5 || Skill Agents || Python scripts for discovery, anomaly detection, and threat intel enrichment
|-
| 6 || Reasoning || LangChain agent with local Ollama/Mistral-7B for structured threat assessment
|-
| 7 || Knowledge Base || SemanticMediaWiki as the living inventory, audit log, and decision record
|}

== OSS Stack (Phase 1) ==

* '''Prometheus''' — metrics collection and storage
* '''Grafana''' — metrics dashboards and alerting
* '''node_exporter''' — Ubuntu host system metrics
* '''LibreNMS''' — device inventory, SNMP polling, autodiscovery
* '''Zeek''' — passive traffic metadata and connection logging
* '''nmap''' / '''masscan''' — on-demand scanning (already installed)
* '''SemanticMediaWiki''' — knowledge base and device inventory (already running at localhost:8080)

== Related Issues ==

* [[Issue:Open DNS Resolver]] — port 53 exposed on WAN interface
* [[Issue:Router Admin Exposed]] — admin UI reachable on ports 80, 443, 8080, 8443
* [[Issue:Unknown Device 192.168.1.57]] — unidentified device on LAN, under investigation

== Related Projects ==

* [[Project:Network Security Audit]]

[[Category:Projects]] [[Category:Infrastructure]] [[Category:Security]]
