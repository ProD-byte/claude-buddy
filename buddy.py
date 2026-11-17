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
  python buddy.py sag <text>      den Watcher etwas sagen lassen (Windows-Stimme, offline); nach jeder Runde liest er
                                  Claudes Ergebnis in einem Satz vor (am Watcher: Einstellungen -> Vorlesen)
  python buddy.py frage <text>    Freigabe am Watcher-Knopf testen (druecken = ja, drehen = nein); im Betrieb fragt der
                                  PermissionRequest-Hook so, 20 s lang (config.json: "freigabe_sek", 0 = aus)
  python buddy.py wurf            Ball von einem Buddy zum anderen werfen (passiert sonst beim Sitzungswechsel)
  python buddy.py ort <stadt>     Ort fuer das Wetter (Open-Meteo, ohne Konto); das Zuhoeren schickt es alle 20 min
  python buddy.py geburtstag TT.MM.   an dem Tag gibt es Torte und Gratulation
  python buddy.py plaudern        die zwei Buddys sofort plaudern lassen (passiert sonst ab und zu von selbst)
  python buddy.py zuhoeren [--ohne-enter]  laeuft dauerhaft: Knopf am Watcher halten und sprechen -> Text wird
                                  offline erkannt (faster-whisper) und ins aktive Fenster eingefuegt + Enter
  python buddy.py install         Hooks in Claude Code eintragen (~/.claude/settings.json); mit Watcher auf Wunsch
                                  auch Sprechen per Knopf (--sprache / --ohne-sprache)
  python buddy.py sprache [aus]   Sprechen per Watcher-Knopf einrichten: faster-whisper + Autostart (aus = entfernen)
  python buddy.py uninstall       Hooks (und Autostart) wieder entfernen
  python buddy.py koppeln [ip] [--neu]  PC mit den Buddys koppeln (ohne Passwort): angesteckte per USB sofort,
                                  die anderen per Knopfdruck am Geraet (Watcher: druecken, T-Display: IO14)
  python buddy.py link            Browser-Adressen der Buddys mit Schluessel (z.B. fuer die SD-Seite)
  python buddy.py flash <ip> <firmware.bin>  Firmware per WLAN aufspielen (pio run -e watcher-wlan -t upload)

Sicherheit: Im WLAN nimmt ein Buddy Befehle nur von gekoppelten PCs an. Die Schluessel stehen in
pc/kopplung.json; geht etwas schief, koppelt buddy.py per USB oder Knopfdruck neu.

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
DATA = os.environ.get("CLAUDE_BUDDY_DATA") or HERE  # das Windows-Programm setzt %LOCALAPPDATA%\ClaudeBuddy
CFG_FILE = os.path.join(DATA, "config.json")
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


# ---------------------------------------------------------------- Kopplung (Schluessel statt Passwort)
# Eigene Datei, nur beim Koppeln geschrieben: config.json schreiben die Hooks staendig, eine alte Kopie
# koennte sonst einen frischen Schluessel wieder ueberschreiben.
KOPPL_FILE = os.path.join(DATA, "kopplung.json")
_TOK_CACHE = {"t": None, "map": {}}


def _kopplung(cfg=None):
    """{mac: {"token", "ip", "name"}}"""
    try:
        with open(KOPPL_FILE, encoding="utf-8") as f:
            return json.load(f)
    except FileNotFoundError:
        old = load_cfg().get("kopplung") or {}  # frueher in config.json
        if old:
            _save_kopplung(old)
        return old
    except Exception:
        return {}


def _save_kopplung(k):
    tmp = KOPPL_FILE + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(k, f, indent=2)
    os.replace(tmp, KOPPL_FILE)  # auf einen Schlag, nie halb geschrieben


def token_for(host):
    """Schluessel fuer eine Buddy-Adresse."""
    try:
        mt = os.path.getmtime(KOPPL_FILE)
    except OSError:
        if not os.path.exists(KOPPL_FILE) and (load_cfg().get("kopplung")):
            _kopplung()  # einmalig umziehen
            return token_for(host)
        return None
    if _TOK_CACHE["t"] != mt:
        _TOK_CACHE["t"] = mt
        _TOK_CACHE["map"] = {v.get("ip"): v.get("token") for v in _kopplung().values() if isinstance(v, dict)}
    return _TOK_CACHE["map"].get(host)


def store_token(mac, token, ip, name=""):
    k = _kopplung()
    for m in [m for m, v in k.items() if m != mac and v.get("ip") == ip]:
        del k[m]  # andere Adresse gehoert jetzt diesem Geraet
    k[mac] = {"token": token, "ip": ip, "name": name or (k.get(mac) or {}).get("name", "")}
    _save_kopplung(k)
    _TOK_CACHE["t"] = None


def pc_name():
    import socket
    return ascii_only(socket.gethostname(), 23) or "PC"


def usb_pair(port):
    """Koppelt still ueber das USB-Kabel ("KP <name>" -> "TOKEN <hex> <mac>"). Liefert (token, mac) oder None."""
    try:
        s = open_port(port)
        s.reset_input_buffer()
        s.write(("KP %s\n" % pc_name()).encode("ascii"))
        s.flush()
        t, buf = time.time(), b""
        while time.time() - t < 2:
            buf += s.read(128)
            if b"TOKEN " in buf and b"\n" in buf.split(b"TOKEN ", 1)[1]:
                break
        s.close()
        txt = buf.decode("ascii", "replace")
        if "TOKEN " not in txt:
            return None
        parts = txt.split("TOKEN ", 1)[1].splitlines()[0].split()
        if len(parts) >= 2 and len(parts[0]) == 32:
            return parts[0], parts[1]
    except Exception:
        pass
    return None


def _raw_get(url, timeout=2, token=None):
    """GET ohne automatische Neu-Kopplung (fuer die Kopplung selbst)."""
    import urllib.request
    req = urllib.request.Request(url, headers={"X-Buddy-Token": token} if token else {})
    req._buddy_retry = True
    return urllib.request.urlopen(req, timeout=timeout).read().decode("ascii", "replace")


def device_mac(host):
    try:
        m = _raw_get("http://%s/id" % host, 2).strip()
        return m if len(m) == 17 else None
    except Exception:
        return None


def paired_ok(host, tries=3):
    """True = gekoppelt (oder alte Firmware ohne Kopplung), False = Buddy lehnt den Schluessel ab,
    None = nicht erreichbar. Nur bei False neu koppeln - eine neue Kopplung macht den alten Schluessel ungueltig."""
    for i in range(tries):
        try:
            return bool(json.loads(_raw_get("http://%s/pair?test=1" % host, 3, token_for(host))).get("ok"))
        except Exception as e:
            if getattr(e, "code", 0) == 404:
                return True  # alte Firmware: kennt /pair nicht
            time.sleep(1)
    return None


def repair_token(host):
    """Nach "401 nicht gekoppelt": still reparieren. Neue IP-Adresse -> Schluessel ueber die MAC wiederfinden,
    sonst per USB neu koppeln, wenn der Buddy gerade angesteckt ist. True = neuer Versuch lohnt sich."""
    mac = device_mac(host)
    if mac:
        e = _kopplung().get(mac)
        if e and e.get("ip") != host:
            store_token(mac, e["token"], host)
            return True
    for port in ([] if FORCE_WLAN else find_ports()):
        r = ask_port(port, 1.0)
        if r and r[0] == host:
            tm = usb_pair(port)
            if tm:
                store_token(tm[1], tm[0], host, "USB")
                return True
    return False


