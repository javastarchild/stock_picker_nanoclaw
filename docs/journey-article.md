# From Zero to AI-Powered Home Security & Stock Analysis: A Journey with NanoClaw

*By javastarchild | April 2026*

---

## The Beginning

It started simply enough. One evening in late March 2026, I opened a chat with my AI assistant — Andy, powered by Claude — and typed two words: *"Are you ready to get to work?"*

What followed was one of the most productive and eye-opening technical journeys I've undertaken. Over the course of two weeks, Andy and I tackled two ambitious projects simultaneously: a comprehensive home network security audit, and a fully automated AI-powered stock analysis pipeline. This is the story of that journey.

---

## Part 1: Securing the Home Network

### Discovery — What's Really on Your Network?

Most people assume their home network is secure. I was one of them. The first thing Andy suggested was a full network discovery scan using Nmap:

```bash
sudo nmap -sn 192.168.1.0/24
```

The results were sobering. **29 devices** were active on my network — many of which I couldn't immediately identify. Among them: multiple Amazon devices, three Wyze security cameras, a Ring doorbell, a MyQ garage door opener, several Roku TVs, a Google Home Mini, a Pioneer AV receiver, and two devices from a Chinese manufacturer called Hui Zhou Gaoshengda Technology.

But one device stood out immediately: **192.168.1.57** — unknown vendor, unknown name, running a SOCKS5 proxy on port 1080 with *no authentication*.

### The SOCKS5 Mystery

A SOCKS5 proxy with no authentication on a home network is a serious red flag. It could mean a compromised device, a rogue access point, or someone deliberately running a proxy. Andy walked me through a methodical investigation:

```bash
curl --socks5 192.168.1.57:1080 http://ifconfig.me
```

The proxy accepted connections but couldn't forward traffic — either misconfigured or intentionally sandboxed. While the immediate threat was contained, the device remained unidentified and suspicious.

### The Bigger Shock: The Router

While investigating the mystery device, Andy suggested scanning the router itself — both internally and from the outside. What we found was alarming:

**My Verizon Fios Quantum Gateway router had its admin panel exposed to the entire internet on four ports: 80, 443, 8080, and 8443.**

Anyone on the internet could attempt to log into my router's admin panel. But worse was yet to come. Testing the DNS service:

```bash
dig @108.28.53.181 google.com
```

The DNS query returned results. My router was acting as an **open DNS resolver** — publicly accessible to anyone on the internet. This is a known attack vector for DNS amplification DDoS attacks, where attackers send spoofed queries to open resolvers to flood victims with traffic. My home IP could be used as a weapon.

### The Fix

The remediation required careful navigation of the Verizon router's admin panel. Andy explained clearly why the fixes wouldn't break streaming services (a concern I had), and we proceeded step by step:

1. **Disable remote management** — closing the admin panel to the internet
2. **Block WAN DNS access** — preventing the open resolver abuse
3. **Mount allowlist configuration** — securing additional services

The process wasn't without friction. A misconfigured `containerPath`, a missing `mount-allowlist.json` with required fields, and several bot restarts were needed before everything aligned. But that troubleshooting process itself was instructive — real security work is iterative.

### Remaining Concerns

The audit surfaced several issues still awaiting resolution:
- The unidentified device at 192.168.1.57
- No network segmentation (all IoT devices on the same flat network as computers)
- The MyQ garage door opener with an exposed HTTP interface
- Two Gaoshengda IoT devices requiring identification
- Wyze cameras with historical vulnerability records

---

## Part 2: Building an AI Stock Analysis Pipeline

### The Setup

Alongside the security work, I'd been building a stock analysis tool: a Python pipeline that fetches S&P 500 constituents, downloads price history via `yfinance`, scores news sentiment using VADER, fits SARIMAX forecasting models, and generates ranked reports.

Getting it running through Andy involved a multi-day deployment saga:

