"""Shared collection logic for TA-netqual (per-interface link quality)."""
import json
import os
import re
import sys

NET = "/sys/class/net"
_MAIN = sys.modules.get("__main__")
_STEM_SRC = getattr(_MAIN, "__file__", None) or (sys.argv[0] if sys.argv else "")
SCRIPT_STEM = re.sub(r"[^a-z0-9_]+", "_", os.path.splitext(os.path.basename(_STEM_SRC))[0].lower()).strip("_") or "netqual"
STATE_FILE = "/var/tmp/ta_netqual_state_%s.json" % SCRIPT_STEM

SKIP_RE = re.compile(r"^(lo|veth|docker|br-|br\d|cni|tap|virbr|kube|calix|flannel|ovs|qvm|lxd|nerdctl|wslc)")


def _read(path):
    try:
        with open(path) as fh:
            return fh.read().strip()
    except OSError:
        return None


def collect_iface(name):
    base = os.path.join(NET, name)
    rec = {}
    speed = _read(os.path.join(base, "speed"))
    try:
        speed_mbps = int(speed)
    except (TypeError, ValueError):
        speed_mbps = 0
    rec["speed_mbps"] = speed_mbps if speed_mbps > 0 else 0
    carrier = _read(os.path.join(base, "carrier"))
    rec["carrier"] = 1 if carrier == "1" else 0
    operstate = _read(os.path.join(base, "operstate")) or "unknown"
    rec["operstate"] = operstate
    rec["operstate_up"] = 1 if operstate in ("up", "unknown") and rec["carrier"] else 0
    mtu = _read(os.path.join(base, "mtu"))
    rec["mtu"] = int(mtu) if mtu else None
    rec["up"] = 1 if rec["carrier"] and operstate in ("up", "unknown") else 0
    stats = {}
    for k in ("rx_packets", "tx_packets", "rx_errors", "tx_errors", "rx_dropped", "tx_dropped", "rx_bytes", "tx_bytes"):
        v = _read(os.path.join(base, "statistics", k))
        if v is not None:
            try:
                stats[k] = int(v)
            except ValueError:
                pass
    rec["counters"] = stats
    return rec


def _load_state():
    try:
        with open(STATE_FILE) as fh:
            return json.load(fh).get("up", {})
    except (OSError, ValueError):
        return {}


def _save_state(current_up):
    try:
        os.makedirs(os.path.dirname(STATE_FILE), exist_ok=True)
        tmp = "%s.%d.tmp" % (STATE_FILE, os.getpid())
        with open(tmp, "w") as fh:
            json.dump({"up": current_up}, fh)
        os.replace(tmp, STATE_FILE)
    except OSError as exc:
        sys.stderr.write("TA-netqual: state write failed for %s: %s\n" % (STATE_FILE, exc))


def discover():
    try:
        names = sorted(n for n in os.listdir(NET) if not SKIP_RE.match(n))
    except OSError:
        names = []
    ifaces = {}
    for name in names:
        try:
            ifaces[name] = collect_iface(name)
        except Exception:
            continue
    prev = _load_state()
    flaps = []
    current_up = {}
    for name, rec in ifaces.items():
        current_up[name] = bool(rec.get("up"))
        if prev and prev.get(name, False) and not rec.get("up"):
            flaps.append(name)
            rec["link_flap"] = 1
    _save_state(current_up)
    status = "alarm" if flaps else "ok"
    return {
        "status": status,
        "iface_total": len(ifaces),
        "link_flaps": flaps,
        "ifaces": ifaces,
    }


def metrics_payload(data):
    payload = {"iface_total": data.get("iface_total", 0)}
    for name, rec in data.get("ifaces", {}).items():
        prefix = re.sub(r"[^a-z0-9]+", "_", name.lower()).strip("_")
        payload["%s_speed_mbps" % prefix] = rec.get("speed_mbps", 0)
        payload["%s_carrier" % prefix] = rec.get("carrier", 0)
        payload["%s_operstate_up" % prefix] = rec.get("operstate_up", 0)
        for k in ("rx_errors", "tx_errors", "rx_dropped", "tx_dropped"):
            if k in rec.get("counters", {}):
                payload["%s_%s" % (prefix, k)] = rec["counters"][k]
    return payload


def emit(payload):
    sys.stdout.write(json.dumps(payload, sort_keys=True) + "\n")
    sys.stdout.flush()


def fail(message):
    sys.stderr.write("TA-netqual collection error: %s\n" % message)
    return 1
