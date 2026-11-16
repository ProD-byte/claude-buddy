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
  python buddy.py foto [240|416|480|640] [--drehen 90|180|270 [--merken]] [--still] [--an]
                                  Foto mit der Kamera des SenseCAP Watchers (USB, sonst WLAN), gibt den Dateipfad aus.
                                  Liegt in %LOCALAPPDATA%\\claude-buddy\\fotos (letztes.jpg = neuestes).
                                  --still: nicht auf dem Buddy zeigen, --an: Kamera 2 min anlassen
  SD-Karte des Watchers (ueber WLAN, Uebersicht im Browser: http://<ip>/sd):
  python buddy.py zeitraffer <sek>|aus   Zeitraffer auf die SD-Karte starten/stoppen (ohne Angabe: Stand)
  python buddy.py zeitraffer holen [serie]  neueste (oder genannte) Serie laden und als GIF speichern
  python buddy.py ton [<name> <datei.wav>|<name> weg]  eigenen Ton hochladen/entfernen (ohne: Liste)
  python buddy.py protokoll       letzte Arbeitsrunden und Summe von heute
  python buddy.py install         Hooks in Claude Code eintragen (~/.claude/settings.json)
  python buddy.py uninstall       Hooks wieder entfernen

Verbindung: zuerst USB, sonst WLAN (IP aus config.json, sonst claude-buddy.local).
Alle Buddys bekommen die Meldung: angesteckte per USB (T-Display-S3 am Espressif-Port,
SenseCAP Watcher am zweiten Kanal seines CH342), alle anderen bekannten per WLAN.
Welche WLAN-Adresse zu welchem USB-Port gehoert, merkt sich config.json ("devices").
Alle Befehle gehen auch per WLAN. Mit --wlan wird USB uebersprungen (zum Testen).
"""
import json
import os
import sys
import time

HERE = os.path.dirname(os.path.abspath(__file__))
CFG_FILE = os.path.join(HERE, "config.json")
ESPRESSIF_VID = 0x303A
CH342_VID, CH342_PID = 0x1A86, 0x55D2  # SenseCAP Watcher: Kanal x.2 = ESP32-S3 (x.0 ist der Kamera-Chip)
SCAN_EVERY = 20  # s: so oft nach neu angesteckten Buddys suchen


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
        out = []
        for p in list_ports.comports():
            if p.vid == ESPRESSIF_VID:
                out.append(p.device)
            elif p.vid == CH342_VID and p.pid == CH342_PID and (p.location or "").endswith(".2"):
                out.append(p.device)
        return out
    except Exception:
        return []


def ask_port(p, wait=1.0):
    """Fragt einen Buddy per USB nach seiner WLAN-Adresse: "BUDDY <ip oder -> v<version>". Liefert (ip, version) oder None."""
    try:
        s = open_port(p)
        s.reset_input_buffer()
        s.write(b"?\n")
        s.flush()
        t = time.time()
        buf = b""
        while time.time() - t < wait:
            buf += s.read(64)
            if b"BUDDY" in buf and b"\n" in buf.split(b"BUDDY", 1)[1]:
                break
        s.close()
        txt = buf.decode("ascii", "replace")
        if "BUDDY" not in txt:
            return None
        parts = txt.split("BUDDY", 1)[1].splitlines()[0].split()
        return (parts[0] if parts else "-"), (parts[1] if len(parts) > 1 else "v1")
    except Exception:
        return None


def learn_device(cfg, port, ip):
    """Merkt sich, welche WLAN-Adresse zu welchem USB-Port gehoert (cfg["devices"] = {ip: port})."""
    devs = cfg.setdefault("devices", {})
    for k in [k for k, v in devs.items() if v == port and k != ip]:
        del devs[k]  # Port hat jetzt eine andere Adresse
    if ip and ip != "-":
        devs[ip] = port


def usb_ports(cfg):
    """Bekannte USB-Ports aller Buddys; sucht hoechstens alle SCAN_EVERY s neu (spart Zeit in den Hooks)."""
    if FORCE_WLAN:
        return []
    ports = list(cfg.get("ports") or ([cfg["port"]] if cfg.get("port") else []))
    if not ports or time.time() - cfg.get("scan_t", 0) > SCAN_EVERY:
        ports = list(dict.fromkeys(find_ports()))
        cfg["ports"] = ports
        cfg["scan_t"] = time.time()
        if ports:
            cfg["port"] = ports[0]
        # neue Buddys nach ihrer WLAN-Adresse fragen (ohne Adresse hoechstens alle 5 min erneut)
        known = set((cfg.get("devices") or {}).values())
        asked = cfg.setdefault("asked", {})
        for p in ports:
            if p not in known and time.time() - asked.get(p, 0) > 300:
                asked[p] = time.time()
                r = ask_port(p, 0.8)
                if r:
                    learn_device(cfg, p, r[0])
        save_cfg(cfg)
    return ports


def write_port(p, data, chunked=False):
    """Schreibt data an einen Port; True wenn es geklappt hat."""
    for _ in range(3):  # Port kann kurz von einem anderen Hook belegt sein
        try:
            s = open_port(p)
            if chunked:
                s.write_timeout = 3
                for i in range(0, len(data), 2048):  # in Haeppchen, sonst laeuft der Empfangspuffer im Buddy ueber
                    s.write(data[i:i + 2048])
                    s.flush()
                    time.sleep(0.03)
            else:
                s.write(data)
                s.flush()
            s.close()
            return True
        except Exception as e:
            if "PermissionError" in repr(e) or "Zugriff" in str(e):
                time.sleep(0.05)
                continue
            return False
    return False


def send_usb(data, chunked=False):
    """An alle Buddys per USB; liefert die Liste der Ports, die es bekommen haben."""
    cfg = load_cfg()
    ports = usb_ports(cfg)
    ok = [p for p in ports if write_port(p, data, chunked)]
    if len(ok) < len(ports) and not FORCE_WLAN:  # einer fehlt (abgesteckt?): gleich neu suchen
        fresh = [p for p in find_ports() if p not in ports]
        ok += [p for p in fresh if write_port(p, data, chunked)]
        cfg["ports"] = ok
        cfg["scan_t"] = time.time()
        if ok:
            cfg["port"] = ok[0]
        save_cfg(cfg)
    return ok


def wlan_targets(cfg, reached):
    """WLAN-Adressen der bekannten Buddys, die gerade nicht per USB erreicht wurden.
    Wer zuletzt nicht antwortete, wird 60 s lang uebersprungen (damit die Hooks nicht warten)."""
    devs = dict(cfg.get("devices") or {})
    if not devs and cfg.get("host"):  # alte config.json: nur eine Adresse
        devs = {cfg["host"]: cfg.get("port")}
    down = cfg.get("down") or {}
    return [ip for ip, port in devs.items() if port not in reached and time.time() - down.get(ip, 0) > 60]


def http_multi(hosts, path, data=None, timeout=0.8):
    """Ruft path bei mehreren Buddys gleichzeitig auf; liefert die Liste der Adressen, die geantwortet haben."""
    import threading
    import urllib.request
    ok, lock = [], threading.Lock()

    def one(h):
        try:
            req = urllib.request.Request("http://%s%s" % (h, path), data=data,
                                         headers={"Content-Type": "text/plain"} if data else {})
            urllib.request.urlopen(req, timeout=timeout).read()
            with lock:
                ok.append(h)
        except Exception:
            pass

    th = [threading.Thread(target=one, args=(h,)) for h in hosts]
    for t in th:
        t.start()
    for t in th:
        t.join()
    if len(ok) < len(hosts):  # Nicht-Antworter merken
        cfg = load_cfg()
        down = cfg.setdefault("down", {})
        for h in hosts:
            if h in ok:
                down.pop(h, None)
            else:
                down[h] = time.time()
        save_cfg(cfg)
    elif hosts:
        cfg = load_cfg()
        if any(h in (cfg.get("down") or {}) for h in hosts):
            for h in hosts:
                cfg["down"].pop(h, None)
            save_cfg(cfg)
    return ok


def line_path(line):
    """HTTP-Pfad fuer eine Befehlszeile."""
    import urllib.parse
    if line.startswith("S "):  # Zustand ueber /s (kennt auch aeltere Firmware)
        f = line[2:].split("|")
        f += [""] * (5 - len(f))
        return "/s?" + urllib.parse.urlencode({"st": f[0], "d": f[1], "t": f[2], "sid": f[3], "p": f[4]})
    return "/cmd?" + urllib.parse.urlencode({"l": line})  # alle anderen Befehle (ab v5)


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
    data = (line + "\n").encode("ascii", "replace")
    reached = send_usb(data)
    # WLAN: alle bekannten Buddys, die gerade nicht am USB haengen
    cfg = load_cfg()
    hosts = wlan_targets(cfg, reached)
    path = line_path(line)
    if hosts:
        return bool(http_multi(hosts, path, timeout=0.8 if line.startswith("S ") else 2)) or bool(reached)
    if reached:
        return True
    return http(path, timeout=0.6 if line.startswith("S ") else 2) is not None  # noch keine Adresse bekannt: mDNS


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
    reached = []
    if not secs:
        data = ("P %d %d %s|" % (w, h, cap)).encode("ascii") + b64.encode("ascii") + b"\n"
        reached = send_usb(data, chunked=True)
    import urllib.parse
    q = urllib.parse.urlencode({"w": w, "h": h, "c": cap, "s": int(secs)})
    hosts = wlan_targets(load_cfg(), reached)
    if hosts:
        return bool(http_multi(hosts, "/img?" + q, data=b64.encode("ascii"), timeout=3)) or bool(reached)
    if reached:
        return True
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
    """Alle Buddys suchen: per USB (und deren WLAN-Adresse merken), dann die bekannten, die nur im WLAN sind."""
    cfg = load_cfg()
    usb = [] if FORCE_WLAN else find_ports()
    seen = set()
    for p in usb:
        r = ask_port(p, 1.5)
        if r:
            learn_device(cfg, p, r[0])
            seen.add(r[0])
            print("Buddy an %s, WLAN: %s, Firmware %s" % (p, r[0], r[1]))
        else:
            print("%s antwortet nicht" % p)
    if usb:
        cfg["ports"], cfg["scan_t"], cfg["port"] = usb, time.time(), usb[0]
    devs = dict(cfg.get("devices") or {})
    if not devs and cfg.get("host"):
        devs = {cfg["host"]: cfg.get("port")}
    for ip in devs:
        if ip in seen:
            continue
        import urllib.request
        try:
            txt = urllib.request.urlopen("http://%s/cmd?l=%%3F" % ip, timeout=1.5).read().decode("ascii", "replace")
            print("Buddy per WLAN %s (zuletzt an %s), Firmware %s" % (ip, devs[ip] or "?", txt.split()[-1] if txt.startswith("BUDDY") else "?"))
            seen.add(ip)
        except Exception:
            print("%s (zuletzt an %s) antwortet nicht" % (ip, devs[ip] or "?"))
    cfg.pop("down", None)
    save_cfg(cfg)
    if seen or usb:
        return
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


# ----------------------------------------------------------------- Kamera (SenseCAP Watcher)
# Die Kamera haengt am KI-Chip Himax WE2. Der ist ueber den anderen Kanal des CH342 direkt am PC
# (SSCMA-AT-Befehle, 921600 Baud); der Buddy schaltet nur seinen Strom ("K 1" / "K 0").
# Fotos bleiben lokal (nicht im synchronisierten Projektordner), die letzten FOTO_MAX werden behalten.
FOTO_DIR = os.path.join(os.environ.get("LOCALAPPDATA") or os.path.expanduser("~"), "claude-buddy", "fotos")
FOTO_MAX = 30
FOTO_RES = {"240": 0, "416": 1, "480": 2, "640": 3}


def himax_port():
    """COM-Port des Kamerachips: der Kanal des Watcher-CH342, der nicht der ESP32 ist."""
    try:
        from serial.tools import list_ports
        for p in list_ports.comports():
            if p.vid == CH342_VID and p.pid == CH342_PID and not (p.location or "").endswith(".2"):
                return p.device
    except Exception:
        pass
    return None


def himax_cmd(s, c, wait=3.0, until_image=False):
    """Schickt einen AT-Befehl und sammelt die JSON-Antworten (je Zeile eine)."""
    s.reset_input_buffer()
    s.write((c + "\r\n").encode())
    t, buf, msgs = time.time(), b"", []
    while time.time() - t < wait:
        buf += s.read(1 << 16)
        while b"\n" in buf:
            line, buf = buf.split(b"\n", 1)
            line = line.strip()
            if line.startswith(b"{"):
                try:
                    msgs.append(json.loads(line))
                except Exception:
                    pass
        if msgs and not until_image:
            break
        if until_image and any(isinstance(m.get("data"), dict) and m["data"].get("image") for m in msgs):
            break
    return msgs


def foto_wlan(res="640", keep_on=False):
    """Foto ueber WLAN: der Watcher holt das Bild selbst per SPI vom Kamerachip (ab Firmware v8).
    Liefert die JPEG-Bytes oder None."""
    import urllib.request
    cfg = load_cfg()
    hosts = list((cfg.get("devices") or {}).keys()) or ([cfg["host"]] if cfg.get("host") else [])
    r = FOTO_RES.get(str(res), 3)
    for ip in hosts:
        try:  # das T-Display kennt /foto nicht (404) - dann den naechsten Buddy fragen
            urllib.request.urlopen("http://%s/foto?r=%d%s" % (ip, r, "&an=1" if keep_on else ""), timeout=2).read()
        except Exception:
            continue
        t = time.time()
        while time.time() - t < 25:
            time.sleep(0.4)
            try:
                return urllib.request.urlopen("http://%s/foto.jpg" % ip, timeout=5).read()
            except urllib.error.HTTPError as e:
                if e.code == 503:  # nimmt noch auf
                    continue
                print("Watcher %s: %s" % (ip, e.read().decode("utf-8", "replace")))
                return None
            except Exception:
                continue
        print("Watcher %s: keine Antwort" % ip)
        return None
    return None


def foto(res="640", keep_on=False, show=True, rotate=None):
    """Foto mit der Watcher-Kamera (per USB direkt vom Kamerachip, sonst ueber WLAN); liefert den Dateipfad oder None."""
    import base64
    port = None if FORCE_WLAN else himax_port()
    if not port:
        import urllib.error  # noqa: F401
        jpg = foto_wlan(res, keep_on)
        if not jpg:
            print("Kein Foto: Watcher weder per USB noch per WLAN erreichbar.")
            return None
        return foto_save(jpg, show, rotate)
    import serial
    s = serial.Serial()
    s.port, s.baudrate, s.timeout = port, 921600, 0.1
    s.dtr = False
    s.rts = False
    try:
        s.open()
    except Exception as e:
        print("Kamera-Port %s nicht frei: %s" % (port, e))
        return None
    jpg = None
    try:
        # Laeuft der Chip schon? Sonst einschalten und den Start abwarten: Der Bootloader geht in den
        # X-Modem-Flashmodus, wenn in den ersten 100 ms ein Zeichen kommt - also erst still mitlesen.
        if not any(m.get("name") == "ID?" for m in himax_cmd(s, "AT+ID?", 0.6)):
            send_line("K 1")
            t, last, got = time.time(), time.time(), False
            while time.time() - t < 8:
                b = s.read(4096)
                if b:
                    got, last = True, time.time()
                elif got and time.time() - last > 1.0:
                    break  # Startmeldung ist durch
        t = time.time()
        while time.time() - t < 12:  # nach dem Einschalten braucht der Chip ein paar Sekunden
            if any(m.get("name") == "ID?" for m in himax_cmd(s, "AT+ID?", 0.8)):
                break
        else:
            print("Kamerachip antwortet nicht.")
            return None
        himax_cmd(s, "AT+SENSOR=1,1,%d" % FOTO_RES.get(str(res), 3), 3)
        for m in himax_cmd(s, "AT+SAMPLE=1", 8, until_image=True):
            d = m.get("data")
            if isinstance(d, dict) and d.get("image"):
                jpg = base64.b64decode(d["image"])
    finally:
        s.close()
        if not keep_on:
            send_line("K 0")
    if not jpg:
        print("Kein Bild bekommen.")
        return None
    sd_put("fotos/%s.jpg" % time.strftime("%Y-%m-%d_%H-%M-%S"), jpg, timeout=3)  # auch ins SD-Fotoarchiv (wenn im WLAN)
    return foto_save(jpg, show, rotate)


# ----------------------------------------------------------------- SD-Karte des Watchers (ueber WLAN)
def watcher_host():
    """WLAN-Adresse des Buddys mit SD-Karte (der Watcher); None wenn keiner antwortet."""
    import urllib.request
    cfg = load_cfg()
    for ip in list((cfg.get("devices") or {}).keys()) or ([cfg["host"]] if cfg.get("host") else []):
        try:
            with urllib.request.urlopen("http://%s/zeitraffer" % ip, timeout=1.5) as r:
                if r.status == 200:
                    return ip
        except Exception:
            continue
    return None


def sd_put(path, data, timeout=10, host=None):
    """Datei auf die SD-Karte des Watchers schreiben (multipart-POST an /sdput)."""
    import urllib.parse
    import urllib.request
    host = host or watcher_host()
    if not host:
        return False
    bnd = "----buddy%d" % int(time.time() * 1000)
    body = (("--%s\r\nContent-Disposition: form-data; name=\"f\"; filename=\"%s\"\r\n"
             "Content-Type: application/octet-stream\r\n\r\n") % (bnd, os.path.basename(path))).encode() + data + ("\r\n--%s--\r\n" % bnd).encode()
    req = urllib.request.Request("http://%s/sdput?%s" % (host, urllib.parse.urlencode({"p": path})), data=body,
                                 headers={"Content-Type": "multipart/form-data; boundary=" + bnd})
    try:
        return urllib.request.urlopen(req, timeout=timeout).read().startswith(b"ok")
    except Exception:
        return False


def sd_get(host, path, timeout=10):
    import urllib.parse
    import urllib.request
    return urllib.request.urlopen("http://%s/sdget?%s" % (host, urllib.parse.urlencode({"p": path})), timeout=timeout).read()


def sd_list(host, d=""):
    import urllib.parse
    import urllib.request
    return json.loads(urllib.request.urlopen("http://%s/sdlist?%s" % (host, urllib.parse.urlencode({"d": d})), timeout=10).read())


def zeitraffer(args):
    """zeitraffer <sek> | aus | holen [serie] | (ohne: Stand)"""
    import urllib.request
    host = watcher_host()
    if not host:
        print("Watcher nicht im WLAN erreichbar.")
        return
    a = args[0] if args else ""
    if a == "holen":
        return zeitraffer_holen(host, args[1] if len(args) > 1 else None)
    if a:
        sec = 0 if a in ("aus", "0", "stop") else int(a)
        try:
            txt = urllib.request.urlopen("http://%s/zeitraffer?s=%d" % (host, sec), timeout=15).read()
        except urllib.error.HTTPError as e:
            txt = e.read()
    else:
        txt = urllib.request.urlopen("http://%s/zeitraffer" % host, timeout=5).read()
    st = json.loads(txt)
    if not st.get("sd"):
        print("Keine SD-Karte im Watcher.")
    elif st.get("an"):
        print("Zeitraffer laeuft: alle %d s, %d Bilder bisher (%s)" % (st["sek"], st["bilder"], st["ordner"]))
    else:
        print("Zeitraffer aus. Letzte Serie: %s (%d Bilder)" % (st.get("ordner") or "-", st.get("bilder", 0)))


def zeitraffer_holen(host, serie=None, fps=8, breite=480):
    """Laedt eine Zeitraffer-Serie (Standard: die neueste) und macht daraus ein GIF; gibt den Pfad aus."""
    from PIL import Image
    import io
    serien = sd_list(host, "zeitraffer").get("dirs", [])
    if not serien:
        print("Noch keine Zeitraffer-Serie auf der SD-Karte.")
        return None
    serie = serie or serien[0]  # neueste zuerst
    files = sorted(f[0] for f in sd_list(host, "zeitraffer/" + serie).get("files", []) if f[0].endswith(".jpg"))
    if not files:
        print("Serie %s ist leer." % serie)
        return None
    out_dir = os.path.join(os.path.dirname(FOTO_DIR), "zeitraffer", serie)
    os.makedirs(out_dir, exist_ok=True)
    frames = []
    for i, f in enumerate(files):
        p = os.path.join(out_dir, f)
        if not os.path.exists(p):
            with open(p, "wb") as fh:
                fh.write(sd_get(host, "zeitraffer/%s/%s" % (serie, f)))
        img = Image.open(p).convert("RGB")
        img.thumbnail((breite, breite))
        frames.append(img)
        print("\r%d/%d Bilder geladen" % (i + 1, len(files)), end="", flush=True)
    print()
    gif = os.path.join(os.path.dirname(out_dir), serie + ".gif")
    frames[0].save(gif, save_all=True, append_images=frames[1:], duration=int(1000 / fps), loop=0, optimize=True)
    print(gif)
    return gif


def ton(args):
    """ton <name> <datei.wav> | ton <name> weg | ton (Liste)"""
    import io
    import wave
    names = ["hello", "bye", "think", "read", "search", "write", "run", "web", "agent", "need", "ask", "done", "oops",
             "poke", "mode", "remind", "whistle", "pop", "party", "commit", "push", "build", "upload", "test", "testok",
             "testfail", "delete", "compact", "camera"]
    host = watcher_host()
    if not host:
        print("Watcher nicht im WLAN erreichbar.")
        return
    if not args:
        have = {f[0][:-4] for f in sd_list(host, "toene").get("files", []) if f[0].endswith(".wav")}
        print("Eigene Toene (* = vorhanden):")
        print("  " + "  ".join(("*" if n in have else "") + n for n in names))
        return
    name = args[0]
    if name not in names:
        print("Unbekannter Name. Moeglich: " + ", ".join(names))
        return
    if len(args) > 1 and args[1] in ("weg", "loeschen", "aus"):
        import urllib.request
        urllib.request.urlopen("http://%s/sddel?p=toene/%s.wav" % (host, name), timeout=5).read()
        print("%s: wieder der eingebaute Ton" % name)
        return
    w = wave.open(args[1], "rb")
    ch, sw, rate = w.getnchannels(), w.getsampwidth(), w.getframerate()
    data = w.readframes(min(w.getnframes(), rate * 10))  # hoechstens 10 s
    w.close()
    if ch > 2:
        print("Bitte eine Mono- oder Stereo-WAV.")
        return
    if sw != 2:  # der Watcher kann nur 16 Bit; Kanaele und Abtastrate rechnet er selbst um
        try:
            import warnings
            with warnings.catch_warnings():
                warnings.simplefilter("ignore")
                import audioop
            data = audioop.lin2lin(data, sw, 2)
        except ImportError:
            print("Bitte als 16-Bit-WAV speichern (diese hat %d Bit)." % (sw * 8))
            return
    buf = io.BytesIO()
    o = wave.open(buf, "wb")
    o.setnchannels(ch)
    o.setsampwidth(2)
    o.setframerate(rate)
    o.writeframes(data)
    o.close()
    ok = sd_put("toene/%s.wav" % name, buf.getvalue(), host=host)
    print("%s: %s" % (name, "hochgeladen, ab jetzt aktiv" if ok else "Hochladen fehlgeschlagen"))


def protokoll(n=15):
    """Letzte Runden aus dem Arbeitsprotokoll und die Summe von heute."""
    host = watcher_host()
    if not host:
        print("Watcher nicht im WLAN erreichbar.")
        return
    try:
        rows = [r.split(";") for r in sd_get(host, "protokoll.csv").decode("utf-8", "replace").splitlines()[1:] if r.strip()]
    except Exception:
        print("Noch kein Protokoll.")
        return
    for r in rows[-n:]:
        print("%s %s-%s  %3d min  %s" % (r[0], r[1], r[2], int(r[3]) // 60, r[4] if len(r) > 4 else ""))
    heute = time.strftime("%Y-%m-%d")
    t = [int(r[3]) for r in rows if r[0] == heute]
    print("Heute: %d Runden, %d:%02d h" % (len(t), sum(t) // 3600, sum(t) // 60 % 60))


def foto_save(jpg, show=True, rotate=None):
    """JPEG speichern (ggf. gedreht), letztes.jpg aktualisieren, alte aufraeumen, als Polaroid zeigen."""
    os.makedirs(FOTO_DIR, exist_ok=True)
    path = os.path.join(FOTO_DIR, time.strftime("foto-%Y%m%d-%H%M%S.jpg"))
    rotate = load_cfg().get("foto_drehen", 0) if rotate is None else rotate
    img = None
    if rotate or show:
        from PIL import Image
        import io
        img = Image.open(io.BytesIO(jpg))
        if rotate:
            img = img.rotate(-rotate, expand=True)  # im Uhrzeigersinn
    if rotate:
        img.save(path, quality=92)
    else:
        with open(path, "wb") as f:
            f.write(jpg)
    import shutil
    shutil.copy(path, os.path.join(FOTO_DIR, "letztes.jpg"))
    old = sorted(f for f in os.listdir(FOTO_DIR) if f.startswith("foto-"))
    for f in old[:-FOTO_MAX]:
        try:
            os.remove(os.path.join(FOTO_DIR, f))
        except OSError:
            pass
    if show and img is not None:
        send_image(img, "Foto")  # kurz als Polaroid auf den Buddys (mit Ausloese-Geraeusch)
    return path


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
    elif cmd == "foto":
        args = sys.argv[2:]
        res = next((a for a in args if a in FOTO_RES), "640")
        rot = None
        if "--drehen" in args:
            i = args.index("--drehen")
            rot = int(args[i + 1]) if i + 1 < len(args) else 180
            if "--merken" in args:
                c = load_cfg()
                c["foto_drehen"] = rot
                save_cfg(c)
        p = foto(res, keep_on="--an" in args, show="--still" not in args, rotate=rot)
        if p:
            print(p)
        else:
            sys.exit(1)
    elif cmd == "zeitraffer":
        zeitraffer(sys.argv[2:])
    elif cmd == "ton":
        ton(sys.argv[2:])
    elif cmd == "protokoll":
        protokoll()
    elif cmd == "update":
        print("ok - der Buddy sucht jetzt nach einem Update" if send_line("U") else "Geraet nicht erreicht")
    elif cmd == "install":
        install()
    elif cmd == "uninstall":
        uninstall()
    else:
        print(__doc__)