def button_pair(host, wait=65, quiet=False):
    """Kopplung per Knopfdruck: Buddy fragt "Koppeln?", am Geraet bestaetigen. True = gekoppelt."""
    import urllib.parse
    try:
        r = json.loads(_raw_get("http://%s/pair?%s" % (host, urllib.parse.urlencode({"name": pc_name()})), 3))
    except Exception as e:
        if not quiet:
            print("%s: Kopplung nicht moeglich (%s)" % (host, e))
        return False
    if not quiet:
        print("%s fragt jetzt \"Koppeln?\" - Watcher: druecken (drehen = nein), AMOLED: PWR (BOOT = nein), T-Display: IO14 (IO0 = nein)." % host)
    t = time.time()
    while time.time() - t < wait:
        time.sleep(1)
        try:
            st = json.loads(_raw_get("http://%s/pair?id=%s" % (host, r["id"]), 3))
        except Exception:
            continue
        if st.get("st") == "ok":
            store_token(st["mac"], st["token"], host, "Knopf")
            if not quiet:
                print("%s: gekoppelt." % host)
            return True
        if st.get("st") in ("nein", "weg"):
            break
    if not quiet:
        print("%s: nicht gekoppelt." % host)
    return False


def _install_token_opener():
    """Alle urllib-Aufrufe an Buddys bekommen ihren Schluessel; bei 401 wird einmal still neu gekoppelt."""
    import urllib.request

    class TokenHandler(urllib.request.BaseHandler):
        handler_order = 400

        def http_request(self, req):
            t = token_for((req.host or "").split(":")[0])
            if t and not req.has_header("X-buddy-token"):
                req.add_unredirected_header("X-Buddy-Token", t)
            return req

        def http_error_401(self, req, fp, code, msg, hdrs):
            if getattr(req, "_buddy_retry", False):
                return None
            req._buddy_retry = True
            if not repair_token((req.host or "").split(":")[0]):
                return None
            req.unredirected_hdrs.pop("X-buddy-token", None)
            return self.parent.open(req, timeout=req.timeout)

    urllib.request.install_opener(urllib.request.build_opener(TokenHandler))


_install_token_opener()


def koppeln(args):
    """Angesteckte Buddys per USB koppeln, die anderen per Knopfdruck."""
    neu = "--neu" in args
    ips = [a for a in args if a[:1].isdigit()]
    cfg = load_cfg()
    done = set()
    if not ips:
        for port in ([] if FORCE_WLAN else find_ports()):
            r = ask_port(port, 1.5)
            if not r:
                print("%s antwortet nicht" % port)
                continue
            ip = r[0]
            if ip != "-" and not neu and token_for(ip) and paired_ok(ip) is True:
                print("%s (%s): schon gekoppelt" % (port, ip))
                done.add(ip)
                continue
            tm = usb_pair(port)
            if tm:
                store_token(tm[1], tm[0], ip if ip != "-" else "", "USB")
                print("%s (%s): per USB gekoppelt" % (port, ip))
                done.add(ip)
            else:
                print("%s: alte Firmware ohne Kopplung (%s)" % (port, r[1]))
        cfg = load_cfg()
        ips = [ip for ip in (cfg.get("devices") or {}) if ip not in done]
        for v in _kopplung(cfg).values():
            if v.get("ip") and v["ip"] not in done and v["ip"] not in ips:
                ips.append(v["ip"])
    for ip in ips:
        ok = paired_ok(ip)
        if ok is None:
            print("%s antwortet nicht" % ip)
            continue
        if ok and not neu:
            print("%s: schon gekoppelt" % ip)
            continue
        if device_mac(ip) is None and not neu:
            print("%s antwortet nicht (oder alte Firmware)" % ip)
            continue
        button_pair(ip)


def link():
    for mac, v in _kopplung().items():
        if v.get("ip"):
            print("http://%s/sd?k=%s   (%s)" % (v["ip"], v["token"], mac))


