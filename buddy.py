"""Claude-Buddy: schickt den Arbeitszustand von Claude Code an das T-Display-S3.

Aufrufe:
  python buddy.py hook            (von den Claude-Code-Hooks, liest JSON von stdin)
  python buddy.py send <zustand> [detail]   zum Testen, z.B.  send write datei.cpp
  python buddy.py demo            alle Animationen nacheinander
  python buddy.py demo2           Beschaeftigungen, Feiern und lange Arbeit
  python buddy.py act <name>      yawn, stretch, yoyo, book, water, bubble, whistle
  python buddy.py party <sek>     Feier testen (unter 60 nicken, bis 300 Konfetti, darueber Feuerwerk)
  python buddy.py long <min>      lange Arbeit testen (ab 5 Schweiss, 10 Kaffee, 15 Dampf)
  python buddy.py wifi            WLAN-Zugang ueber USB ins Geraet schreiben
  python buddy.py find            Geraet suchen, Verbindung pruefen
  python buddy.py update          Buddy sofort nach neuer Firmware suchen lassen
  python buddy.py install         Hooks in Claude Code eintragen (~/.claude/settings.json)
  python buddy.py uninstall       Hooks wieder entfernen

Verbindung: zuerst USB (Espressif-Port), sonst WLAN (IP aus config.json).
"""
import json
import os
import sys
import time

HERE = os.path.dirname(os.path.abspath(__file__))
CFG_FILE = os.path.join(HERE, "config.json")
ESPRESSIF_VID = 0x303A


