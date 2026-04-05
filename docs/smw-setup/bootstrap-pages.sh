#!/bin/bash
# =========================================================
# Bootstrap NanoClaw Knowledge Base with initial pages
# Run AFTER setup.sh completes successfully
# =========================================================

WIKI_DIR="$HOME/nanoclaw-wiki"
cd "$WIKI_DIR"

# Helper function to create a wiki page
create_page() {
    local title="$1"
    local content="$2"
    echo "$content" | docker compose exec -T mediawiki php maintenance/edit.php \
        --user=Admin \
        --summary="Bootstrap: initial page creation" \
        "$title"
    echo "✅ Created: $title"
}

echo "=== Bootstrapping NanoClaw Knowledge Base ==="
echo ""

# =========================================================
# MAIN HUB PAGE
# =========================================================
create_page "Main Page" '== NanoClaw Knowledge Base ==

Welcome to the living knowledge graph of everything [[User:Javastarchild|javastarchild]] and Andy have built together.

=== Active Projects ===
{{#ask: [[Category:Project]] [[Has status::Active]]
| ?Has goal
| ?Started on
| ?Has repository
| format=table
| headers=show
}}

=== All Projects ===
{{#ask: [[Category:Project]]
| ?Has status
| ?Uses technology
| format=table
}}

=== Open Issues (All Projects) ===
{{#ask: [[Category:Issue]] [[Has status::Open]]
| ?Belongs to project
| ?Has priority
| format=table
| sort=Has priority
}}
'

# =========================================================
# PROJECT TEMPLATE
# =========================================================
create_page "Template:Project" '== {{{name|{{PAGENAME}}}}} ==

; Status: [[Has status::{{{status|Active}}}]]
; Started: [[Started on::{{{started|}}}]]
; Goal: [[Has goal::{{{goal|}}}]]
; Repository: [[Has repository::{{{repo|}}}]]
; Technologies: [[Uses technology::{{{tech|}}}]]
; Related to: [[Related to::{{{related|}}}]]

[[Category:Project]]
'

# =========================================================
# PROJECT: NETWORK SECURITY AUDIT
# =========================================================
create_page "Project:Network Security Audit" '{{Project
|name=Home Network Security Audit
|status=Active
|started=2026-03-22
|goal=Identify and remediate vulnerabilities in home network
|tech=Nmap, Masscan, Linux
|related=Project:NanoClaw
}}

== Summary ==
Comprehensive security audit of home network (192.168.1.0/24) conducted with Andy (NanoClaw AI). Discovered 29 devices, multiple critical vulnerabilities.

== Key Findings ==

=== Critical ===
* [[Issue:Open DNS Resolver]] — Router acting as public DNS relay on 108.28.53.181
* [[Issue:Router Admin Exposed]] — Verizon router admin panel open to internet (ports 80,443,8080,8443)
* [[Issue:Unknown Device 192.168.1.57]] — SOCKS5 proxy with no authentication

=== High ===
* [[Issue:MyQ Garage Exposed]] — Garage door opener HTTP interface accessible on local network
* [[Issue:No IoT Segmentation]] — All 29 devices on single flat network

=== Devices Discovered ===
{{#ask: [[Category:NetworkDevice]] [[Belongs to project::Project:Network Security Audit]]
| ?Has IP
| ?Has vendor
| ?Has risk level
| format=table
}}

== Open Issues ==
{{#ask: [[Category:Issue]] [[Belongs to project::Project:Network Security Audit]] [[Has status::Open]]
| ?Has priority
| format=ul
}}

[[Category:Project]]
'

# =========================================================
# PROJECT: STOCK PICKER
# =========================================================
create_page "Project:Stock Picker" '{{Project
|name=AI Stock Analysis Pipeline
|status=Active
|started=2026-03-31
|goal=Automated S&P 500 stock screening with SARIMAX forecasting and sentiment analysis
|repo=https://github.com/javastarchild/stock_picker_nanoclaw
|tech=Python, pandas, statsmodels, yfinance, NLTK VADER, NewsAPI
|related=Project:NanoClaw
}}

== Summary ==
Multi-agent pipeline that screens S&P 500 stocks by GICS sector, downloads price history via yfinance, scores news sentiment using VADER, and fits SARIMAX models to generate 7-30 day price forecasts.

== Architecture ==
* '''DataSourceAgent''' — fetches S&P 500 constituents (Wikipedia → GitHub CSV fallback)
* '''StockDataAgent''' — downloads OHLCV via yfinance
* '''NewsAgent''' — fetches articles via NewsAPI
* '''SentimentAgent''' — VADER sentiment scoring
* '''ForecastAgent''' — SARIMAX(1,1,1) model with sentiment as exogenous variable
* '''ReportAgent''' — generates CSV + summary reports

