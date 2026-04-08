# IoT VLAN Segmentation Plan
## Verizon Fios G3100 (BHR5)

**Status:** Planning
**Last updated:** 2026-04-08
**Goal:** Isolate Ring, MyQ, Wyze cameras, and other IoT devices from the main LAN without breaking cloud access.

---

## Context

The G3100 was set to "Maximum Security" firewall mode — Ring doorbell, MyQ garage opener, and Wyze cameras all stopped working. Reverted to "Typical" to restore function. **Root cause:** those devices need outbound internet access to their cloud services, which Maximum Security blocked. The correct long-term fix is network segmentation — not a looser firewall — so IoT devices get internet access but cannot reach or be reached from the main LAN.

---

## Critical Finding: The G3100's "IoT SSID" Is Not Isolated

⚠️ Despite Verizon labeling a third SSID as "IoT," devices on it receive `192.168.1.x` addresses and **can communicate freely with all main LAN devices**. It exists for Verizon's SON (Self-Organizing Network) feature, not security isolation.

**Do not use the IoT SSID for security isolation.**

---

## The Actual Isolation Option: Guest SSID

The G3100's **Guest Network SSID** uses VLAN 10 internally and places devices on a separate subnet:

| Network | Subnet | Gateway | Isolation |
|---------|--------|---------|-----------|
| Primary LAN | 192.168.1.0/24 | 192.168.1.1 | — |
| Guest / IoT SSID | 192.168.200.0/24 | 192.168.200.1 | ✅ Isolated |
| IoT SSID (Verizon-labeled) | 192.168.1.0/24 | 192.168.1.1 | ❌ NOT isolated |

Guest network devices:
- ✅ Have full internet access
- ✅ Cannot reach 192.168.1.x devices
- ✅ Cannot be reached from 192.168.1.x devices
- ✅ Ring, MyQ, Wyze will work (cloud access intact)

---

## Implementation Steps

### Step 1 — Enable and Name the Guest Network
1. Log into `https://192.168.1.1` → Proceed → log in
2. Navigate to **WiFi** → **Guest Network**
3. Enable the Guest Network
4. Set SSID name: `NanoClaw-IoT` (or similar to distinguish from main)
5. Set a strong password (different from main WiFi)
6. Verify "Guest network isolation" is enabled (it should be by default)

### Step 2 — Move IoT Devices to Guest SSID

Priority devices to migrate (these caused the firewall issue):

| Device | Type | Move to IoT SSID |
|--------|------|-----------------|
| Ring doorbell | Camera/doorbell | ✅ Yes |
| MyQ garage opener | Smart home | ✅ Yes |
| Wyze cameras | Camera | ✅ Yes |
| Gaoshengda device (.232) | Unknown — likely smart home | ✅ Yes |
| Gaoshengda device (.249) | Unknown — likely smart home | ✅ Yes |

For each device: go into its app settings → change WiFi network → connect to `NanoClaw-IoT`.

### Step 3 — Identify Gaoshengda Devices Before or During Migration

Gaoshengda Technology is a Chinese OEM chip manufacturer. Their modules appear in:
- Roku smart home accessories (plugs, bulbs, cameras)
- Smart plugs / light strips (various brands)
- Generic Tuya-platform devices

**To identify them:** Check your router's DHCP client list for hostnames at .232 and .249. Cross-reference against recently added smart home devices. Move them to the IoT SSID regardless — they should be there either way.

### Step 4 — Verify Isolation Works
After migration, from a main LAN device, try to ping 192.168.200.x — should time out. Verify Ring/MyQ/Wyze apps still function normally (they will, via internet).

### Step 5 — Re-enable Maximum Security (Optional, Later)
Once IoT devices are on the Guest SSID and confirmed working, you can revisit Maximum Security on the primary network. The G3100's firewall modes apply primarily to WAN-initiated connections; IoT devices on the Guest SSID will continue to initiate outbound connections to their cloud services regardless of the primary LAN firewall setting.

---

## Wired IoT Devices (Future)

If you ever need to isolate wired devices (e.g., a wired smart TV or NVR), the G3100 does not support wired VLAN assignment natively. Options:
- **Managed switch** (e.g., Netgear GS308E ~$35, or Unifi) — configure a port as untagged on VLAN 10 to land on the Guest subnet
- **Firewalla** — plugs into G3100 LAN port, provides richer segmentation and firewall rules without double-NAT

---

## Open Items

- [ ] Identify Gaoshengda devices (.232, .249) by hostname/app
- [ ] Enable and configure Guest SSID
- [ ] Migrate Ring, MyQ, Wyze to Guest SSID
- [ ] Migrate Gaoshengda devices to Guest SSID
- [ ] Test isolation (ping test from main LAN)
- [ ] Verify Ring/MyQ/Wyze still functional on new SSID
- [ ] Consider managed switch for wired IoT (NVR, etc.) — future phase