def load_cfg():
    try:
        with open(CFG_FILE, encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return {}


def save_cfg(cfg):
    try:
        with open(CFG_FILE, "w", encoding="utf-8") as f:
            json.dump(cfg, f, indent=2)
    except Exception:
        pass


def ascii_only(s, n=44):
    s = str(s or "")
    for a, b in (("ä", "ae"), ("ö", "oe"), ("ü", "ue"), ("Ä", "Ae"), ("Ö", "Oe"), ("Ü", "Ue"), ("ß", "ss")):
        s = s.replace(a, b)
    s = " ".join(s.split())
    s = "".join(c for c in s if 32 <= ord(c) < 127 and c != "|")
    return s[:n]


def open_port(port):
    import serial
    s = serial.Serial()
    s.port = port
    s.baudrate = 115200
    s.timeout = 0.3
    s.write_timeout = 0.5
    s.dtr = False  # sonst startet der ESP32-S3 beim Oeffnen neu
    s.rts = False
    s.open()
    return s


def find_ports():
    try:
        from serial.tools import list_ports
        return [p.device for p in list_ports.comports() if p.vid == ESPRESSIF_VID]
    except Exception:
        return []


def send_line(line):
    """Schickt eine Zeile; True wenn es geklappt hat."""
    cfg = load_cfg()
    data = (line + "\n").encode("ascii", "replace")
    ports = []
    if cfg.get("port"):
        ports.append(cfg["port"])
    for attempt in range(2):
        for p in ports:
            for _ in range(3):  # Port kann kurz von einem anderen Hook belegt sein
                try:
                    s = open_port(p)
                    s.write(data)
                    s.flush()
                    s.close()
                    if cfg.get("port") != p:
                        cfg["port"] = p
                        save_cfg(cfg)
                    return True
                except Exception as e:
                    if "PermissionError" in repr(e) or "Zugriff" in str(e):
                        time.sleep(0.05)
                        continue
                    break
        if attempt == 0:
            ports = [p for p in find_ports() if p not in ports]
            if not ports:
                break
    # WLAN
    host = cfg.get("host")
    if line.startswith("S "):
        import urllib.parse, urllib.request
        f = line[2:].split("|")
        f += [""] * (5 - len(f))
        q = urllib.parse.urlencode({"st": f[0], "d": f[1], "t": f[2], "sid": f[3], "p": f[4]})
        if host:
            try:
                urllib.request.urlopen("http://%s/s?%s" % (host, q), timeout=0.6).read()
                return True
            except Exception:
                pass
        # IP hat sich evtl. geaendert (DHCP): ueber den mDNS-Namen neu suchen
        try:
            import socket
            ip = socket.gethostbyname("claude-buddy.local")
            if ip and ip != host:
                urllib.request.urlopen("http://%s/s?%s" % (ip, q), timeout=0.6).read()
                cfg["host"] = ip
                save_cfg(cfg)
                return True
        except Exception:
            pass
    return False


LOG_FILE = os.path.join(HERE, "hook.log")
LOG_SESSION = ""


def log(msg):
    """Kurzes Protokoll (pc/hook.log), wird bei 200 kB abgeschnitten."""
    try:
        if os.path.exists(LOG_FILE) and os.path.getsize(LOG_FILE) > 200000:
            os.replace(LOG_FILE, LOG_FILE + ".alt")
        with open(LOG_FILE, "a", encoding="utf-8") as f:
            f.write("%s %s %s\n" % (time.strftime("%H:%M:%S"), LOG_SESSION[:8], msg))
    except Exception:
        pass


def send_state(state, detail="", sid="", proj=""):
    # Zeitstempel: Hooks laufen parallel, das Geraet verwirft veraltete Meldungen
    ts = int(time.time() * 1000) & 0xFFFFFFFF
    t0 = time.time()
    ok = send_line("S %s|%s|%d|%s|%s" % (state, ascii_only(detail), ts, ascii_only(sid, 12), ascii_only(proj, 19)))
    log("%-6s %-24s %s %dms" % (state, ascii_only(detail, 24), "ok" if ok else "FEHLER", (time.time() - t0) * 1000))
    return ok


# ----------------------------------------------------------------- Hook-Auswertung
READ_TOOLS = {"Read", "NotebookRead"}
SEARCH_TOOLS = {"Grep", "Glob", "ToolSearch", "LS"}
WRITE_TOOLS = {"Edit", "Write", "MultiEdit", "NotebookEdit"}
RUN_TOOLS = {"Bash", "PowerShell", "BashOutput", "Monitor"}
WEB_TOOLS = {"WebFetch", "WebSearch"}
AGENT_TOOLS = {"Agent", "Task", "SendMessage"}
ASK_TOOLS = {"AskUserQuestion", "ExitPlanMode"}


def base(p):
    return os.path.basename(str(p or "").rstrip("/\\")) or str(p or "")


def tool_state(name, inp):
    inp = inp or {}
    if name in READ_TOOLS:
        return "read", base(inp.get("file_path") or inp.get("notebook_path"))
    if name in WRITE_TOOLS:
        return "write", base(inp.get("file_path") or inp.get("notebook_path"))
    if name in SEARCH_TOOLS:
        return "search", inp.get("pattern") or inp.get("query") or ""
    if name in RUN_TOOLS:
        return "run", inp.get("description") or inp.get("command") or ""
    if name in WEB_TOOLS:
        if inp.get("url"):
            import urllib.parse
            return "web", urllib.parse.urlparse(inp["url"]).netloc
        return "web", inp.get("query") or ""
    if name in AGENT_TOOLS:
        return "agent", inp.get("description") or ""
    if name in ASK_TOOLS:
        return "ask", "Plan fertig" if name == "ExitPlanMode" else ""
    if name.startswith("mcp__"):
        parts = name.split("__")
        tool = parts[-1]
        if "browser" in name.lower() or "chrome" in name.lower():
            return "web", tool
        return "run", tool
    if name in ("TodoWrite", "TaskCreate", "TaskUpdate"):
        return "think", "plane"
    return "think", name


def handle_hook():
    try:
        ev = json.loads(sys.stdin.buffer.read().decode("utf-8", "replace") or "{}")
    except Exception:
        ev = {}
    global LOG_SESSION
    LOG_SESSION = str(ev.get("session_id", ""))
    name = ev.get("hook_event_name", "")
    cwd = base(ev.get("cwd", ""))
    sid = str(ev.get("session_id", ""))[:8]  # jede Claude-Code-Sitzung bekommt am Buddy eine eigene Figur

    def send(st, d=""):
        send_state(st, d, sid, cwd)
    if name == "SessionStart":
        send("hello")
    elif name == "UserPromptSubmit":
        send("think")
    elif name == "PreToolUse":
        st, d = tool_state(ev.get("tool_name", ""), ev.get("tool_input"))
        send(st, d)
    elif name == "PostToolUse":
        send("think")
    elif name == "PostToolUseFailure":
        send("oops", ev.get("tool_name", ""))  # Befehl ist fehlgeschlagen: kurzer Schreck
    elif name == "Notification":
        msg = str(ev.get("message", ""))
        ntype = str(ev.get("notification_type", ""))
        if "permission" in ntype or "permission" in msg.lower() or "erlaubnis" in msg.lower():
            send("need")
        elif "idle" in ntype or "waiting" in msg.lower():
            send("wait")
        else:
            send("need")
    elif name == "Stop":
        send("done")
    elif name == "SessionEnd":
        send("bye")
    # Hooks duerfen Claude nie aufhalten
    sys.exit(0)


# ----------------------------------------------------------------- Werkzeuge
def demo():
    seq = [("hello", "Demo"), ("think", ""), ("read", "ClaudeBuddy.cpp"), ("search", "drawCharacter"),
           ("write", "ClaudeBuddy.cpp"), ("run", "pio run -t upload"), ("web", "docs.lilygo.cc"),
           ("agent", "Helfer suchen"), ("think", ""), ("ask", "Welche Farbe?"), ("need", "Erlaubnis noetig"),
           ("oops", "Test"), ("done", "Demo"), ("wait", ""), ("sleep", "")]
    for st, d in seq:
        ok = send_state(st, d)
        print("%-7s %-22s %s" % (st, d, "ok" if ok else "NICHT erreicht"))
        time.sleep(5)


def demo2():
    steps = [("A yawn", 4), ("A stretch", 5), ("A yoyo", 8), ("A book", 9), ("A water", 7), ("A bubble", 7),
             ("A whistle", 6), ("L 6", 5), ("L 11", 5), ("L 16", 6), ("D 20", 8), ("D 120", 8), ("D 400", 12)]
    for cmd, wait in steps:
        ok = send_line(cmd)
        print("%-10s %s" % (cmd, "ok" if ok else "NICHT erreicht"))
        time.sleep(wait)
    send_state("idle", "")


HOOK_EVENTS = ["SessionStart", "UserPromptSubmit", "PreToolUse", "PostToolUse", "PostToolUseFailure", "Notification", "Stop", "SessionEnd"]


def settings_path():
    return os.path.join(os.path.expanduser("~"), ".claude", "settings.json")


def install():
    """Traegt die Hooks fuer alle Claude-Code-Sitzungen ein (bestehende Einstellungen bleiben erhalten)."""
    p = settings_path()
    data = {}
    if os.path.exists(p):
        with open(p, encoding="utf-8") as f:
            data = json.load(f)
        with open(p + ".vor-buddy", "w", encoding="utf-8") as f:
            json.dump(data, f, indent=2)
    me = os.path.abspath(__file__).replace("\\", "/")
    py = "python" if os.name == "nt" else "python3"
    cmd = '%s "%s" hook' % (py, me)
    hooks = data.setdefault("hooks", {})
    for ev in HOOK_EVENTS:
        groups = hooks.setdefault(ev, [])
        groups[:] = [g for g in groups if not any("buddy.py" in h.get("command", "") for h in g.get("hooks", []))]
        h = {"type": "command", "command": cmd, "timeout": 5}
        if ev != "SessionEnd":
            h["async"] = True  # Claude wartet nicht auf den Buddy
        g = {"hooks": [h]}
        if ev in ("PreToolUse", "PostToolUse", "PostToolUseFailure"):
            g["matcher"] = "*"
        groups.append(g)
    os.makedirs(os.path.dirname(p), exist_ok=True)
    with open(p, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=2)
    print("Hooks eingetragen in", p)
    print("Neue Claude-Code-Sitzungen melden sich jetzt beim Buddy.")
    try:
        import serial  # noqa: F401
    except ImportError:
        print("Hinweis: Fuer USB bitte noch  pip install pyserial  ausfuehren (WLAN geht auch ohne).")


def uninstall():
    p = settings_path()
    if not os.path.exists(p):
        print("Keine Einstellungen gefunden."); return
    with open(p, encoding="utf-8") as f:
        data = json.load(f)
    hooks = data.get("hooks", {})
    for ev in list(hooks):
        hooks[ev] = [g for g in hooks[ev] if not any("buddy.py" in h.get("command", "") for h in g.get("hooks", []))]
        if not hooks[ev]:
            del hooks[ev]
    if not hooks:
        data.pop("hooks", None)
    with open(p, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=2)
    print("Buddy-Hooks entfernt.")


def query_device():
    for p in ([load_cfg().get("port")] if load_cfg().get("port") else []) + find_ports():
        try:
            s = open_port(p)
            s.reset_input_buffer()
            s.write(b"?\n")
            s.flush()
            t = time.time()
            buf = b""
            while time.time() - t < 1.5:
                buf += s.read(64)
                if b"BUDDY" in buf and b"\n" in buf.split(b"BUDDY", 1)[1]:
                    break
            s.close()
            txt = buf.decode("ascii", "replace")
            if "BUDDY" in txt:
                parts = txt.split("BUDDY", 1)[1].splitlines()[0].split()  # "<ip oder -> v<version>"
                global DEVICE_VERSION
                DEVICE_VERSION = parts[1] if len(parts) > 1 else "v1"
                return p, (parts[0] if parts else "-")
        except Exception:
            pass
    return None, None


DEVICE_VERSION = "?"


def find():
    port, ip = query_device()
    cfg = load_cfg()
    if port:
        cfg["port"] = port
        if ip and ip != "-":
            cfg["host"] = ip
        save_cfg(cfg)
        print("Gefunden an %s, WLAN: %s, Firmware %s" % (port, ip, DEVICE_VERSION))
    else:
        print("Kein Buddy per USB gefunden.", "WLAN-Adresse: %s" % cfg.get("host") if cfg.get("host") else "")


def wifi():
    import getpass
    ssid = input("WLAN-Name (leer = WLAN aus): ").strip()
    pw = getpass.getpass("Passwort: ") if ssid else ""
    if not send_line("W %s|%s" % (ssid, pw)):
        print("Geraet nicht erreicht (USB angeschlossen?)")
        return
    print("Gespeichert, warte auf Verbindung ...")
    for _ in range(15):
        time.sleep(1.5)
        port, ip = query_device()
        if ip and ip != "-":
            cfg = load_cfg()
            cfg["host"] = ip
            save_cfg(cfg)
            print("Verbunden: %s  (jetzt klappt es auch ohne USB-Datenverbindung)" % ip)
            return
    print("Noch keine Verbindung - Name/Passwort pruefen (nur 2,4-GHz-WLAN).")


if __name__ == "__main__":
    cmd = sys.argv[1] if len(sys.argv) > 1 else "hook"
    if cmd == "hook":
        try:
            handle_hook()
        except SystemExit:
            raise
        except Exception:
            sys.exit(0)
    elif cmd == "send":
        ok = send_state(sys.argv[2], " ".join(sys.argv[3:]))
        print("ok" if ok else "Geraet nicht erreicht")
    elif cmd == "demo":
        demo()
    elif cmd == "demo2":
        demo2()
    elif cmd == "act":
        print("ok" if send_line("A " + sys.argv[2]) else "Geraet nicht erreicht")
    elif cmd == "party":
        print("ok" if send_line("D " + sys.argv[2]) else "Geraet nicht erreicht")
    elif cmd == "long":
        print("ok" if send_line("L " + sys.argv[2]) else "Geraet nicht erreicht")
    elif cmd == "wifi":
        wifi()
    elif cmd == "find":
        find()
    elif cmd == "update":
        print("ok - der Buddy sucht jetzt nach einem Update" if send_line("U") else "Geraet nicht erreicht")
    elif cmd == "install":
        install()
    elif cmd == "uninstall":
        uninstall()
    else:
        print(__doc__)