== Prediction Accuracy Log ==
{{#ask: [[Category:PredictionResult]] [[Belongs to project::Project:Stock Picker]]
| ?Has ticker
| ?Has date
| ?Has predicted price
| ?Has actual price
| ?Has error percent
| format=table
| sort=Has date
| order=desc
}}

== Automation ==
* Daily ANET accuracy check: Mon-Fri 4:30pm ET
* Weekly IT sector refresh: Mondays 7am ET
* Nightly GitHub auto-save: 11pm ET

[[Category:Project]]
'

# =========================================================
# PROJECT: NANOCLAW
# =========================================================
create_page "Project:NanoClaw" '{{Project
|name=NanoClaw AI Assistant
|status=Active
|started=2026-03-22
|goal=Personal AI assistant with persistent memory, scheduled tasks, and skill system
|repo=https://github.com/javastarchild/nanoclaw-state
|tech=Claude (Anthropic), Node.js, Docker, WhatsApp, SemanticMediaWiki
|related=Project:Stock Picker, Project:Network Security Audit
}}

== Summary ==
NanoClaw is a personal AI assistant powered by Claude (Anthropic) running locally via Docker. It maintains persistent memory, runs scheduled tasks, and communicates via WhatsApp.

== Key Capabilities ==
* Scheduled tasks (cron + one-time)
* Persistent group memory (CLAUDE.md files)
* Skill system (stock-picker, agent-browser, capabilities, status)
* GitHub state auto-save
* SemanticMediaWiki knowledge base management

== Installed Skills ==
{{#ask: [[Category:Skill]] [[Belongs to project::Project:NanoClaw]]
| ?Has description
| format=table
}}

== Automation Schedule ==
* 8:00am daily: Morning briefing
* Mon-Fri 4:30pm: ANET stock check
* Monday 7:00am: IT sector forecast
* 11:00pm nightly: GitHub auto-save

[[Category:Project]]
'

# =========================================================
# ISSUE PAGES
# =========================================================
create_page "Issue:Open DNS Resolver" '[[Has status::Open]] [[Has priority::Critical]] [[Belongs to project::Project:Network Security Audit]]

== Description ==
Verizon Fios Quantum Gateway router at public IP 108.28.53.181 is responding to DNS queries from the open internet, making it an open DNS resolver.

== Evidence ==
<pre>
dig @108.28.53.181 google.com
;; Got answer — status: NOERROR, 6 answers returned
</pre>

== Risk ==
* Can be used in DNS amplification DDoS attacks against third parties
* IP may be blacklisted by ISPs and security organizations
* Verizon could terminate service for abuse

== Fix ==
Log into http://192.168.1.1 → Firewall → Block inbound port 53 from WAN

[[Category:Issue]]
'

create_page "Issue:Router Admin Exposed" '[[Has status::Open]] [[Has priority::Critical]] [[Belongs to project::Project:Network Security Audit]]

== Description ==
Verizon Fios Quantum Gateway router admin panel is publicly accessible on 4 ports from the open internet.

== Evidence ==
<pre>
nmap -sV 108.28.53.181
80/tcp   open  http        (Verizon Router admin)
443/tcp  open  ssl/https   (Verizon Router admin)
8080/tcp open  http-proxy  (Verizon Router admin)
8443/tcp open  ssl/https   (Verizon Router admin)
</pre>

== Fix ==
http://192.168.1.1 → Advanced → Remote Administration → Disable

[[Category:Issue]]
'

create_page "Issue:Unknown Device 192.168.1.57" '[[Has status::Open]] [[Has priority::High]] [[Belongs to project::Project:Network Security Audit]]

== Description ==
Unknown device at 192.168.1.57 running a SOCKS5 proxy on port 1080 with no authentication. MAC address 10:BF:67:40:A0:09 (unknown vendor).

== Evidence ==
<pre>
PORT     STATE SERVICE
1080/tcp open  socks5 (No authentication)
8888/tcp open  tcpwrapped
OS: Linux 3.2-4.9
</pre>

== Testing ==
* curl --socks5 192.168.1.57:1080 http://ifconfig.me → FAILED (proxy non-functional)
* curl --socks5 192.168.1.57:1080 http://192.168.1.1 → FAILED

== Status ==
Proxy accepts connections but cannot forward traffic. Device identity unknown.

== Next Steps ==
* Physical inspection of all devices
* curl http://192.168.1.57 — check for web interface
* MAC vendor lookup: 10:BF:67

[[Category:Issue]]
'

echo ""
echo "=========================================="
echo "✅ Knowledge Base bootstrapped!"
echo "=========================================="
echo ""
echo "  🌐 Visit: http://localhost:8080"
echo "  📖 Main page shows all projects"
echo "  🔍 Semantic queries auto-populate tables"
echo ""