def flash(ip, binfile):
    """Firmware per WLAN aufspielen (POST /update mit Schluessel)."""
    import urllib.request
    import uuid
    data = open(binfile, "rb").read()
    bnd = uuid.uuid4().hex
    body = (("--%s\r\nContent-Disposition: form-data; name=\"firmware\"; filename=\"firmware.bin\"\r\n"
             "Content-Type: application/octet-stream\r\n\r\n" % bnd).encode() + data + ("\r\n--%s--\r\n" % bnd).encode())
    ok = paired_ok(ip)
    if ok is None:
        print("%s antwortet nicht" % ip)
        sys.exit(1)
    if not ok:
        print("%s ist nicht gekoppelt - Kopplung per Knopfdruck ..." % ip)
        if not button_pair(ip):
            sys.exit(1)
    req = urllib.request.Request("http://%s/update" % ip, data=body, headers={"Content-Type": "multipart/form-data; boundary=" + bnd})
    print("lade %d KB auf %s ..." % (len(data) // 1024, ip))
    try:
        print(urllib.request.urlopen(req, timeout=180).read().decode("ascii", "replace"))
    except Exception as e:
        print("fehlgeschlagen: %s" % e)
        sys.exit(1)


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


BOARDS = {}  # Port oder IP -> Geraeteart aus der Antwort auf "?" ("watcher", "amoled", "tdisplay")
BOARD_LABEL = {"watcher": "SenseCAP Watcher", "amoled": "AMOLED 1.75C", "tdisplay": "T-Display-S3"}


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
        if len(parts) > 2:
            BOARDS[p] = parts[2]
            if parts[0] != "-":
                BOARDS[parts[0]] = parts[2]
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


_PORT_LOCKS = {}


def _port_lock(p):
    import threading
    return _PORT_LOCKS.setdefault(p, threading.Lock())


def write_port(p, data, chunked=False):
    """Schreibt data an einen Port; True wenn es geklappt hat."""
    with _port_lock(p):
        return _write_port(p, data, chunked)


def _write_port(p, data, chunked=False):
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


LOG_FILE = os.path.join(DATA, "hook.log")
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
RUN_TOOLS = {"Bash", "PowerShell", "BashOutput"}
WAIT_TOOLS = {"Monitor", "TaskOutput", "ScheduleWakeup", "AwaitShell"}       # auf etwas im Hintergrund warten
MSG_TOOLS = {"SendMessage", "ListAgents"}                                    # mit anderen Sitzungen/Helfern reden
WEB_TOOLS = {"WebFetch", "WebSearch"}
AGENT_TOOLS = {"Agent", "Task"}
ASK_TOOLS = {"AskUserQuestion", "ExitPlanMode"}


def base(p):
    return os.path.basename(str(p or "").rstrip("/\\")) or str(p or "")


import re

TEST_RE = re.compile(r"\b(pytest|unittest|jest|vitest|mocha|ctest|go test|cargo test|npm (run )?test|yarn test|pnpm test|pio test|gradle test|mvn test|phpunit|rspec)\b")
UPLOAD_RE = re.compile(r"(-t upload|--target upload|\besptool\b|arduino-cli upload|\bavrdude\b|idf\.py .*flash|\bpio run -e ota)")
BUILD_RE = re.compile(r"\b(pio run|platformio run|npm run build|yarn build|pnpm build|make\b|cmake --build|cargo build|go build|tsc\b|vite build|webpack|gradle build|mvn package|dotnet build|gcc|g\+\+|pip install|npm install|npm ci)")
DELETE_RE = re.compile(r"(^|[;&|]\s*)(rm|del|rmdir|rd|remove-item|git rm)\b")
INSTALL_RE = re.compile(r"\b(pip3? install|python -m pip install|npm (i|install|ci)\b|yarn add|pnpm (add|install)|apt(-get)? install|winget install|choco install|brew install|cargo add|pio pkg install|platformio pkg install|gem install|go get)")
DOWNLOAD_RE = re.compile(r"(\bcurl\b|\bwget\b|invoke-webrequest|\biwr\b|gh release download|\bgit clone\b|\bgit pull\b|\bgit fetch\b)")
WAIT_RE = re.compile(r"^(sleep|start-sleep|timeout)\b")
IMAGE_EXT_RE = re.compile(r"\.(png|jpe?g|gif|webp|bmp)$", re.I)


def command_kind(cmd):
    """Ordnet einen Terminal-Befehl einer Taetigkeit zu (fuer die passende Animation)."""
    c = " ".join(str(cmd or "").lower().split())
    if re.search(r"\bgit commit\b", c):
        return "commit"
    if re.search(r"\bgit push\b", c):
        return "push"
    if TEST_RE.search(c):
        return "test"
    if INSTALL_RE.search(c):
        return "install"
    if UPLOAD_RE.search(c):
        return "upload"
    if BUILD_RE.search(c):
        return "build"
    if DELETE_RE.search(c):
        return "delete"
    if WAIT_RE.search(c):
        return "waitbg"
    if DOWNLOAD_RE.search(c):
        return "download"
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
        f = inp.get("file_path") or inp.get("notebook_path") or ""
        if IMAGE_EXT_RE.search(str(f)):
            return "look", base(f)  # ein Bild ansehen
        return "read", base(f)
    if name in WRITE_TOOLS:
        d = line_diff(name, inp)
        st = "write" if name == "Write" else "edit"  # neu schreiben oder vorhandene Datei aendern
        return st, (base(inp.get("file_path") or inp.get("notebook_path")) + ("  " + d if d else ""))
    if name in WAIT_TOOLS:
        return "waitbg", inp.get("description") or ""
    if name in MSG_TOOLS:
        return "msg", inp.get("to") or inp.get("summary") or ""
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
            return "browser", inp.get("url") and __import__("urllib.parse").parse.urlparse(inp["url"]).netloc or tool
        if "ccd_session" in name or "send_message" in tool:
            return "msg", inp.get("title") or ""
        if tool == "update_plan":
            return "plan", ""
        return "run", tool
    if name == "TodoWrite":
        todos = inp.get("todos") or []
        done = sum(1 for t in todos if isinstance(t, dict) and t.get("status") == "completed")
        return "plan", "%d/%d" % (done, len(todos))
    if name in ("TaskCreate", "TaskUpdate"):
        return "plan", ""
    return "think", name


# ----------------------------------------------------------------- Vorlesen, Freigabe am Knopf, Ball werfen
# Stimmen: die neueren Windows-Stimmen (WinRT/OneCore) klingen natuerlicher und es gibt Mann und Frau.
# Fehlen sie, wird die klassische Stimme (System.Speech, z.B. Hedda) genommen.
VOICES = {"frau": "Microsoft Katja", "mann": "Microsoft Stefan"}
VOICE_LABEL = {"frau": "Frau (Katja)", "mann": "Mann (Stefan)"}
WINRT_TTS = r"""
param([string]$TextFile, [string]$OutFile, [string]$Voice, [double]$Rate)
Add-Type -AssemblyName System.Runtime.WindowsRuntime
[void][Windows.Media.SpeechSynthesis.SpeechSynthesizer, Windows.Media.SpeechSynthesis, ContentType = WindowsRuntime]
[void][Windows.Storage.Streams.DataReader, Windows.Storage.Streams, ContentType = WindowsRuntime]
$asTask = ([System.WindowsRuntimeSystemExtensions].GetMethods() | Where-Object {
  $_.Name -eq 'AsTask' -and $_.GetParameters().Count -eq 1 -and $_.GetParameters()[0].ParameterType.Name -eq 'IAsyncOperation`1' })[0]
function Await($op, [Type]$t) { $task = $asTask.MakeGenericMethod($t).Invoke($null, @($op)); $task.Wait(-1) | Out-Null; $task.Result }
$s = New-Object Windows.Media.SpeechSynthesis.SpeechSynthesizer
$v = [Windows.Media.SpeechSynthesis.SpeechSynthesizer]::AllVoices | Where-Object { $_.DisplayName -eq $Voice } | Select-Object -First 1
if (-not $v) { exit 3 }
$s.Voice = $v
try { $s.Options.SpeakingRate = $Rate } catch {}
$text = [IO.File]::ReadAllText($TextFile, [Text.Encoding]::UTF8)
$stream = Await ($s.SynthesizeTextToStreamAsync($text)) ([Windows.Media.SpeechSynthesis.SpeechSynthesisStream])
$r = New-Object Windows.Storage.Streams.DataReader($stream.GetInputStreamAt(0))
[void](Await ($r.LoadAsync([uint32]$stream.Size)) ([uint32]))
$b = New-Object byte[] ([int]$stream.Size)
$r.ReadBytes($b)
[IO.File]::WriteAllBytes($OutFile, $b)
"""


def voice_for(host=None):
    """"frau" oder "mann": je Buddy (config "stimmen" {ip: art}), sonst die allgemeine Wahl (config "stimme_art")."""
    cfg = load_cfg()
    return (cfg.get("stimmen") or {}).get(host) or cfg.get("stimme_art", "frau")


def to16k_mono(path):
    """WAV-Datei in 16 kHz, mono, 16 Bit umrechnen (so spielt sie der Buddy)."""
    import wave
    import numpy as np
    with wave.open(path, "rb") as w:
        ch, sw, sr, n = w.getnchannels(), w.getsampwidth(), w.getframerate(), w.getnframes()
        raw = w.readframes(n)
    if sw != 2:
        return False
    x = np.frombuffer(raw, dtype="<i2").astype(np.float32)
    if ch > 1:
        x = x.reshape(-1, ch).mean(axis=1)
    if sr != 16000 and len(x):
        t = np.arange(0, len(x) / sr, 1 / 16000.0)
        x = np.interp(t, np.arange(len(x)) / sr, x)
    with wave.open(path, "wb") as w:
        w.setnchannels(1)
        w.setsampwidth(2)
        w.setframerate(16000)
        w.writeframes(np.clip(x, -32768, 32767).astype("<i2").tobytes())
    return True


def tts_wav(text, art=None):
    """Text -> WAV-Bytes (16 kHz, mono, 16 Bit), offline mit einer Windows-Stimme. art: "frau" / "mann"."""
    import subprocess
    import tempfile
    d = tempfile.gettempdir()
    tp, wp = os.path.join(d, "buddy-sag.txt"), os.path.join(d, "buddy-sag.wav")
    with open(tp, "w", encoding="utf-8") as f:
        f.write(text)
    nowin = getattr(subprocess, "CREATE_NO_WINDOW", 0)
    art = art or voice_for()
    try:  # neuere Windows-Stimmen (Mann/Frau)
        ps1 = os.path.join(d, "buddy-tts.ps1")
        with open(ps1, "w", encoding="utf-8-sig") as f:
            f.write(WINRT_TTS)
        if os.path.exists(wp):
            os.remove(wp)
        r = subprocess.run(["powershell", "-NoProfile", "-NonInteractive", "-ExecutionPolicy", "Bypass", "-File", ps1,
                            "-TextFile", tp, "-OutFile", wp, "-Voice", VOICES.get(art, VOICES["frau"]), "-Rate", "1.05"],
                           capture_output=True, timeout=30, creationflags=nowin)
        if r.returncode == 0 and os.path.exists(wp) and os.path.getsize(wp) > 2000 and to16k_mono(wp):
            return loud_wav(wp)
    except Exception:
        pass
    stimme = load_cfg().get("stimme", "Microsoft Hedda Desktop")  # klassische Stimme als Rueckfall
    ps = ("Add-Type -AssemblyName System.Speech; $s = New-Object System.Speech.Synthesis.SpeechSynthesizer; "
          "try { $s.SelectVoice('%s') } catch {}; $s.Rate = 1; "
          "$f = New-Object System.Speech.AudioFormat.SpeechAudioFormatInfo(16000, "
          "[System.Speech.AudioFormat.AudioBitsPerSample]::Sixteen, [System.Speech.AudioFormat.AudioChannel]::Mono); "
          "$s.SetOutputToWaveFile('%s', $f); $s.Speak([IO.File]::ReadAllText('%s', [Text.Encoding]::UTF8)); $s.Dispose()") % (stimme, wp, tp)
    subprocess.run(["powershell", "-NoProfile", "-NonInteractive", "-Command", ps], capture_output=True, timeout=20,
                   creationflags=nowin)
    return loud_wav(wp)


def loud_wav(path, drive=2.2):
    """WAV voll aussteuern und sanft verdichten (der kleine Lautsprecher braucht Pegel, leise Silben werden hoerbar)."""
    import array
    import io
    import math
    import wave
    with wave.open(path, "rb") as w:
        par = w.getparams()
        a = array.array("h")
        a.frombytes(w.readframes(w.getnframes()))
    peak = max((abs(x) for x in a), default=0) or 1
    k = math.tanh(drive)
    out = array.array("h", (int(math.tanh(drive * x / peak) / k * 31500) for x in a))
    buf = io.BytesIO()
    with wave.open(buf, "wb") as w:
        w.setparams(par)
        w.writeframes(out.tobytes())
    return buf.getvalue()


def say(text):
    """Laesst alle Buddys mit Lautsprecher (Watcher, AMOLED) einen Satz sprechen (wenn "Vorlesen" an ist)."""
    import threading
    import urllib.request
    text = (text or "").strip()
    if not text or not load_cfg().get("vorlesen", True):
        return False
    hosts = mic_hosts()  # wer ein Mikrofon hat, hat auch einen Lautsprecher
    if not hosts:
        return False
    wavs = {}
    for h in hosts:  # jeder Buddy mit seiner Stimme; gleiche Stimmen nur einmal erzeugen
        art = voice_for(h)
        if art not in wavs:
            wavs[art] = tts_wav(text, art)
    ok = []

    def one(h):
        wav = wavs[voice_for(h)]
        bnd = "----buddysay%d" % int(time.time() * 1000)
        body = (("--%s\r\nContent-Disposition: form-data; name=\"f\"; filename=\"sag.wav\"\r\n"
                 "Content-Type: audio/wav\r\n\r\n") % bnd).encode() + wav + ("\r\n--%s--\r\n" % bnd).encode()
        req = urllib.request.Request("http://%s/say" % h, data=body, headers={"Content-Type": "multipart/form-data; boundary=" + bnd})
        try:
            if urllib.request.urlopen(req, timeout=10).read().startswith(b"ok"):
                ok.append(h)
        except Exception:
            pass
    th = [threading.Thread(target=one, args=(h,)) for h in hosts]
    for t in th:
        t.start()
    for t in th:
        t.join()
    return bool(ok)


def say_on(host, text, art=None):
    """Einen Satz auf genau einem Buddy sprechen (Probe der Stimme, Gespraeche). Liefert die Dauer in s oder 0."""
    import urllib.request
    wav = tts_wav(text, art or voice_for(host))
    bnd = "----buddysay%d" % int(time.time() * 1000)
    body = (("--%s\r\nContent-Disposition: form-data; name=\"f\"; filename=\"sag.wav\"\r\n"
             "Content-Type: audio/wav\r\n\r\n") % bnd).encode() + wav + ("\r\n--%s--\r\n" % bnd).encode()
    req = urllib.request.Request("http://%s/say" % host, data=body, headers={"Content-Type": "multipart/form-data; boundary=" + bnd})
    try:
        if urllib.request.urlopen(req, timeout=10).read().startswith(b"ok"):
            return max(0.0, (len(wav) - 44) / 32000.0)
    except Exception:
        pass
    return 0


def last_answer(ev):
    """Letzte Antwort von Claude (Text) aus dem Hook bzw. dem Gespraechsprotokoll."""
    t = ev.get("last_assistant_message")
    if isinstance(t, str) and t.strip():
        return t
    p = ev.get("transcript_path")
    if not p or not os.path.exists(p):
        return ""
    try:
        with open(p, encoding="utf-8") as f:
            lines = f.readlines()[-200:]
    except OSError:
        return ""
    for line in reversed(lines):
        try:
            e = json.loads(line)
        except Exception:
            continue
        m = e.get("message") or {}
        if e.get("type") != "assistant" or m.get("role") != "assistant":
            continue
        c = m.get("content")
        txt = c if isinstance(c, str) else " ".join(b.get("text", "") for b in (c or []) if isinstance(b, dict) and b.get("type") == "text")
        if txt.strip():
            return txt
    return ""


def speakable(text, n=220):
    """Ersten Satz (oder zwei kurze) einer Antwort fuer die Sprachausgabe aufbereiten."""
    import re
    t = re.sub(r"```.*?```", " ", text, flags=re.S)
    t = re.sub(r"`([^`]*)`", r"\1", t)
    t = re.sub(r"\[([^\]]*)\]\([^)]*\)", r"\1", t)
    t = re.sub(r"https?://\S+", "", t)
    t = re.sub(r"[*_#>|]+", " ", t)
    t = re.sub(r"\s+", " ", t).strip()
    out = ""
    for s in re.split(r"(?<=[.!?])\s+", t):
        if len(out) + len(s) > n and out:
            break
        out += (" " if out else "") + s
        if len(out) > 60:
            break
    return out[:n]


def ask_knob(text, wait=None):
    """Freigabe am Watcher erfragen: 'allow', 'deny' oder None (keiner hat geantwortet / kein Watcher)."""
    import random
    import urllib.parse
    import urllib.request
    wait = load_cfg().get("freigabe_sek", 20) if wait is None else wait
    if not wait:
        return None
    host = watcher_host()
    if not host:
        return None
    fid = random.randint(1, 999999)
    try:
        urllib.request.urlopen("http://%s/cmd?%s" % (host, urllib.parse.urlencode({"l": "F %d|%s" % (fid, ascii_only(text, 70))})), timeout=3).read()
    except Exception:
        return None
    t = time.time()
    while time.time() - t < wait:
        time.sleep(0.3)
        try:
            st = json.loads(urllib.request.urlopen("http://%s/frage" % host, timeout=2).read())
        except Exception:
            continue
        if st.get("id") == fid and st.get("a") in (1, 2):
            return "allow" if st["a"] == 1 else "deny"
    try:  # niemand hat geantwortet: Frage zurueckziehen, Claude fragt dann am PC
        urllib.request.urlopen("http://%s/cmd?l=F%%200" % host, timeout=2).read()
    except Exception:
        pass
    return None


def maybe_throw(sid):
    """Wechselt die Arbeit zu einer anderen Claude-Sitzung, wirft ein Buddy dem anderen einen Ball zu (Ping-Pong)."""
    import urllib.request
    cfg = load_cfg()
    now = time.time()
    last, last_t = cfg.get("wurf_sid"), cfg.get("wurf_t", 0)
    if sid == last:
        if now - last_t > 30:
            cfg["wurf_t"] = now
            save_cfg(cfg)
        return
    cfg["wurf_sid"], cfg["wurf_t"] = sid, now
    devs = sorted((cfg.get("devices") or {}).keys())
    if not last or now - last_t > 600 or now - cfg.get("wurf_zuletzt", 0) < 15 or len(devs) < 2:
        save_cfg(cfg)
        return
    von = cfg.get("wurf_von") if cfg.get("wurf_von") in devs else devs[0]
    zu = next(d for d in devs if d != von)
    cfg["wurf_von"], cfg["wurf_zuletzt"] = zu, now  # naechstes Mal andersherum
    save_cfg(cfg)
    try:
        urllib.request.urlopen("http://%s/cmd?l=Y%%201" % von, timeout=2).read()
        time.sleep(0.75)  # Ball fliegt aus dem einen Bild ...
        urllib.request.urlopen("http://%s/cmd?l=Y%%202" % zu, timeout=2).read()  # ... und ins andere
    except Exception:
        pass


def plan_progress(sid, name, inp):
    """(erledigt, gesamt) der Aufgabenliste, wenn sich etwas aendert; je Sitzung in config.json gemerkt."""
    items = None
    if name == "TodoWrite":
        items = [t.get("status") for t in inp.get("todos") or [] if isinstance(t, dict)]
    elif name.endswith("update_plan"):
        if inp.get("items"):
            items = [t.get("status") for t in inp["items"] if isinstance(t, dict)]
        else:
            cfg = load_cfg()
            plan = (cfg.get("plaene") or {}).get(sid)
            if not plan:
                return None
            done, total = plan
            if inp.get("advance"):
                done += 1
            done += len(inp.get("done") or [])
            done = min(done, total)
            cfg.setdefault("plaene", {})[sid] = [done, total]
            save_cfg(cfg)
            return done, total
    if items is None:
        return None
    done, total = sum(1 for x in items if x == "completed"), len(items)
    cfg = load_cfg()
    pl = cfg.setdefault("plaene", {})
    pl[sid] = [done, total]
    if len(pl) > 20:  # alte Sitzungen vergessen
        for k in list(pl)[:-20]:
            del pl[k]
    save_cfg(cfg)
    return done, total


def handle_hook():
    try:
        ev = json.loads(sys.stdin.buffer.read().decode("utf-8", "replace") or "{}")
    except Exception:
        ev = {}
    out = handle_event(ev)
    if out:
        print(out)
    sys.exit(0)  # Hooks duerfen Claude nie aufhalten


def handle_event(ev):
    """Ein Hook-Ereignis (JSON von Claude Code) an die Buddys weitergeben. Liefert die Hook-Ausgabe (meist leer)."""
    out = ""
    global LOG_SESSION
    LOG_SESSION = str(ev.get("session_id", ""))
    name = ev.get("hook_event_name", "")
    cwd = base(ev.get("cwd", ""))
    sid = str(ev.get("session_id", ""))[:8]  # jede Claude-Code-Sitzung bekommt am Buddy eine eigene Figur

    def send(st, d=""):
        send_state(st, d, sid, cwd)
    if name in ("SessionStart", "UserPromptSubmit"):
        try:
            maybe_throw(sid)
        except Exception:
            pass
    if name == "SessionStart":
        send("hello")
    elif name == "UserPromptSubmit":
        send("think")
    elif name == "PreToolUse":
        st, d = tool_state(ev.get("tool_name", ""), ev.get("tool_input"))
        send(st, d)
        try:
            pr = plan_progress(sid, ev.get("tool_name", ""), ev.get("tool_input") or {})
            if pr:
                send_line("PR %d/%d" % pr)
        except Exception:
            pass
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
        tool = ev.get("tool_name", "")
        st, d = tool_state(tool, ev.get("tool_input"))
        send("need", d)  # zeigt, wofuer Claude die Erlaubnis braucht
        try:  # am Watcher-Knopf beantworten lassen (sonst normale Abfrage am PC)
            ans = ask_knob("%s: %s" % (tool, d) if d else tool)
        except Exception:
            ans = None
        if ans:
            dec = {"behavior": ans}
            if ans == "deny":
                dec["message"] = "Am Claude-Buddy (Watcher) abgelehnt."
            out = json.dumps({"hookSpecificOutput": {"hookEventName": "PermissionRequest", "decision": dec}})
            send("think")
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
        try:  # Ergebnis in einem Satz vorlesen (Watcher)
            say(speakable(last_answer(ev)))
        except Exception:
            pass
    elif name == "SessionEnd":
        send("bye")
    return out


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


AUTOSTART = os.path.join(os.environ.get("APPDATA") or "", "Microsoft", "Windows", "Start Menu", "Programs", "Startup",
                         "claude-buddy-zuhoeren.vbs")


def sprache(args=()):
    """Sprechen per Watcher-Knopf einrichten: faster-whisper installieren, Zuhoeren in den Autostart legen und starten."""
    import subprocess
    try:
        import faster_whisper  # noqa: F401
        print("faster-whisper ist da.")
    except ImportError:
        print("Installiere faster-whisper (Spracherkennung, offline) ...")
        subprocess.run([sys.executable, "-m", "pip", "install", "--disable-pip-version-check", "faster-whisper"], check=False)
    if os.name != "nt":
        print("Autostart gibt es nur unter Windows - bitte  python buddy.py zuhoeren  selbst starten.")
        return
    pyw = os.path.join(os.path.dirname(sys.executable), "pythonw.exe")
    if not os.path.exists(pyw):
        pyw = sys.executable
    me = os.path.abspath(__file__)
    vbs = ('\' Claude-Buddy: Sprechen per Watcher-Knopf (startet unsichtbar mit Windows)\r\n'
           'CreateObject("WScript.Shell").Run """%s"" ""%s"" zuhoeren", 0, False\r\n') % (pyw, me)
    os.makedirs(os.path.dirname(AUTOSTART), exist_ok=True)
    with open(AUTOSTART, "w", encoding="utf-16") as f:  # VBS mit Umlauten im Pfad: UTF-16
        f.write(vbs)
    print("Autostart eingerichtet:", AUTOSTART)
    if "--nicht-starten" not in args:
        subprocess.Popen(["wscript", AUTOSTART])
        print("Zuhoeren laeuft (Protokoll: %s)." % os.path.join(LOG_DIR, "zuhoeren.log"))
    print("Am Watcher: Knopf halten und sprechen - der Text landet im aktiven Fenster.")


def sprache_aus():
    if os.path.exists(AUTOSTART):
        os.remove(AUTOSTART)
        print("Autostart entfernt. (Ein laufendes Zuhoeren endet mit dem naechsten Neustart.)")


def install(args=()):
    """Traegt die Hooks fuer alle Claude-Code-Sitzungen ein (bestehende Einstellungen bleiben erhalten)."""
    p = settings_path()
    data = {}
    if os.path.exists(p):
        with open(p, encoding="utf-8") as f:
            data = json.load(f)
        if not os.path.exists(p + ".vor-buddy"):  # nur einmal: der Stand von vor dem Buddy
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
        if ev == "PermissionRequest":  # wartet auf die Antwort am Watcher-Knopf (danach normale Abfrage)
            h["timeout"] = 35
        elif ev != "SessionEnd":
            h["async"] = True  # Claude wartet nicht auf den Buddy
            if ev in ("Stop", "SessionStart", "UserPromptSubmit"):
                h["timeout"] = 25  # Vorlesen bzw. Ball werfen braucht etwas laenger
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
    # Sprechen per Knopf gibt es nur beim SenseCAP Watcher (hat ein Mikrofon)
    want = "--sprache" in args
    if not want and "--ohne-sprache" not in args and (himax_port() or watcher_host()):
        try:
            want = input("SenseCAP Watcher gefunden. Sprechen per Knopf einrichten (Autostart)? [J/n] ").strip().lower() in ("", "j", "ja", "y")
        except EOFError:
            want = False
    if want:
        sprache(args)


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
    sprache_aus()


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
            print("%s an %s, WLAN: %s, Firmware %s" % (BOARD_LABEL.get(BOARDS.get(p), "Buddy"), p, r[0], r[1]))
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
        r = ask_wlan(ip)
        if r:
            print("%s per WLAN %s (zuletzt an %s), Firmware %s" % (BOARD_LABEL.get(r[1], "Buddy"), ip, devs[ip] or "?", r[0]))
            seen.add(ip)
        else:
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
def ask_wlan(ip, timeout=1.5):
    """(version, art) eines Buddys im WLAN, None wenn er nicht antwortet. Aeltere Firmware nennt keine Art."""
    try:
        txt = _raw_get("http://%s/cmd?l=%%3F" % ip, timeout).strip()
    except Exception:
        return None
    if not txt.startswith("BUDDY"):
        return None
    parts = txt.split()
    board = parts[3] if len(parts) > 3 else ""
    if board:
        BOARDS[ip] = board
    return (parts[2] if len(parts) > 2 else "?"), board


def get_options(ip, timeout=4):
    """Einstellungen eines Buddys (ab Firmware mit Befehl "O") als dict, None wenn nicht erreichbar/zu alt."""
    import urllib.request
    try:
        txt = urllib.request.urlopen("http://%s/cmd?l=O" % ip, timeout=timeout).read().decode("utf-8", "replace")
        return json.loads(txt) if txt.startswith("{") else None
    except Exception:
        return None


def set_options(ip, **kv):
    """Einstellungen setzen, z.B. set_options(ip, vol=3, lcd=4). Liefert die neuen Werte (dict) oder None."""
    import urllib.parse
    import urllib.request
    line = "O " + ",".join("%s=%d" % (k, int(v)) for k, v in kv.items())
    try:
        txt = urllib.request.urlopen("http://%s/cmd?%s" % (ip, urllib.parse.urlencode({"l": line})), timeout=4).read().decode()
        return json.loads(txt) if txt.startswith("{") else None
    except Exception:
        return None


def mic_hosts():
    """WLAN-Adressen aller Buddys mit Mikrofon (Watcher, AMOLED): die beantworten /rec."""
    import urllib.request
    cfg = load_cfg()
    out = []
    for ip in list((cfg.get("devices") or {}).keys()) or ([cfg["host"]] if cfg.get("host") else []):
        r = ask_wlan(ip)
        if not r or r[1] == "tdisplay":
            continue
        try:
            with urllib.request.urlopen("http://%s/rec" % ip, timeout=1.5) as resp:
                if resp.status == 200:
                    out.append(ip)
        except Exception:
            continue
    return out


def watcher_host():
    """WLAN-Adresse des Buddys mit Kamera und SD-Karte (der Watcher); None wenn keiner antwortet."""
    import urllib.request
    cfg = load_cfg()
    ips = list((cfg.get("devices") or {}).keys()) or ([cfg["host"]] if cfg.get("host") else [])
    for ip in ips:
        r = ask_wlan(ip)
        if r and r[1] in ("", "watcher"):  # "" = aeltere Firmware (nur der Watcher hatte /zeitraffer)
            try:
                with urllib.request.urlopen("http://%s/zeitraffer" % ip, timeout=1.5) as resp:
                    if resp.status == 200:
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


# ----------------------------------------------------------------- Sprechen (Watcher-Knopf halten)
# Der Watcher nimmt auf, solange der Knopf gehalten wird. "zuhoeren" fragt /rec ab, holt /rec.wav,
# erkennt den Text offline mit faster-whisper und fuegt ihn ins aktive Fenster ein (+ Enter).
LOG_DIR = os.path.join(os.environ.get("LOCALAPPDATA") or os.path.expanduser("~"), "claude-buddy")
WHISPER_MODEL = "small"
WHISPER_HINT = "Claude, Claude Code, Buddy, Watcher, ESP32, T-Display, PlatformIO, GitHub, Commit, Push, Firmware, Python."


def zlog(msg):
    os.makedirs(LOG_DIR, exist_ok=True)
    line = time.strftime("%H:%M:%S ") + msg
    print(line, flush=True)
    try:
        with open(os.path.join(LOG_DIR, "zuhoeren.log"), "a", encoding="utf-8") as f:
            f.write(time.strftime("%Y-%m-%d ") + line + "\n")
    except OSError:
        pass


def clip_get():
    import ctypes
    from ctypes import wintypes
    u, k = ctypes.windll.user32, ctypes.windll.kernel32
    u.GetClipboardData.restype = wintypes.HANDLE
    u.GetClipboardData.argtypes = [wintypes.UINT]
    k.GlobalLock.restype = wintypes.LPVOID
    k.GlobalLock.argtypes = [wintypes.HGLOBAL]
    k.GlobalUnlock.argtypes = [wintypes.HGLOBAL]
    u.OpenClipboard.argtypes = [wintypes.HWND]
    if not u.OpenClipboard(None):
        return None
    try:
        h = u.GetClipboardData(13)  # CF_UNICODETEXT
        if not h:
            return None
        p = k.GlobalLock(h)
        txt = ctypes.wstring_at(p) if p else None
        k.GlobalUnlock(h)
        return txt
    finally:
        u.CloseClipboard()


def clip_set(text):
    import ctypes
    from ctypes import wintypes
    u, k = ctypes.windll.user32, ctypes.windll.kernel32
    k.GlobalAlloc.restype = wintypes.HGLOBAL
    k.GlobalAlloc.argtypes = [wintypes.UINT, ctypes.c_size_t]
    k.GlobalLock.restype = wintypes.LPVOID
    k.GlobalLock.argtypes = [wintypes.HGLOBAL]
    k.GlobalUnlock.argtypes = [wintypes.HGLOBAL]
    u.OpenClipboard.argtypes = [wintypes.HWND]
    u.SetClipboardData.argtypes = [wintypes.UINT, wintypes.HANDLE]
    u.SetClipboardData.restype = wintypes.HANDLE
    data = (text + "\0").encode("utf-16-le")
    for _ in range(10):
        if u.OpenClipboard(None):
            break
        time.sleep(0.05)
    else:
        return False
    try:
        u.EmptyClipboard()
        h = k.GlobalAlloc(0x0002, len(data))  # GMEM_MOVEABLE
        p = k.GlobalLock(h)
        ctypes.memmove(p, data, len(data))
        k.GlobalUnlock(h)
        u.SetClipboardData(13, h)
        return True
    finally:
        u.CloseClipboard()


def type_text(text, enter=True):
    """Text ueber die Zwischenablage ins aktive Fenster einfuegen (Strg+V), optional Enter; alte Zwischenablage zurueck."""
    import ctypes
    kb = ctypes.windll.user32.keybd_event
    old = clip_get()
    if not clip_set(text):
        return False
    time.sleep(0.05)
    kb(0x11, 0, 0, 0)          # Strg
    kb(0x56, 0, 0, 0)          # V
    kb(0x56, 0, 2, 0)
    kb(0x11, 0, 2, 0)
    if enter:
        time.sleep(0.25)
        kb(0x0D, 0, 0, 0)      # Enter
        kb(0x0D, 0, 2, 0)
    time.sleep(0.4)
    if old is not None:
        clip_set(old)
    return True


def transcribe(model, wav):
    """WAV-Bytes (16 kHz, mono, 16 Bit vom Watcher) -> Text. Liest die WAV selbst (ohne PyAV)."""
    import io
    import wave
    import numpy as np
    with wave.open(io.BytesIO(wav), "rb") as w:
        pcm = np.frombuffer(w.readframes(w.getnframes()), dtype="<i2").astype(np.float32) / 32768.0
    if len(pcm) < 1600:
        return ""
    segs, _ = model.transcribe(pcm, language="de", beam_size=5, vad_filter=True, initial_prompt=WHISPER_HINT)
    return " ".join(s.text.strip() for s in segs).strip()


# ----------------------------------------------------------------- Wetter und Plaudereien (laeuft im Zuhoeren mit)
# Wetter von Open-Meteo (ohne Konto) fuer den Ort aus config.json ("lat", "lon"), alle 20 Minuten an alle Buddys.
# Sind beide Buddys untaetig, plaudern sie ab und zu miteinander (Sprechblasen, Befehl "C <text>").
PLAUDEREIEN = [
    [(0, "Psst... bist du wach?"), (1, "Jetzt schon!"), (0, "~wave"), (1, "~wave")],
    [(0, "Ganz schoen ruhig hier."), (1, "Pssst, er denkt nach!")],
    [(0, "Was machst du so?"), (1, "Ich warte auf Arbeit."), (0, "Ich auch!")],
    [(0, "Ich hab heute schon viel gelernt."), (1, "Angeber!"), (0, "Hehe.")],
    [(0, "Weisst du einen Witz?"), (1, "Was macht ein Pirat am PC?"), (1, "Er drueckt Enter!"), (0, "Hahaha!")],
    [(0, "Meine Pflanze waechst!"), (1, "Meine auch!"), (0, "Wettgiessen?")],
    [(0, "~wave"), (1, "Huhu!"), (0, "Huhu zurueck!")],
    [(0, "Ob er gleich wieder tippt?"), (1, "Bestimmt!"), (0, "Ich bin bereit.")],
    [(0, "Ich hab Hunger."), (1, "Wir essen Strom."), (0, "Lecker Strom!")],
    [(0, "Wie spaet ist es?"), (1, "Zeit fuer Code!")],
    [(0, "Gibts was Neues?"), (1, "Alles gruen bei mir."), (0, "Prima!")],
    [(0, "Schoenes Wetter heute?"), (1, "Ich seh nur Pixel."), (0, "Hihi.")],
    [(0, "Magst du Kaffee?"), (1, "Nur Bits und Bytes."), (0, "Ich auch.")],
    [(0, "Lass uns tanzen!"), (1, "Ohne Musik?"), (0, "Na gut, spaeter.")],
]


import threading
ZUHOEREN = {}  # Zustand fuer das Windows-Programm (Sperre, Modell geladen ...)
WX_EVENT = threading.Event()  # gesetzt, wenn ein Buddy kein Wetter hat (z.B. nach einem Neustart)


def extras_loop():
    """Hintergrund: Wetter holen und verteilen, Buddys plaudern lassen."""
    import random
    import urllib.parse
    import urllib.request

    def to_all(line, devs):
        for ip in devs:
            try:
                urllib.request.urlopen("http://%s/cmd?%s" % (ip, urllib.parse.urlencode({"l": line})), timeout=2).read()
            except Exception:
                pass

    next_wx, next_chat = 0, time.time() + random.uniform(180, 420)
    while True:
        try:
            cfg = load_cfg()
            devs = list((cfg.get("devices") or {}).keys())
            now = time.time()
            if WX_EVENT.is_set():
                WX_EVENT.clear()
                next_wx = 0
            if now >= next_wx and devs:
                next_wx = now + 20 * 60
                lat, lon = cfg.get("lat"), cfg.get("lon")
                if lat is not None and lon is not None:
                    url = ("https://api.open-meteo.com/v1/forecast?latitude=%s&longitude=%s"
                           "&current=weather_code,is_day,temperature_2m&timezone=auto") % (lat, lon)
                    cur = json.loads(urllib.request.urlopen(url, timeout=10).read())["current"]
                    line = "E %d|%d|%d" % (cur["weather_code"], cur["is_day"], round(cur["temperature_2m"]))
                    to_all(line, devs)
                    zlog("Wetter: Code %s, %s, %.0f Grad" % (cur["weather_code"], "Tag" if cur["is_day"] else "Nacht", cur["temperature_2m"]))
                if cfg.get("geburtstag"):
                    to_all("G " + cfg["geburtstag"], devs)
            if now >= next_chat:
                next_chat = now + random.uniform(240, 600)
                if len(devs) >= 2 and cfg.get("plaudern", True):
                    states = []
                    for ip in devs[:2]:
                        try:
                            states.append(urllib.request.urlopen("http://%s/" % ip, timeout=2).read().decode("ascii", "replace"))
                        except Exception:
                            states.append("")
                    if all(s.endswith(("idle", "wait")) for s in states):
                        pair = devs[:2]
                        random.shuffle(pair)
                        for who, text in random.choice(PLAUDEREIEN):
                            to_all("C " + ascii_only(text, 40), [pair[who]])
                            time.sleep(1.6 if text == "~wave" else 3.0)
        except Exception as e:
            zlog("Extras: %s" % e)
        WX_EVENT.wait(15)


def zuhoeren(args):
    """Laeuft dauerhaft: Sprachaufnahmen vom Watcher holen, erkennen, einfuegen."""
    import socket
    import tempfile
    import urllib.parse
    import urllib.request
    try:  # nur einmal gleichzeitig (auch nicht neben dem Windows-Programm)
        lock = socket.socket()
        lock.bind(("127.0.0.1", 47811))
    except OSError:
        print("zuhoeren laeuft schon.")
        return
    ZUHOEREN["lock"] = lock
    enter = load_cfg().get("sprache_enter", True) and "--ohne-enter" not in args
    zlog("lade Spracherkennung (%s) ..." % WHISPER_MODEL)
    from faster_whisper import WhisperModel
    model = WhisperModel(WHISPER_MODEL, device="cpu", compute_type="int8")
    ZUHOEREN["bereit"] = True
    zlog("bereit - Knopf am Buddy halten und sprechen")
    import threading
    threading.Thread(target=extras_loop, daemon=True).start()  # Wetter + Plaudereien
    hosts, last_find = [], 0
    polls, beat, wx_asked = 0, 0, 0
    last_st, trace_until, fails, pair_asked = {}, {}, {}, {}
    while True:
        if not hosts or time.time() - last_find > 60:
            try:
                found = mic_hosts()
            except Exception:
                found = []
            last_find = time.time()
            for h in found:
                if h not in hosts:
                    zlog("Buddy mit Mikrofon: %s (%s)" % (h, BOARD_LABEL.get(BOARDS.get(h), "?")))
            hosts = found or hosts
            if not hosts:
                time.sleep(3)
                continue
        for host in list(hosts):
            try:
                tq = time.time()
                st = json.loads(urllib.request.urlopen("http://%s/rec" % host, timeout=1.5).read())
                fails[host] = 0
                polls += 1
                if st.get("wx") == 0 and time.time() - wx_asked > 60:  # Buddy hat kein Wetter: sofort schicken
                    wx_asked = time.time()
                    WX_EVENT.set()
                if st["st"] != last_st.get(host):
                    if st["st"]:
                        zlog("%s: %s" % (host, {1: "nimmt auf", 2: "Aufnahme wartet", 3: "abgeholt"}.get(st["st"], st["st"])))
                        if st["st"] == 1:
                            trace_until[host] = time.time() + 15
                    last_st[host] = st["st"]
                if time.time() < trace_until.get(host, 0):  # Fehlersuche: jede Abfrage nach Aufnahmebeginn mitschreiben
                    zlog("  %s Abfrage: %s (%.2f s)" % (host, st, time.time() - tq))
                if polls == 1 or time.time() - beat > 600:  # Lebenszeichen im Protokoll
                    beat = time.time()
                    zlog("lebt (%d Abfragen, %d Buddys, %s meldet %s)" % (polls, len(hosts), host, st))
                # st 2 = Aufnahme wartet auf den PC (nach dem Abholen wird daraus 3). Die Nummer allein reicht nicht:
                # nach einem Neustart (z.B. Update) faengt sie wieder bei 1 an.
                if st["st"] == 2:
                    wav = urllib.request.urlopen("http://%s/rec.wav" % host, timeout=10).read()
                    t0 = time.time()
                    text = transcribe(model, wav)
                    zlog("erkannt in %.1f s (%.1f s Ton): %s" % (time.time() - t0, st["ms"] / 1000, text or "-"))
                    show = ascii_only(text, 66)
                    urllib.request.urlopen("http://%s/cmd?%s" % (host, urllib.parse.urlencode({"l": "R " + show if show else "R"})), timeout=3).read()
                    if text:
                        type_text(text, enter)
            except KeyboardInterrupt:
                return
            except Exception as e:  # WLAN-Aussetzer (z.B. Hand ueber der Antenne) oder Buddy startet neu
                if getattr(e, "code", 0) == 401 and time.time() - pair_asked.get(host, 0) > 600 and paired_ok(host) is False:
                    pair_asked[host] = time.time()
                    zlog("%s ist nicht gekoppelt - frage per Knopfdruck" % host)
                    zlog("gekoppelt" if button_pair(host, quiet=True) else "nicht gekoppelt (python buddy.py koppeln)")
                    continue
                fails[host] = fails.get(host, 0) + 1
                if fails[host] <= 3 or fails[host] % 20 == 0:
                    zlog("%s Fehler (%d): %s" % (host, fails[host], e))
                if fails[host] >= 10:  # laenger weg: nicht mehr abfragen, bis er wieder gefunden wird
                    hosts.remove(host)
                    fails[host] = 0
        time.sleep(0.35 if len(hosts) < 2 else 0.2)


def foto_save(jpg, show=True, rotate=None):
    """JPEG speichern (ggf. gedreht), letztes.jpg aktualisieren, alte aufraeumen, als Polaroid zeigen."""
    os.makedirs(FOTO_DIR, exist_ok=True)
    path = os.path.join(FOTO_DIR, time.strftime("foto-%Y%m%d-%H%M%S.jpg"))
    if rotate is None:
        # Die Kamera sitzt fest im Watcher: ist sein Display gedreht (Einbaulage), das Foto genauso drehen.
        # Dazu kommt eine von Hand gemerkte Korrektur (foto --drehen .. --merken).
        rotate = load_cfg().get("foto_drehen", 0)
        try:
            host = watcher_host()
            o = get_options(host, 3) if host else None
            if o and o.get("rot"):
                rotate = (rotate + 90 * int(o["rot"])) % 360
        except Exception:
            pass
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
    elif cmd == "sag":  # Watcher etwas sagen lassen (Test der Stimme)
        print("ok" if say(" ".join(sys.argv[2:]) or "Hallo, ich bin dein Claude-Buddy.") else "nicht geklappt (Watcher im WLAN? Vorlesen an?)")
    elif cmd == "frage":  # Freigabe am Knopf testen
        print(ask_knob(" ".join(sys.argv[2:]) or "Bash: echo Test") or "keine Antwort")
    elif cmd == "ort":  # Wetter-Ort festlegen: python buddy.py ort Cottbus
        import urllib.parse
        import urllib.request
        q = " ".join(sys.argv[2:])
        r = json.loads(urllib.request.urlopen("https://geocoding-api.open-meteo.com/v1/search?" +
                                              urllib.parse.urlencode({"name": q, "count": 1, "language": "de"}), timeout=10).read())
        if not r.get("results"):
            print("Ort nicht gefunden (Stadtname probieren, Postleitzahlen kennt der Dienst oft nicht).")
        else:
            res = r["results"][0]
            c = load_cfg()
            c["ort"], c["lat"], c["lon"] = res["name"], round(res["latitude"], 3), round(res["longitude"], 3)
            save_cfg(c)
            print("Wetter fuer %s (%s, %s) - kommt mit dem naechsten Zuhoeren-Durchlauf" % (res["name"], c["lat"], c["lon"]))
    elif cmd == "geburtstag":  # python buddy.py geburtstag 24.12.
        import re
        m = re.match(r"\s*(\d{1,2})\.(\d{1,2})", " ".join(sys.argv[2:]))
        if m:
            c = load_cfg()
            c["geburtstag"] = "%02d-%02d" % (int(m.group(2)), int(m.group(1)))
            save_cfg(c)
            send_line("G " + c["geburtstag"])
            print("Geburtstag gespeichert (nur Tag und Monat).")
        else:
            print("Bitte als TT.MM. angeben, z.B. 24.12.")
    elif cmd == "plaudern":  # beide Buddys sofort plaudern lassen (Test)
        import random
        import urllib.parse
        import urllib.request
        devs = list((load_cfg().get("devices") or {}).keys())[:2]
        if len(devs) < 2:
            print("Dafuer braucht es zwei Buddys im WLAN.")
        else:
            random.shuffle(devs)
            for who, text in random.choice(PLAUDEREIEN):
                urllib.request.urlopen("http://%s/cmd?%s" % (devs[who], urllib.parse.urlencode({"l": "C " + ascii_only(text, 40)})), timeout=2).read()
                time.sleep(1.6 if text == "~wave" else 3.0)
            print("geplaudert")
    elif cmd == "wurf":  # Ball werfen testen (braucht zwei Buddys im WLAN)
        c = load_cfg()
        c["wurf_sid"], c["wurf_t"], c["wurf_zuletzt"] = "test-alt", time.time(), 0
        save_cfg(c)
        maybe_throw("test-neu")
        print("geworfen")
    elif cmd == "koppeln":
        koppeln(sys.argv[2:])
    elif cmd == "link":
        link()
    elif cmd == "flash":
        flash(sys.argv[2], sys.argv[3])
    elif cmd == "zuhoeren":
        zuhoeren(sys.argv[2:])
    elif cmd == "protokoll":
        protokoll()
    elif cmd == "update":
        print("ok - der Buddy sucht jetzt nach einem Update" if send_line("U") else "Geraet nicht erreicht")
    elif cmd == "install":
        install(sys.argv[2:])
    elif cmd == "sprache":
        if sys.argv[2:3] == ["aus"]:
            sprache_aus()
        else:
            sprache(sys.argv[2:])
    elif cmd == "uninstall":
        uninstall()
    else:
        print(__doc__)