1. **Discovering the skill** — the `stock-picker` skill existed in the project but wasn't deployed to the active skills directory
2. **Mounting the directory** — configuring the NanoClaw container to access the stock picker scripts on the host machine
3. **Fixing the allowlist** — the mount security system required a properly formatted `~/.config/nanoclaw/mount-allowlist.json`
4. **Dependency hell** — numpy 2.x caused SIGILL crashes; pandas 3.x broke SARIMAX; the solution was numpy 1.26.4 + pandas 1.5.3

Every obstacle taught something new about how NanoClaw's containerized architecture works.

### The First Analysis: Information Technology

With everything wired up, I ran the first analysis on the Information Technology sector — 20 tickers, 6 months of price history, 7-day SARIMAX forecasts, with NewsAPI sentiment scoring.

The top pick: **ANET (Arista Networks)**

The model forecast +3.72% over 7 days — the strongest signal in the sector. The news sentiment backed it up: 11 positive articles, 0 negative, average sentiment score of +0.55.

### Validation: The Predictions Come True

The real test came the next two days:

| Date | Predicted | Actual | Error |
|------|-----------|--------|-------|
| Apr 1 | $123.49 | $124.85 | +1.10% ✅ |
| Apr 2 | $124.46 | $126.68 | +1.78% ✅ |

The model called the direction correctly and landed within 2% — impressive for a statistical time-series model with no deep learning. The stock was running *ahead* of the forecast, suggesting the sentiment signal was even stronger than the model captured.

### Automation

With the model validated, we automated everything:

- **Daily ANET accuracy check** at 4:30 PM ET, Monday–Friday — actual close vs prediction, error percentage, trend
- **Weekly IT sector refresh** every Monday at 7:00 AM — fresh 7-day forecasts for all 20 technology tickers, with a ranked summary

The pipeline now runs autonomously, delivering actionable intelligence without manual intervention.

---

## Reflections

### What Made This Work

A few things stand out about this collaboration:

**Persistence through friction.** Neither project was smooth. The network audit hit resistance from a cautious user (me) worried about breaking streaming services. The stock picker deployment required half a dozen restarts and configuration fixes. But Andy never lost the thread — each session picked up exactly where we left off.

**Genuine expertise.** The security advice wasn't generic. Andy knew that SOCKS5 error code 9 means "unassigned" in the RFC spec. It knew that numpy 2.x uses AVX-512 instructions that cause SIGILL on older CPUs. It knew the difference between a DNS amplification attack vector and a simple misconfiguration.

**The value of state.** One of the most valuable things about this setup is memory. Andy remembered the network scan results from two weeks ago. It remembered that the SOCKS5 proxy was non-functional. It remembered the exact predicted prices from the stock analysis. This continuity transforms a chatbot into a genuine collaborator.

### What's Next

The security audit is unfinished. The mystery device at 192.168.1.57 still needs identification. The network needs IoT segmentation — a VLAN separating cameras, smart plugs, and voice assistants from computers and phones. OpenVAS vulnerability scanning hasn't been run yet.

On the stock analysis side, the ANET 30-day forecast runs through mid-May. The weekly IT sector reports will accumulate data over time, eventually enabling backtesting and model refinement. The next step is expanding to other sectors — healthcare and energy are on the list.

And now, with a GitHub-backed state repository, none of this progress will be lost.

---

## Technical Stack

| Component | Technology |
|-----------|------------|
| AI Assistant | Claude (Anthropic) via NanoClaw |
| Network scanning | Nmap 7.80, Masscan |
| Stock data | yfinance 1.2.0 |
| Forecasting | statsmodels SARIMAX |
| Sentiment | NLTK VADER |
| News | NewsAPI |
| Scheduling | NanoClaw cron tasks |
| Language | Python 3.11 / pandas 1.5.3 / numpy 1.26.4 |
| Platform | Linux (Ubuntu 22.04) |

---

## Conclusion

Two weeks. Two projects. One AI assistant.

A home network that was quietly exposed to the internet is now being actively monitored and hardened. A stock analysis pipeline that didn't exist is now running autonomously, delivering weekly forecasts with validated accuracy.

The journey isn't over — it's just getting started.

---

*This article was written in collaboration with Andy (Claude, Anthropic). All scan results, predictions, and accuracy measurements are real.*
