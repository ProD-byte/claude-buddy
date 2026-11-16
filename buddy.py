"""Claude-Buddy: schickt den Arbeitszustand von Claude Code an das T-Display-S3.

Aufrufe:
  python buddy.py hook            (von den Claude-Code-Hooks, liest JSON von stdin)
  python buddy.py send <zustand> [detail]   zum Testen, z.B.  send write datei.cpp
  python buddy.py demo            alle Animationen nacheinander
  python buddy.py demo2           Beschaeftigungen, Feiern und lange Arbeit
  python buddy.py act <name>      yawn, stretch, yoyo, book, water, bubble, whistle
  python buddy.py party <sek>     Feier testen (unter 60 nicken, bis 300 Konfetti, darueber Feuerwerk)
  python buddy.py long <min>      lange Arbeit testen (ab 5 Schweiss, 10 Kaffee, 15 Dampf)
  python buddy.py wifi            WLAN-Zugang ins Geraet schreiben (USB oder bestehendes WLAN)
  python buddy.py find            Geraet suchen, Verbindung pruefen
  python buddy.py bild <datei> [s] Bild als Polaroid zeigen, optional s Sekunden (braucht pillow)
  python buddy.py update          Buddy sofort nach neuer Firmware suchen lassen
  python buddy.py install         Hooks in Claude Code eintragen (~/.claude/settings.json)
  python buddy.py uninstall       Hooks wieder entfernen

Verbindung: zuerst USB (Espressif-Port), sonst WLAN (IP aus config.json, sonst claude-buddy.local).
Alle Befehle gehen auch per WLAN. Mit --wlan wird USB uebersprungen (zum Testen).
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


FORCE_WLAN = "--wlan" in sys.argv  # zum Testen: USB auslassen
if FORCE_WLAN:
    sys.argv.remove("--wlan")


def http(path, data=None, timeout=0.6):
    """Ruft http://<buddy>/<path> auf (IP aus config.json, sonst ueber claude-buddy.local).
    Gibt die Antwort als Text zurueck oder None."""
    import urllib.request
    cfg = load_cfg()
    host = cfg.get("host")
    hosts = [host] if host else []
    for attempt in range(2):
        for h in hosts:
            try:
                req = urllib.request.Request("http://%s%s" % (h, path), data=data,
                                             headers={"Content-Type": "text/plain"} if data else {})
                txt = urllib.request.urlopen(req, timeout=timeout).read().decode("ascii", "replace")
                if h != cfg.get("host"):
                    cfg["host"] = h
                    save_cfg(cfg)
                return txt
            except Exception:
                pass
        if attempt == 0:  # IP hat sich evtl. geaendert (DHCP): ueber den mDNS-Namen neu suchen
            try:
                import socket
                ip = socket.gethostbyname("claude-buddy.local")
            except Exception:
                return None
            hosts = [ip] if ip and ip != host else []
            if not hosts:
                return None
    return None


def send_line(line):
    """Schickt eine Zeile; True wenn es geklappt hat."""
    cfg = load_cfg()
    data = (line + "\n").encode("ascii", "replace")
    ports = []
    if cfg.get("port") and not FORCE_WLAN:
        ports.append(cfg["port"])
    for attempt in range(0 if FORCE_WLAN else 2):
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
    import urllib.parse
    if line.startswith("S "):  # Zustand ueber /s (kennt auch aeltere Firmware)
        f = line[2:].split("|")
        f += [""] * (5 - len(f))
        q = urllib.parse.urlencode({"st": f[0], "d": f[1], "t": f[2], "sid": f[3], "p": f[4]})
        return http("/s?" + q) is not None
    return http("/cmd?" + urllib.parse.urlencode({"l": line}), timeout=2) is not None  # alle anderen Befehle (ab v5)


# ----------------------------------------------------------------- Screenshots als Polaroid
IMG_W, IMG_H = 168, 104
IMAGE_EXT = (".png", ".jpg", ".jpeg", ".webp", ".gif", ".bmp")


def image_payload(img):
    """Pillow-Bild -> (Breite, Hoehe, Base64 der RGB565-Pixel, little endian)."""
    import base64
    img = img.convert("RGB")
    img.thumbnail((IMG_W, IMG_H))
    w, h = img.size
    px = img.tobytes()
    out = bytearray(w * h * 2)
    for i in range(w * h):
        r, g, b = px[3 * i], px[3 * i + 1], px[3 * i + 2]
        v = ((r & 0xF8) << 8) | ((g & 0xFC) << 3) | (b >> 3)
        out[2 * i] = v & 0xFF
        out[2 * i + 1] = v >> 8
    return w, h, base64.b64encode(bytes(out)).decode("ascii")


def send_image(img, caption="", secs=0):
    """Zeigt ein Bild als Polaroid auf dem Buddy (USB, sonst WLAN).
    secs > 0: so lange stehen lassen (geht nur ueber WLAN)."""
    try:
        w, h, b64 = image_payload(img)
    except Exception:
        return False
    cap = ascii_only(caption, 38)
    cfg = load_cfg()
    ports = ([cfg["port"]] if cfg.get("port") else []) + find_ports()
    for p in (dict.fromkeys(ports) if not (secs or FORCE_WLAN) else []):
        for _ in range(3):
            try:
                s = open_port(p)
                s.write_timeout = 3
                data = ("P %d %d %s|" % (w, h, cap)).encode("ascii") + b64.encode("ascii") + b"\n"
                for i in range(0, len(data), 2048):  # in Haeppchen, sonst laeuft der Empfangspuffer im Buddy ueber
                    s.write(data[i:i + 2048])
                    s.flush()
                    time.sleep(0.03)
                s.close()
                return True
            except Exception as e:
                if "PermissionError" in repr(e) or "Zugriff" in str(e):
                    time.sleep(0.05)
                    continue
                break
    import urllib.parse
    q = urllib.parse.urlencode({"w": w, "h": h, "c": cap, "s": int(secs)})
    return http("/img?" + q, data=b64.encode("ascii"), timeout=3) is not None


def find_image(obj, depth=0):
    """Sucht im Ergebnis eines Werkzeugs nach einem eingebetteten Bild (Base64)."""
    if depth > 6:
        return None
    if isinstance(obj, dict):
        if obj.get("type") == "image":
            data = obj.get("data") or (obj.get("source") or {}).get("data")
            if isinstance(data, str) and len(data) > 100:
                return data
        for v in obj.values():
            r = find_image(v, depth + 1)
            if r:
                return r
    elif isinstance(obj, list):
        for v in obj:
            r = find_image(v, depth + 1)
            if r:
                return r
    return None


def image_from_tool(name, inp, resp):
    """Liefert (Pillow-Bild, Titel), wenn das Werkzeug ein Bild angesehen oder einen Screenshot gemacht hat."""
    try:
        from PIL import Image
    except ImportError:
        return None, ""
    import base64, io
    inp = inp or {}
    path = str(inp.get("file_path") or "")
    if name == "Read" and path.lower().endswith(IMAGE_EXT) and os.path.exists(path):
        try:
            return Image.open(path), base(path)
        except Exception:
            return None, ""
    data = find_image(resp)
    if data:
        try:
            return Image.open(io.BytesIO(base64.b64decode(data))), "Screenshot"
        except Exception:
            pass
    return None, ""


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


import re

TEST_RE = re.compile(r"\b(pytest|unittest|jest|vitest|mocha|ctest|go test|cargo test|npm (run )?test|yarn test|pnpm test|pio test|gradle test|mvn test|phpunit|rspec)\b")
UPLOAD_RE = re.compile(r"(-t upload|--target upload|\besptool\b|arduino-cli upload|\bavrdude\b|idf\.py .*flash|\bpio run -e ota)")
BUILD_RE = re.compile(r"\b(pio run|platformio run|npm run build|yarn build|pnpm build|make\b|cmake --build|cargo build|go build|tsc\b|vite build|webpack|gradle build|mvn package|dotnet build|gcc|g\+\+|pip install|npm install|npm ci)")
DELETE_RE = re.compile(r"(^|[;&|]\s*)(rm|del|rmdir|rd|remove-item|git rm)\b")


def command_kind(cmd):
    """Ordnet einen Terminal-Befehl einer Taetigkeit zu (fuer die passende Animation)."""
    c = " ".join(str(cmd or "").lower().split())
    if re.search(r"\bgit commit\b", c):
        return "commit"
    if re.search(r"\bgit push\b", c):
        return "push"
    if TEST_RE.search(c):
        return "test"
    if UPLOAD_RE.search(c):
        return "upload"
    if BUILD_RE.search(c):
        return "build"
    if DELETE_RE.search(c):
        return "delete"
    return "run"


def commit_message(cmd):
    m = re.search(r"-m\s+[\"']([^\"']+)", str(cmd or ""))
    return m.group(1) if m else ""


def line_diff(name, inp):
    """'+12 -3' fuer Datei-Aenderungen."""
    def n(t):
        t = str(t or "")
        return t.count("\n") + 1 if t else 0
    if name == "Write":
        return "+%d" % n(inp.get("content"))
    if name == "MultiEdit":
        add = sum(n(e.get("new_string")) for e in inp.get("edits", []) or [])
        rem = sum(n(e.get("old_string")) for e in inp.get("edits", []) or [])
        return "+%d -%d" % (add, rem)
    if name == "Edit":
        return "+%d -%d" % (n(inp.get("new_string")), n(inp.get("old_string")))
    return ""


def tool_state(name, inp):
    inp = inp or {}
    if name in READ_TOOLS:
        return "read", base(inp.get("file_path") or inp.get("notebook_path"))
    if name in WRITE_TOOLS:
        d = line_diff(name, inp)
        return "write", (base(inp.get("file_path") or inp.get("notebook_path")) + ("  " + d if d else ""))
    if name in ("Bash", "PowerShell"):
        cmd = inp.get("command") or ""
        kind = command_kind(cmd)
        if kind == "commit":
            return "commit", commit_message(cmd) or "git commit"
        return kind, inp.get("description") or cmd
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
    if name == "TodoWrite":
        todos = inp.get("todos") or []
        done = sum(1 for t in todos if isinstance(t, dict) and t.get("status") == "completed")
        return "plan", "%d/%d" % (done, len(todos))
    if name in ("TaskCreate", "TaskUpdate"):
        return "plan", ""
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
        tool, inp = ev.get("tool_name", ""), ev.get("tool_input") or {}
        if tool in ("Bash", "PowerShell") and command_kind(inp.get("command")) == "test":
            send("testok")  # Tests bestanden
        else:
            send("think")
        img, cap = image_from_tool(tool, inp, ev.get("tool_response"))
        if img is not None:
            send_image(img, cap)  # Screenshot kurz als Polaroid zeigen
    elif name == "PostToolUseFailure":
        tool, inp = ev.get("tool_name", ""), ev.get("tool_input") or {}
        if tool in ("Bash", "PowerShell") and command_kind(inp.get("command")) == "test":
            send("testfail")
        else:
            send("oops", tool)  # Befehl ist fehlgeschlagen: kurzer Schreck
    elif name == "PermissionRequest":
        st, d = tool_state(ev.get("tool_name", ""), ev.get("tool_input"))
        send("need", d)  # zeigt, wofuer Claude die Erlaubnis braucht
    elif name == "PreCompact":
        send("compact")
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


HOOK_EVENTS = ["SessionStart", "UserPromptSubmit", "PreToolUse", "PostToolUse", "PostToolUseFailure", "PermissionRequest",
               "PreCompact", "Notification", "Stop", "SessionEnd"]


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
        if ev in ("PreToolUse", "PostToolUse", "PostToolUseFailure", "PermissionRequest"):
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
    """(Verbindung, IP) - Verbindung ist der USB-Port oder "WLAN"."""
    global DEVICE_VERSION
    for p in ([] if FORCE_WLAN else ([load_cfg().get("port")] if load_cfg().get("port") else []) + find_ports()):
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
                DEVICE_VERSION = parts[1] if len(parts) > 1 else "v1"
                return p, (parts[0] if parts else "-")
        except Exception:
            pass
    txt = http("/cmd?l=%3F", timeout=1.5)  # ueber WLAN fragen (ab v5)
    if txt and txt.startswith("BUDDY"):
        parts = txt.split()
        DEVICE_VERSION = parts[2] if len(parts) > 2 else "?"
        return "WLAN", parts[1] if len(parts) > 1 else "-"
    if txt is None and http("/status", timeout=1.5):  # aeltere Firmware ohne /cmd
        return "WLAN", load_cfg().get("host")
    return None, None


DEVICE_VERSION = "?"


def find():
    port, ip = query_device()
    cfg = load_cfg()
    if port:
        if port != "WLAN":
            cfg["port"] = port
        if ip and ip != "-":
            cfg["host"] = ip
        save_cfg(cfg)
        print("Gefunden %s %s, WLAN: %s, Firmware %s" % ("per" if port == "WLAN" else "an", port, ip, DEVICE_VERSION))
    else:
        print("Kein Buddy gefunden (weder USB noch WLAN).")


def wifi():
    import getpass
    ssid = input("WLAN-Name (leer = WLAN aus): ").strip()
    pw = getpass.getpass("Passwort: ") if ssid else ""
    if not send_line("W %s|%s" % (ssid, pw)):
        print("Geraet nicht erreicht (weder USB noch WLAN)")
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
    elif cmd == "bild":
        from PIL import Image
        secs = int(sys.argv[3]) if len(sys.argv) > 3 else 0
        ok = send_image(Image.open(sys.argv[2]), base(sys.argv[2]), secs)
        print("ok" if ok else "Geraet nicht erreicht")
    elif cmd == "update":
        print("ok - der Buddy sucht jetzt nach einem Update" if send_line("U") else "Geraet nicht erreicht")
    elif cmd == "install":
        install()
    elif cmd == "uninstall":
        uninstall()
    else:
        print(__doc__)
