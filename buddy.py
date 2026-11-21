"""Claude-Buddy: schickt den Arbeitszustand von Claude Code an den SenseCAP Watcher.

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
                                  die anderen per Knopfdruck am Watcher (druecken = ja, drehen = nein)
  python buddy.py link            Browser-Adressen der Buddys mit Schluessel (z.B. fuer die SD-Seite)
  python buddy.py flash <ip> <firmware.bin>  Firmware per WLAN aufspielen (pio run -e watcher-wlan -t upload)

Sicherheit: Im WLAN nimmt ein Buddy Befehle nur von gekoppelten PCs an. Die Schluessel stehen in
pc/kopplung.json; geht etwas schief, koppelt buddy.py per USB oder Knopfdruck neu.

Verbindung: zuerst USB, sonst WLAN (IP aus config.json, sonst claude-buddy.local).
Alle Buddys bekommen die Meldung: angesteckte per USB (am zweiten Kanal des CH342 im Watcher),
alle anderen bekannten per WLAN.
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
CH342_VID, CH342_PID = 0x1A86, 0x55D2  # SenseCAP Watcher: Kanal x.2 = ESP32-S3 (x.0 ist der Kamera-Chip)
SCAN_EVERY = 20  # s: so oft nach neu angesteckten Buddys suchen


class Cfg(dict):
    """config.json als dict. Merkt sich den gelesenen Stand, damit save_cfg nur die eigenen Aenderungen schreibt."""
    _orig = None


_CFG_LOCK = None


def _cfg_lock():
    global _CFG_LOCK
    if _CFG_LOCK is None:
        import threading
        _CFG_LOCK = threading.RLock()
    return _CFG_LOCK


def _read_cfg():
    try:
        with open(CFG_FILE, encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return {}


def load_cfg():
    import copy
    c = Cfg(_read_cfg())
    c._orig = copy.deepcopy(dict(c))
    return c


_SPRACHE = []


def lang():
    """Sprache der Oberflaeche und der Stimme: "de" oder "en". Aus config.json ("sprache"), sonst die Windows-Sprache."""
    if not _SPRACHE:
        s = _read_cfg().get("sprache")
        if s not in ("de", "en"):
            s = "en"
            try:
                if os.name == "nt":
                    import ctypes
                    if ctypes.windll.kernel32.GetUserDefaultUILanguage() & 0x3FF == 0x07:  # Deutsch
                        s = "de"
                else:
                    import locale
                    if (locale.getlocale()[0] or os.environ.get("LANG", "")).lower().startswith("de"):
                        s = "de"
            except Exception:
                s = "de"
        _SPRACHE.append(s)
    return _SPRACHE[0]


def set_lang(s):
    cfg = load_cfg()
    cfg["sprache"] = "en" if s == "en" else "de"
    save_cfg(cfg)
    _SPRACHE[:] = [cfg["sprache"]]
    try:
        _voices_fuer_sprache()
    except NameError:  # beim Laden des Moduls noch nicht definiert
        pass


def L(de, en):
    """Text in der eingestellten Sprache."""
    return en if lang() == "en" else de


def save_cfg(cfg):
    """Nur die Schluessel schreiben, die sich seit load_cfg() geaendert haben, auf den aktuellen Stand der Datei.
    So ueberschreibt ein Teil des Programms mit einer alten Kopie nie, was ein anderer inzwischen gespeichert hat
    (z.B. "Sprechen per Knopf" aus dem Menue, waehrend ein Hook seine Zustaende speichert)."""
    import copy
    with _cfg_lock():
        if isinstance(cfg, Cfg) and cfg._orig is not None:
            cur = _read_cfg()
            orig = cfg._orig
            for k in set(cfg) | set(orig):
                if k not in cfg:
                    cur.pop(k, None)
                elif k not in orig or cfg[k] != orig[k]:
                    cur[k] = cfg[k]
            data = cur
        else:
            data = dict(cfg)
        try:
            tmp = CFG_FILE + ".tmp"
            with open(tmp, "w", encoding="utf-8") as f:
                json.dump(data, f, indent=2)
            os.replace(tmp, CFG_FILE)
        except Exception:
            pass
        if isinstance(cfg, Cfg):  # weiter benutzbar: ab jetzt gilt der gespeicherte Stand als gelesen
            cfg._orig = copy.deepcopy(dict(cfg))


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
        print("%s fragt jetzt \"Koppeln?\" - am Watcher druecken (drehen = nein)." % host)
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
            if p.vid == CH342_VID and p.pid == CH342_PID and (p.location or "").endswith(".2"):
                out.append(p.device)
        return out
    except Exception:
        return []


def fw_name(v):
    """Firmware-Version zum Anzeigen: Build 17 = "1.00", 18 = "1.01" ...; aeltere bleiben "v16"."""
    try:
        b = int(str(v).lstrip("v"))
    except Exception:
        return str(v)
    return "%d.%02d" % (1 + (b - 17) // 100, (b - 17) % 100) if b >= 17 else "v%d" % b


BOARDS = {}  # Port oder IP -> Geraeteart aus der Antwort auf "?" ("watcher")
BOARD_LABEL = {"watcher": "SenseCAP Watcher"}


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


def usb_ask(line, wait=1.5, until=None):
    """Eine Befehlszeile per USB schicken und die Antwort lesen (z. B. "O", "RA?"). None ohne USB-Buddy."""
    for p in usb_ports(load_cfg()) or find_ports():
        for _ in range(20):
            try:
                s = open_port(p)
                break
            except Exception as e:  # noqa: BLE001
                if "PermissionError" in repr(e) or "Zugriff" in str(e):
                    time.sleep(0.05)
                    continue
                s = None
                break
        else:
            s = None
        if not s:
            continue
        try:
            s.reset_input_buffer()
            s.write((line + "\n").encode("ascii", "replace"))
            s.flush()
            t, buf = time.time(), b""
            while time.time() - t < wait:
                buf += s.read(256)
                if until and until.encode() in buf and b"\n" in buf.split(until.encode(), 1)[1]:
                    break
            return buf.decode("utf-8", "replace")
        finally:
            s.close()
    return None


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
VOICES_DE = {"frau": "Microsoft Katja", "mann": "Microsoft Stefan"}
VOICES_EN = {"frau": "Microsoft Zira", "mann": "Microsoft David"}
VOICE_LABEL_DE = {"frau": "Frau (Katja)", "mann": "Mann (Stefan)"}
VOICE_LABEL_EN = {"frau": "Female (Zira)", "mann": "Male (David)"}
CLASSIC_EN = {"frau": "Microsoft Zira Desktop", "mann": "Microsoft David Desktop"}  # aeltere Windows-Stimmen
VOICES, VOICE_LABEL = VOICES_DE, VOICE_LABEL_DE


def _voices_fuer_sprache():
    """Stimmen und Namen passend zur eingestellten Sprache (nach einem Sprachwechsel neu setzen)."""
    global VOICES, VOICE_LABEL
    en = lang() == "en"
    VOICES = VOICES_EN if en else VOICES_DE
    VOICE_LABEL = VOICE_LABEL_EN if en else VOICE_LABEL_DE
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


# Linux: Piper (offline, neuronale Stimmen von rhasspy/piper-voices). Die Modelle laedt der Einrichtungsassistent.
PIPER_VOICES = {"mann": ("de_DE-thorsten-medium", "de/de_DE/thorsten/medium"),
                "frau": ("de_DE-kerstin-low", "de/de_DE/kerstin/low")}
PIPER_URL = "https://huggingface.co/rhasspy/piper-voices/resolve/main/%s/%s%s"
_PIPER = {}
_voices_fuer_sprache()
if os.name != "nt":
    VOICE_LABEL = {"frau": "Frau (Kerstin)", "mann": "Mann (Thorsten)"}


def piper_dir():
    return os.path.join(DATA, "stimmen")


def piper_model(art):
    """Pfad der Piper-Stimme (.onnx) oder None, wenn sie noch nicht geladen ist."""
    name = PIPER_VOICES.get(art, PIPER_VOICES["frau"])[0]
    pth = os.path.join(piper_dir(), name + ".onnx")
    return pth if os.path.exists(pth) and os.path.exists(pth + ".json") else None


def piper_download(art, progress=None):
    """Piper-Stimme (Modell + Beschreibung) laden; progress(0..100)."""
    import urllib.request
    name, sub = PIPER_VOICES[art]
    os.makedirs(piper_dir(), exist_ok=True)
    for ext in (".onnx.json", ".onnx"):
        dst = os.path.join(piper_dir(), name + ext)
        tmp = dst + ".tmp"
        with urllib.request.urlopen(PIPER_URL % (sub, name, ext), timeout=60) as r, open(tmp, "wb") as f:
            total, done = int(r.headers.get("Content-Length") or 0), 0
            while True:
                b = r.read(65536)
                if not b:
                    break
                f.write(b)
                done += len(b)
                if progress and total and ext == ".onnx":
                    progress(int(done * 100 / total))
        os.replace(tmp, dst)
    return piper_model(art)


def _piper_wav(text, art, wp):
    import wave
    model = piper_model(art)
    if not model:
        return False
    from piper import PiperVoice
    v = _PIPER.get(model) or PiperVoice.load(model)
    _PIPER[model] = v
    with wave.open(wp, "wb") as wf:
        if hasattr(v, "synthesize_wav"):  # piper-tts ab 1.3
            v.synthesize_wav(text, wf)
        else:
            v.synthesize(text, wf)
    return os.path.getsize(wp) > 2000


def tts_wav_linux(text, art):
    import shutil
    import subprocess
    import tempfile
    wp = os.path.join(tempfile.gettempdir(), "buddy-sag.wav")
    try:
        if _piper_wav(text, art, wp) and to16k_mono(wp):
            return loud_wav(wp)
    except Exception as e:
        zlog("Piper: %s" % e)
    esp = shutil.which("espeak-ng") or shutil.which("espeak")  # Rueckfall: klingt roboterhaft, geht aber immer
    if esp:
        subprocess.run([esp, "-v", "de+m3" if art == "mann" else "de+f3", "-s", "165", "-w", wp, text], timeout=30)
        if os.path.exists(wp) and to16k_mono(wp):
            return loud_wav(wp)
    raise RuntimeError("Keine Stimme: Piper-Stimmen im Programm laden oder espeak-ng installieren")


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
    if os.name != "nt":
        return tts_wav_linux(text, art or voice_for())
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
    if lang() == "en":
        stimme = CLASSIC_EN.get(art, CLASSIC_EN["frau"])  # fehlt David, nimmt SelectVoice die Standardstimme
    ps = ("Add-Type -AssemblyName System.Speech; $s = New-Object System.Speech.Synthesis.SpeechSynthesizer; "
          "try { $s.SelectVoice('%s') } catch { $v = $s.GetInstalledVoices() | Where-Object { $_.VoiceInfo.Culture.Name -like '"
          + lang() + "*' } | Select-Object -First 1; if ($v) { $s.SelectVoice($v.VoiceInfo.Name) } }; $s.Rate = 1; "
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


_SAY_GEN = [0]  # zaehlt die Antworten: eine neue beendet das Vorlesen der alten


# ---------------------------------------------------------------- Radio (Versuch)
RADIO_API = "https://de1.api.radio-browser.info/json/stations/search"


def radio_find(name):
    """Sender im freien Verzeichnis radio-browser.info suchen. Liefert (name, stream-url) oder None. Nur MP3."""
    import urllib.parse
    import urllib.request
    q = {"name": name, "codec": "MP3", "limit": 20, "hidebroken": "true", "order": "clickcount", "reverse": "true"}
    req = urllib.request.Request(RADIO_API + "?" + urllib.parse.urlencode(q), headers={"User-Agent": "ClaudeBuddy/1"})
    try:
        st = json.load(urllib.request.urlopen(req, timeout=10))
    except Exception as e:  # noqa: BLE001
        zlog("Radio-Suche: %r" % e)
        return None
    st = [x for x in st if x.get("url_resolved", "").startswith("http") and len(x["url_resolved"]) < 300]
    if not st:
        return None
    best = sorted(st, key=lambda x: (x.get("bitrate", 0) < 64, -x.get("clickcount", 0)))[0]
    import re
    nm = re.split(r"\s*[|(\[]", best["name"].strip())[0].strip() or best["name"].strip()  # "Deutschlandfunk | DLF | MP3" -> "Deutschlandfunk"
    return nm, best["url_resolved"]


# ---------------------------------------------------------------- Nutzungslimits von Claude (5 Stunden / Woche)
# Auf Wunsch des Nutzers: mit dem Anmelde-Schluessel, den Claude Code in ~/.claude/.credentials.json ablegt.
# Der Schluessel geht nur an Anthropic (wie bei Claude Code selbst), wird nie protokolliert und nie an den Watcher geschickt.
CLAUDE_CREDS = os.path.join(os.path.expanduser("~"), ".claude", ".credentials.json")
CLAUDE_CLIENT_ID = "9d1c250a-e61b-44d9-88ed-5944d1962f5e"  # oeffentliche Kennung von Claude Code (OAuth)
CLAUDE_TOKEN_URL = "https://platform.claude.com/v1/oauth/token"
CLAUDE_USAGE_URL = "https://api.anthropic.com/api/oauth/usage"


def _claude_oauth():
    try:
        with open(CLAUDE_CREDS, encoding="utf-8") as f:
            d = json.load(f)
        return d, d.get("claudeAiOauth") or {}
    except Exception:
        return None, {}


class _claude_lock:
    """Einfache Sperrdatei neben der Anmeldung (mehrere Buddy-Teile im selben Moment)."""
    P = CLAUDE_CREDS + ".buddy.lock"

    def __enter__(self):
        t = time.time()
        while time.time() - t < 15:
            try:
                self.fd = os.open(self.P, os.O_CREAT | os.O_EXCL | os.O_WRONLY)
                return self
            except FileExistsError:
                try:
                    if time.time() - os.path.getmtime(self.P) > 60:  # liegengeblieben
                        os.remove(self.P)
                        continue
                except OSError:
                    pass
                time.sleep(0.3)
        self.fd = None
        return self

    def __exit__(self, *a):
        if self.fd is not None:
            os.close(self.fd)
            try:
                os.remove(self.P)
            except OSError:
                pass


def _claude_refresh(d, o):
    """Abgelaufenen Schluessel erneuern wie Claude Code und zurueckschreiben (damit Claude Code angemeldet bleibt)."""
    import urllib.request
    body = json.dumps({"grant_type": "refresh_token", "refresh_token": o["refreshToken"], "client_id": CLAUDE_CLIENT_ID,
                       "scope": " ".join(o.get("scopes") or [])}).encode()
    req = urllib.request.Request(CLAUDE_TOKEN_URL, data=body, headers={
        "Content-Type": "application/json", "Accept": "application/json", "User-Agent": "claude-buddy"})  # ohne eigene Kennung blockt Cloudflare (1010)
    r = json.load(urllib.request.urlopen(req, timeout=20))
    o["accessToken"] = r["access_token"]
    if r.get("refresh_token"):
        o["refreshToken"] = r["refresh_token"]
    o["expiresAt"] = int((time.time() + int(r.get("expires_in", 3600))) * 1000)
    d["claudeAiOauth"] = o
    tmp = CLAUDE_CREDS + ".buddy.tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(d, f)
    os.replace(tmp, CLAUDE_CREDS)
    zlog("Claude-Anmeldung erneuert")
    return o


def claude_usage():
    """{'5h': (prozent, reset-epoch), 'woche': (prozent, reset-epoch)} oder ein Text, warum es nicht geht."""
    import urllib.error
    import urllib.request
    from datetime import datetime
    d, o = _claude_oauth()
    if not o.get("accessToken"):
        return "Claude Code ist nicht angemeldet (einmal im Terminal: claude, dann /login)"

    def frisch(x):
        return x.get("expiresAt", 0) / 1000 - time.time() > 600
    try:
        if not frisch(o) and o.get("refreshToken"):
            # Erneuern gibt einen neuen Erneuerungsschluessel aus, der alte wird ungueltig. Damit sich Buddy und
            # Claude Code nicht gegenseitig aussperren: unter Sperre unmittelbar davor neu lesen - hat Claude Code
            # schon erneuert, dessen Schluessel nehmen statt selbst zu erneuern.
            with _claude_lock():
                d, o = _claude_oauth()
                if not frisch(o):
                    try:
                        o = _claude_refresh(d, o)
                    except urllib.error.HTTPError as e:
                        time.sleep(2)
                        d, o = _claude_oauth()  # vielleicht kam Claude Code gerade zuvor
                        if not frisch(o):
                            if e.code in (400, 401):
                                return "Anmeldung abgelaufen – Claude Code einmal neu anmelden (claude, /login)"
                            raise
        req = urllib.request.Request(CLAUDE_USAGE_URL, headers={
            "Authorization": "Bearer " + o["accessToken"], "anthropic-beta": "oauth-2025-04-20",
            "User-Agent": "claude-buddy", "Content-Type": "application/json"})
        r = json.load(urllib.request.urlopen(req, timeout=15))
    except urllib.error.HTTPError as e:
        return "Anthropic antwortet %d" % e.code  # ohne Schluessel im Text
    except Exception as e:  # noqa: BLE001
        return "Verbrauch nicht abrufbar (%s)" % type(e).__name__

    def eintrag(x):
        if not isinstance(x, dict) or x.get("utilization") is None:
            return None
        t = 0
        try:
            t = datetime.fromisoformat(str(x.get("resets_at")).replace("Z", "+00:00")).timestamp()
        except Exception:
            pass
        return (int(round(float(x["utilization"]))), t)
    return {"5h": eintrag(r.get("five_hour")), "woche": eintrag(r.get("seven_day"))}


def reset_text(t, tag=False):
    """Ruecksetzzeit fuer den Watcher: "21:50" bzw. "Fr 09:00"."""
    if not t:
        return ""
    lt = time.localtime(round(t / 60.0) * 60)  # Anthropic schickt z. B. 08:59:59.6 -> 09:00
    tage = ["Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"] if lang() == "en" else ["Mo", "Di", "Mi", "Do", "Fr", "Sa", "So"]
    return ("%s %02d:%02d" % (tage[lt.tm_wday], lt.tm_hour, lt.tm_min)) if tag else ("%02d:%02d" % (lt.tm_hour, lt.tm_min))


_usage_zeile = None  # zuletzt gesendete Boegen (fuer erneutes Senden nach einem Watcher-Neustart)


def claude_usage_senden():
    """Verbrauch holen und als Boegen an den Watcher. Liefert das Ergebnis von claude_usage()."""
    global _usage_zeile
    u = claude_usage()
    if isinstance(u, dict) and (u.get("5h") or u.get("woche")):
        f, w = u.get("5h") or (-1, 0), u.get("woche") or (-1, 0)
        _usage_zeile = "KX -1|%d|%d|%s|%s" % (f[0], w[0], reset_text(f[1]), reset_text(w[1], True))
        send_line(_usage_zeile)
    return u


def claude_usage_wiederholen():
    """Die letzten Boegen nochmal schicken (ohne Anthropic zu fragen) - ein neu gestarteter Watcher hat sonst keine."""
    if _usage_zeile:
        send_line(_usage_zeile)


def radio_name(n):
    """Anzeigename: "radio 3 | rbb | HQ" -> "radio 3", "radioeins-rbb-56 kbit/s" -> "radioeins"."""
    import re
    n = re.split(r"\s*[|(\[]", (n or "").strip())[0].strip()
    return re.sub(r"[-\s]*(rbb[-\s]*)?\d+\s*kbit/?s\b", "", n, flags=re.I).strip(" -")


def _rb(q):
    """Anfrage an radio-browser.info (ohne Konto)."""
    import urllib.parse
    import urllib.request
    req = urllib.request.Request(RADIO_API + "?" + urllib.parse.urlencode(q), headers={"User-Agent": "ClaudeBuddy/1"})
    return json.load(urllib.request.urlopen(req, timeout=15))


def radio_top(n=10):
    """Die beliebtesten Sender fuer den eigenen Ort (config "ort"): erst bis zu 3 aus 60 km Umkreis, dann das
    Bundesland bzw. die Region, zuletzt das Land - jeweils nach Stimmen bei radio-browser.info, nur MP3.
    Liefert [(name, url, favicon)]."""
    import re
    import urllib.parse
    import urllib.request
    cfg = load_cfg()
    ort = (cfg.get("ort") or "").split(",")[0].strip()
    lat, lon, land, region = cfg.get("lat"), cfg.get("lon"), None, None
    if ort:
        try:
            u = "https://geocoding-api.open-meteo.com/v1/search?" + urllib.parse.urlencode({"name": ort, "count": 1, "language": "de"})
            g = json.load(urllib.request.urlopen(u, timeout=10))["results"][0]
            lat, lon, land, region = lat or g["latitude"], lon or g["longitude"], g.get("country_code"), g.get("admin1")
        except Exception as e:  # noqa: BLE001
            zlog("Radio-Ort: %r" % e)
    basis = {"codec": "MP3", "hidebroken": "true", "order": "votes", "reverse": "true", "limit": max(40, n * 4)}
    kandidaten = []
    if lat and lon:
        try:
            kandidaten += [x for x in _rb(dict(basis, geo_lat=lat, geo_long=lon, geo_distance=60000)) if x.get("votes", 0) >= 10][:3]
        except Exception as e:  # noqa: BLE001
            zlog("Radio-Umkreis: %r" % e)
    if land and region:
        kandidaten += _rb(dict(basis, countrycode=land, state=region))
    if land:
        landweit = _rb(dict(basis, countrycode=land))
        kandidaten += [x for x in landweit if not (x.get("state") or "").strip()]  # erst landesweite
        kandidaten += [x for x in landweit if (x.get("state") or "").strip()]      # dann beliebte aus anderen Regionen
    out, gesehen = [], set()
    for x in kandidaten:
        name = re.split(r"\s*[|(\[]", (x.get("name") or "").strip())[0].strip()
        name = re.sub(r"[-\s]*(rbb[-\s]*)?\d+\s*kbit/?s\b", "", name, flags=re.I).strip(" -")  # "radioeins-rbb-56 kbit/s"
        url = x.get("url_resolved") or ""
        if not name or not url.startswith("http") or len(url) >= 300:
            continue
        if re.search(r"[#|]|^\d+R\b", name) or not re.match(r"^[\w\u00c0-\u017f]", name):
            continue  # Nischen-Streams mit Sonderzeichen-Namen
        if not ukw_like(x, name):
            continue  # nur Sender, die man auch im Radio (UKW/DAB+) empfaengt
        key = re.sub(r"[^a-z0-9]", "", name.lower())[:10]
        strom = re.sub(r"^https?://(www\.)?|[?#].*$", "", url.lower()).rstrip("/")  # derselbe Stream unter anderem Namen
        if key in gesehen or strom in gesehen:
            continue
        if any(len(k) >= 6 and k in strom.replace(".", "").replace("-", "") for k in gesehen if "/" not in k):
            continue  # gleiches Programm unter neuem Namen ("radio 3" laeuft unter rbbkultur.de)
        gesehen.add(key)
        gesehen.add(strom)
        out.append((name, url, x.get("favicon") or ""))
        if len(out) >= n:
            break
    if len(out) < n and (land or "").upper() not in ("DE", "AT", "CH", "GB"):
        # ausserhalb von DACH/UK kennt der strenge Filter wenige Sender: auffuellen, aber ohne Webradios
        for x in kandidaten:
            name = re.split(r"\s*[|(\[]", (x.get("name") or "").strip())[0].strip()
            url = x.get("url_resolved") or ""
            if not name or not url.startswith("http") or len(url) >= 300 or RADIO_WEB.search(name):
                continue
            if "webradio" in (x.get("tags") or "").lower() or x.get("votes", 0) < 20:
                continue
            key = re.sub(r"[^a-z0-9]", "", name.lower())[:10]
            strom = re.sub(r"^https?://(www\.)?|[?#].*$", "", url.lower()).rstrip("/")
            if key in gesehen or strom in gesehen:
                continue
            gesehen.update((key, strom))
            out.append((name, url, x.get("favicon") or ""))
            if len(out) >= n:
                break
    return out


def ort_automatisch():
    """Ort ueber die Internetverbindung (oeffentliche IP des WLANs) bestimmen und speichern, wenn noch keiner gesetzt ist.
    Liefert (ort, lat, lon) oder None."""
    import urllib.request
    cfg = load_cfg()
    if cfg.get("ort") and cfg.get("lat"):
        return cfg["ort"], cfg["lat"], cfg["lon"]
    for url in ("https://ipwho.is/?fields=success,city,latitude,longitude",
                "https://ipapi.co/json/"):
        try:
            req = urllib.request.Request(url, headers={"User-Agent": "claude-buddy"})
            d = json.load(urllib.request.urlopen(req, timeout=8))
            city, lat, lon = d.get("city"), d.get("latitude"), d.get("longitude")
            if city and lat is not None and lon is not None:
                cfg = load_cfg()
                cfg["ort"], cfg["lat"], cfg["lon"] = city, round(float(lat), 3), round(float(lon), 3)
                cfg["ort_auto"] = True
                save_cfg(cfg)
                zlog("Ort automatisch: %s" % city)
                return city, cfg["lat"], cfg["lon"]
        except Exception as e:  # noqa: BLE001
            zlog("Ort automatisch (%s): %r" % (url.split("/")[2], e))
    return None


def radio_liste_senden(sender, progress=None):
    """[(name, url, logo)] als Senderwalze auf den Watcher (Liste + Logos). Liefert die Zahl, die der Watcher meldet."""
    radio_cmd("RF -")
    for i, (n, u, logo) in enumerate(sender):
        radio_cmd("RF %d|%s|%s" % (i, ascii_only(n, 22), u))
        sd_put("radio/%d.raw" % i, logo if logo and len(logo) == LOGO * LOGO * 2 else b"")
        if progress:
            progress(i + 1, len(sender))
    return len(sender)


def radio_logos_nachladen(ip):
    """Fehlende Senderlogos auf der SD-Karte neu holen (z.B. nach einer neuen Karte). Liefert die Zahl."""
    import re
    import urllib.parse
    import urllib.request
    try:
        r = urllib.request.urlopen("http://%s/cmd?%s" % (ip, urllib.parse.urlencode({"l": "RF?"})), timeout=5).read().decode()
    except Exception:
        return 0
    vorhanden = set()
    try:  # nur fehlende Logos holen (eigene bleiben)
        d = json.loads(urllib.request.urlopen("http://%s/sdlist?%s" % (ip, urllib.parse.urlencode({"d": "radio"})), timeout=8).read())
        vorhanden = {f[0] for f in d.get("files", []) if f[1] == LOGO * LOGO * 2}
    except Exception:
        pass
    n = 0
    for i, name in re.findall(r"\| (\d+) (.+?) \(\d+\)", r):
        if "%s.raw" % i in vorhanden:
            continue
        logo = radio_logo_suchen(name.strip())
        if logo and sd_put("radio/%s.raw" % i, logo, host=ip):
            n += 1
    return n


def radio_anzahl():
    """Wie viele Sender hat der Watcher auf der Walze? None, wenn er nicht antwortet."""
    import urllib.parse
    import urllib.request
    h = watcher_host()
    if not h:
        return None
    try:
        r = urllib.request.urlopen("http://%s/cmd?%s" % (h, urllib.parse.urlencode({"l": "RF?"})), timeout=5).read().decode()
        return int(r.split("anzahl=")[1].split()[0])
    except Exception:
        return None


def radio_top_senden(n=20, nur_wenn_leer=True, progress=None):
    """Die n beliebtesten Sender fuer den Ort holen (mit Logos) und auf den Watcher legen.
    nur_wenn_leer: nichts tun, wenn dort schon Sender stehen (eigene Liste nicht ueberschreiben)."""
    if nur_wenn_leer:
        k = radio_anzahl()
        if k is None or k > 0:
            return k
    ort_automatisch()
    liste = [(nm, u, radio_logo_suchen(nm, fav)) for nm, u, fav in radio_top(n)]
    if not liste:
        return 0
    return radio_liste_senden(liste, progress)


import re  # noqa: E402
RADIO_WEB = re.compile(r"\b(hits?|mix|charts?|deep|house|lounge|chill|classic rock|rock fm|non-?stop|webradio|internetradio|"
                       r"party|club|dance|techno|edm|80er|90er|2000er|oldies only|schlager-?radio|kids|xmas|weihnacht|"
                       r"love|retro|best of|indie|classics?|perlen|metal|hip ?hop|rap|instrumental|lofi|ambient|bobs|alternative|soft rock|bollerwagen|"
                       r"\d0s\d0s|\d0er)\b|\s-\s", re.I)


# Stream- bzw. Webseiten-Netze von Rundfunkanbietern, die ihre Programme auch ueber UKW/DAB+ senden
RADIO_NETZE = ("radiogroup.de", "rndfnk.com", "regiocast", "streamabc.net", "ffn.de", "radiohamburg", "radiobob", "bbradio.de",
               "berliner-rundfunk", "104.6rtl", "radioberlin", "rs2.de", "jam.fm", "energy.de", "radiopsr", "antenne.de",
               "antenne1", "radio-ffh", "bigfm", "sunshine-live", "rpr1", "hitradio", "radio21", "radioteddy", "dlf.de",
               "deutschlandradio", "wdr.de", "ndr.de", "mdr.de", "br.de", "hr.de", "swr.de", "sr.de", "rbb", "bbc.co.uk",
               "orf.at", "srf.ch", "rtl.de", "stream.laut.fm")


def ukw_like(x, name):
    """Kommt der Sender offiziell auch ueber Antenne (UKW/DAB+) und ist kein reines Webradio?
    radio-browser kennt dafuer kein Merkmal. Oeffentlich-rechtlich markierte Sender zaehlen immer; private nur mit
    einem Hinweis auf Rundfunk: Frequenz im Namen, UKW/DAB in den Stichwoertern oder ein bekanntes Rundfunk-Netz."""
    tags = (x.get("tags") or "").lower()
    if re.search(r"public radio|\b(ard|wdr|ndr|mdr|br|hr|swr|rbb|sr|dlf|bbc|orf|srf|npr|cbc|abc|rai|rtve|radio france|"
                 r"france inter|nos|npo|vrt|rtbf|yle|nrk|dr|sveriges radio|rte|rnz|sabc|nhk)\b", tags):
        return not RADIO_WEB.search(name)
    if RADIO_WEB.search(name) or "webradio" in tags:
        return False
    if re.search(r"\b\d{2,3}[.,]\d\b", name) or re.search(r"\b(ukw|dab|fm \d)", tags):
        return True
    adressen = ((x.get("url_resolved") or "") + " " + (x.get("homepage") or "")).lower()
    return any(n in adressen and n != "stream.laut.fm" for n in RADIO_NETZE)


LOGO = 96  # Logo-Kachel fuer den Watcher: 96 x 96, RGB565 Big Endian (wie im Display-Speicher)


def radio_logo(url):
    """Senderlogo laden und als runde Kachel auf Weiss umrechnen. Liefert die Rohdaten oder None."""
    import io
    import urllib.request
    from PIL import Image
    if not url:
        return None
    try:
        data = urllib.request.urlopen(urllib.request.Request(url, headers={"User-Agent": "ClaudeBuddy/1"}), timeout=10).read()
        im = Image.open(io.BytesIO(data))
        im.load()
    except Exception:
        return None
    im = im.convert("RGBA")
    if im.width < 32 or im.height < 32:
        return None  # zu klein, wird nur matschig
    ecken = [im.getpixel((x, y)) for x in (1, im.width - 2) for y in (1, im.height - 2)]
    deckend = all(c[3] > 240 for c in ecken) and not all(min(c[:3]) > 235 for c in ecken)
    tile = Image.new("RGBA", (LOGO, LOGO), (255, 255, 255, 255))
    if deckend:  # farbiger Grund: Kreis ganz fuellen (Ecken werden spaeter rund abgeschnitten)
        k = LOGO / min(im.width, im.height)
        im = im.resize((max(LOGO, round(im.width * k)), max(LOGO, round(im.height * k))), Image.LANCZOS)
        tile.alpha_composite(im, (-(im.width - LOGO) // 2, -(im.height - LOGO) // 2))
    else:  # freigestellt oder weisser Grund: mit Rand in den weissen Kreis
        box = int(LOGO * 0.74)
        im.thumbnail((box, box), Image.LANCZOS)
        tile.alpha_composite(im, ((LOGO - im.width) // 2, (LOGO - im.height) // 2))
    out = bytearray()
    for r, g, b, _a in list(tile.getdata()):
        v = ((r & 0xF8) << 8) | ((g & 0xFC) << 3) | (b >> 3)
        out += bytes([v >> 8, v & 0xFF])
    return bytes(out)


def radio_logo_suchen(name, fav=""):
    """Logo fuer einen Sender: erst das hinterlegte Bild, dann die Bilder gleichnamiger Eintraege, zuletzt die
    Webseite des Senders (apple-touch-icon, grosses Favicon). Liefert Rohdaten fuer den Watcher oder None."""
    import re
    import urllib.parse
    import urllib.request
    kandidaten = [fav] if fav else []
    seiten = []
    try:
        for x in _rb({"name": name, "limit": 10, "order": "votes", "reverse": "true"}):
            if radio_name(x["name"]).lower() == name.lower():
                if x.get("favicon"):
                    kandidaten.append(x["favicon"])
                if x.get("homepage"):
                    seiten.append(x["homepage"])
    except Exception:
        pass
    gross, klein, og_bilder = [], [], []
    for seite in list(dict.fromkeys(seiten))[:2]:
        try:
            html = urllib.request.urlopen(urllib.request.Request(seite, headers={"User-Agent": "Mozilla/5.0 ClaudeBuddy"}),
                                          timeout=10).read(300000).decode("utf-8", "replace")
        except Exception:
            continue
        for tag in re.findall(r"<link[^>]+>", html, re.I):
            rel = re.search(r'rel=["\']([^"\']+)', tag, re.I)
            href = re.search(r'href=["\']([^"\']+)', tag, re.I)
            if not (rel and href) or "icon" not in rel.group(1).lower() or href.group(1).lower().endswith(".svg"):
                continue
            size = re.search(r'sizes=["\'](\d+)', tag)
            px = int(size.group(1)) if size else (180 if "apple" in rel.group(1).lower() else 32)
            (gross if px >= 64 else klein).append((px, urllib.parse.urljoin(seite, href.group(1))))
        og = re.search(r'<meta[^>]+property=["\']og:image["\'][^>]+content=["\']([^"\']+)', html, re.I)
        if og:
            og_bilder.append(urllib.parse.urljoin(seite, og.group(1)))
        klein.append((16, urllib.parse.urljoin(seite, "/favicon.ico")))
    reihe = [u for _p, u in sorted(gross, reverse=True)] + kandidaten + [u for _p, u in sorted(klein, reverse=True)] + og_bilder
    for u in dict.fromkeys(reihe):
        d = radio_logo(u)
        if d:
            return d
    return None


def radio_cmd(line):
    """Befehl an den Watcher (per WLAN mit Schluessel, sonst ueber die normalen Wege)."""
    import urllib.parse
    import urllib.request
    host = watcher_host()
    if host:
        try:
            urllib.request.urlopen("http://%s/cmd?%s" % (host, urllib.parse.urlencode({"l": line})), timeout=5).read()
            return True
        except Exception:
            pass
    return send_line(line)


def radio(name):
    """Sender suchen und am Watcher abspielen; 'aus' stoppt. Liefert einen Text fuer die Anzeige."""
    if not name or name.strip().lower() in ("aus", "stop", "stopp", "off", "ende"):
        radio_cmd("RA")
        return L("Radio aus", "Radio off")
    name = fix_place(name.strip())
    tries = [name, name.replace(" ", "")]  # "radio eins", "radioeins"
    if name.lower().startswith("radio "):
        tries.append(name[6:])  # "Radio Fritz" heisst nur "Fritz"
    hit = None
    for n in tries:
        hit = radio_find(n)
        if hit:
            break
    if not hit:
        return L("Sender nicht gefunden: %s", "Station not found: %s") % name
    sname, url = hit
    zlog("Radio: %s -> %s" % (sname, url))
    radio_cmd("RA %s|%s" % (url, ascii_only(sname, 30)))
    return "Radio: %s" % sname


def fix_place(name):
    """Aehnlich klingende Woerter zum eigenen Ort korrigieren (die Erkennung hoert "Cordbus" statt "Cottbus")."""
    import difflib
    ort = (load_cfg().get("ort") or "").split(",")[0].strip()
    if not ort:
        return name
    out = []
    for w in name.split():
        r = difflib.SequenceMatcher(None, w.lower(), ort.lower()).ratio()
        out.append(ort.lower() if r >= 0.7 and w.lower() != ort.lower() else w)
    return " ".join(out)


def whisper_hint():
    """Hinweiswoerter fuer die Spracherkennung: feste Begriffe, Radio und der eigene Ort."""
    ort = (load_cfg().get("ort") or "").split(",")[0].strip()
    if lang() == "en":
        return WHISPER_HINT + " Play radio, station, radio off." + (" %s." % ort if ort else "")
    return WHISPER_HINT + " Spiel Radio, Sender, Radio aus." + (" %s." % ort if ort else "")


def claude_starten():
    """Claude (Desktop-App) oeffnen bzw. nach vorne holen. Liefert True, wenn ein Start ausgeloest wurde."""
    import subprocess
    if os.name != "nt":
        return False
    nowin = getattr(subprocess, "CREATE_NO_WINDOW", 0)
    try:  # App aus dem Store/Installer: ueber ihre Start-ID (z.B. "Claude_xxxx!Claude")
        r = subprocess.run(["powershell", "-NoProfile", "-NonInteractive", "-Command",
                            "(Get-StartApps | Where-Object { $_.Name -eq 'Claude' } | Select-Object -First 1).AppID"],
                           capture_output=True, text=True, timeout=15, creationflags=nowin)
        app_id = (r.stdout or "").strip()
        if app_id:
            subprocess.Popen(["explorer.exe", "shell:AppsFolder\\" + app_id])
            return True
    except Exception:
        pass
    for pfad in (os.path.join(os.environ.get("LOCALAPPDATA", ""), "AnthropicClaude", "claude.exe"),
                 os.path.join(os.environ.get("LOCALAPPDATA", ""), "Programs", "Claude", "Claude.exe")):
        if os.path.exists(pfad):
            subprocess.Popen([pfad])
            return True
    return False


def start_befehl(text):
    """ "Computer, starte Claude" / "öffne Claude" / "start Claude" / "open Claude"."""
    import re
    t = re.sub(r"[.!?,\-]", " ", (text or "").lower()).strip()
    t = re.sub(r"^(computer\s+)?(bitte\s+|please\s+)?", "", re.sub(r"\s+", " ", t)).strip()
    if re.fullmatch(r"(starte?|öffne|oeffne|mach|start|open|launch|run)\s+(mal\s+)?(claude|cloud|klaud|clod)( an| auf| up)?( bitte| please)?|"
                    r"(claude|cloud|klaud)\s+(starten|öffnen|oeffnen|start|open)( bitte| please)?", t):
        if claude_starten():
            return L("Claude startet", "Starting Claude")
        return L("Claude nicht gefunden", "Claude not found")
    return None


BEFEHLSWOERTER = {"aus", "an", "ein", "stopp", "stop", "radio", "musik", "sender", "lauter", "leiser", "spiel", "spiele",
                  "starte", "start", "öffne", "oeffne", "off", "on", "play", "louder", "quieter", "volume", "pause", "weiter",
                  "next", "nächster", "naechster", "computer", "claude", "cloud", "ruhe", "still", "quiet", "halt"}


def _woerter(text):
    import re
    return re.sub(r"[^a-zäöüß ]", " ", (text or "").lower()).split()


def befehl_abgrenzen(text):
    """Kurzer Satz (bis 4 Woerter) mit einem Befehlswort, den kein Befehl verstanden hat: nicht ins Fenster tippen,
    sondern am Watcher "Nicht verstanden" zeigen. Laengere Saetze sind Text fuer Claude."""
    w = _woerter(text)
    if w and len(w) <= 4 and any(x in BEFEHLSWOERTER for x in w):
        return L("Nicht verstanden: %s", "Didn't catch that: %s") % " ".join(w)[:40]
    return None


def lautstaerke_befehl(text, host=None):
    """ "Computer, lauter" / "leiser" / "louder" / "quieter" (ggf. "Radio lauter")."""
    w = [x for x in _woerter(text) if x not in ("computer", "bitte", "please", "radio", "musik", "etwas", "noch", "bit", "a", "mal")]
    if not w or len(w) > 2:
        return None
    d = 1 if w[0] in ("lauter", "louder") else (-1 if w[0] in ("leiser", "quieter", "softer") else 0)
    if not d:
        return None
    hosts = [host] if host else mic_hosts()
    neu = None
    for h in hosts:
        o = get_options(h) or {}
        v = max(1, min(5, int(o.get("vol", 3)) + d))
        if set_options(h, vol=v):
            neu = v
    return (L("Lautstärke %d", "Volume %d") % neu) if neu else None


STOPP_SAETZE = {
    # deutsch
    "stopp", "stop", "halt", "ruhe", "still", "aufhören", "aufhoeren", "hör auf", "hoer auf", "sei still", "sei ruhig",
    "sei leise", "halt die klappe", "klappe", "halt den mund", "halts maul", "schnauze", "schweig", "es reicht", "das reicht",
    "reicht", "genug", "schluss", "ende", "beenden", "abbrechen", "abbruch", "pause", "lass das", "lass es", "nicht mehr",
    "nicht vorlesen", "aus", "ausmachen", "ausschalten", "mach aus", "mach das aus", "alles aus", "stille", "ruhe bitte",
    # englisch
    "cancel", "quiet", "be quiet", "silence", "enough", "thats enough", "shut up", "hush", "never mind", "nevermind",
    "stop it", "stop reading", "stop talking", "pause", "end", "turn off", "off", "that will do",
}
STOPP_FUELLER = {"computer", "bitte", "jetzt", "mal", "doch", "endlich", "sofort", "please", "now", "just", "ok", "okay",
                 "hey", "na", "ja", "so", "nun", "bloß", "bloss", "einfach", "kurz", "du", "you"}


def stopp_befehl(text):
    """ "Computer, stopp" / "hör auf" / "halt die Klappe" / "be quiet" ...: Vorlesen (schon beim Weckwort beendet) und
    Radio aus, nichts eintippen. Liefert die Rueckmeldung fuers Display oder None."""
    w = [x for x in re.sub(r"[^a-zäöüß' ]", " ", (text or "").lower().replace("'", "")).split() if x not in STOPP_FUELLER]
    if w and " ".join(w) in STOPP_SAETZE:
        radio_cmd("RA")
        return L("Okay, ich bin still", "Okay, I'll be quiet")
    return None

def radio_voice(text):
    """Sprachbefehl erkennen: 'spiel Radio Eins', 'Radio Fritz', 'mach das Radio aus', 'Musik aus'.
    Liefert die Antwort (str), wenn es ein Radio-Befehl war, sonst None (dann geht der Text wie immer ins Fenster)."""
    import re
    if lang() == "en":
        return radio_voice_en(text)
    kurz = re.sub(r"^computer\s*", "", re.sub(r"[^a-zäöü ]", "", (text or "").lower()).strip()).strip()
    if kurz in ("aus", "ausmachen", "ausschalten", "off", "radio aus", "musik aus"):  # oft kommt von "Radio aus" nur "Aus" an
        return radio("aus")
    t = re.sub(r"[.!?,\-]", " ", (text or "").lower()).strip()
    t = re.sub(r"\b(spiele?|starte?|mach)(radio|musik)", r"\1 \2", t)  # "spielradio" -> "spiel radio"
    t = re.sub(r"\s+", " ", t)
    t = re.sub(r"^(computer\s+)?(bitte\s+)?", "", t)
    if re.match(r"^((mach|schalt)\w*\s+)?(das\s+|die\s+)?(radio|musik)\s+(aus|stopp?|ab|leise)\s*(bitte)?$", t) or \
            re.match(r"^(stopp?|aus)\s+(das\s+)?(radio|musik)$", t):
        return radio("aus")
    m = re.match(r"^(?:(?:spiel|spiele|mach|starte|schalte?)\w*\s+)?(?:mal\s+)?(?:das\s+)?(?:den\s+sender\s+|radio\s*)(.+?)(?:\s+an)?(?:\s+bitte)?$", t)
    if m and (t.startswith(("spiel", "mach", "start", "schalt", "radio")) or "sender" in t):
        name = m.group(1).strip()
        if "sender" not in t:  # "Radio Eins": das Wort Radio gehoert oft zum Namen
            name = "radio " + name
        return radio(name)
    m = re.match(r"^spiele?\s+(?:mal\s+)?(.{3,40}?)(?:\s+bitte)?$", t)  # "Spiel Antenne Brandenburg": nur wenn es den Sender gibt
    if not m:  # zusammengeschrieben: "Spielantenne Brandenburg"
        m = re.match(r"^spiele?([a-zäöü]{4,}(?:\s+\S+){0,3}?)(?:\s+bitte)?$", t)
    if m and len(m.group(1).split()) <= 4:
        name = fix_place(m.group(1))
        if radio_find(name):
            return radio(name)
    return None


def radio_voice_en(text):
    """English voice commands: 'play Radio Eins', 'play BBC Radio 2', 'radio off', 'stop the radio', 'turn off the music'."""
    import re
    t = re.sub(r"[.!?,\-]", " ", (text or "").lower()).strip()
    t = re.sub(r"\s+", " ", t)
    t = re.sub(r"^(computer\s+)?(please\s+)?", "", t)
    t = re.sub(r"\s+please$", "", t)
    if t in ("off", "radio off", "music off", "stop", "turn off"):
        return radio("aus")
    if re.match(r"^(turn|switch|shut)\s+(off\s+)?(the\s+)?(radio|music)(\s+off)?$", t) or \
            re.match(r"^(stop|pause|mute)\s+(the\s+)?(radio|music)$", t) or re.match(r"^(radio|music)\s+(off|stop)$", t):
        return radio("aus")
    m = re.match(r"^(?:play|start|put on|turn on|tune (?:in )?to)\s+(?:the\s+)?(?:station\s+|radio station\s+)?(.{2,40}?)$", t)
    if m:
        name = m.group(1).strip()
        if name in ("radio", "the radio", "music", "some music"):
            return None
        if radio_find(name) or name.startswith("radio") or "station" in t:
            return radio(name)
    return None


def say_chunks(text, n=380):
    """Text in Stuecke aus ganzen Saetzen (je etwa 25 s Sprache)."""
    import re
    out, cur = [], ""
    for s in re.split(r"(?<=[.!?:])\s+", text):
        while len(s) > n:  # ein einzelner Riesensatz: am Komma bzw. Wort teilen
            cut = s[:n]
            k = max(cut.rfind(", "), cut.rfind("; "))
            k = k + 1 if k > n // 2 else (cut.rfind(" ") if " " in cut else n)
            if cur:
                out.append(cur)
                cur = ""
            out.append(s[:k].strip())
            s = s[k:].strip()
        if cur and len(cur) + len(s) + 1 > n:
            out.append(cur)
            cur = ""
        cur += (" " if cur else "") + s
    if cur:
        out.append(cur)
    return [c for c in out if c.strip()]


def _post_say(h, wav, neu):
    """Ein Stueck an einen Buddy. Liefert 'ok', 'voll' oder ''."""
    import urllib.request
    bnd = "----buddysay%d" % int(time.time() * 1000)
    body = (("--%s\r\nContent-Disposition: form-data; name=\"f\"; filename=\"sag.wav\"\r\n"
             "Content-Type: audio/wav\r\n\r\n") % bnd).encode() + wav + ("\r\n--%s--\r\n" % bnd).encode()
    req = urllib.request.Request("http://%s/say%s" % (h, "?neu=1" if neu else ""), data=body,
                                 headers={"Content-Type": "multipart/form-data; boundary=" + bnd})
    try:
        r = urllib.request.urlopen(req, timeout=30).read()
        return "ok" if r.startswith(b"ok") else ""
    except urllib.error.HTTPError as e:
        return "voll" if e.code == 503 else ""
    except Exception:
        return ""


def say(text):
    """Laesst alle Watcher die ganze Antwort sprechen (wenn "Vorlesen" an ist). Das erste Stueck geht sofort raus,
    der Rest im Hintergrund: Claude Code wartet nie darauf. Eine neue Antwort bricht die alte ab."""
    import threading
    import urllib.error  # noqa: F401  (fuer _post_say)
    text = (text or "").strip()
    if not text or not load_cfg().get("vorlesen", True):
        return False
    hosts = mic_hosts()  # wer ein Mikrofon hat, hat auch einen Lautsprecher
    if not hosts:
        return False
    chunks = say_chunks(text)
    if not chunks:
        return False
    _SAY_GEN[0] += 1
    gen = _SAY_GEN[0]
    cache = {}

    def wav_for(i, art):
        if (i, art) not in cache:
            cache[(i, art)] = tts_wav(chunks[i], art)
        return cache[(i, art)]

    def dur(w):
        return max(0.0, (len(w) - 44) / 32000.0)

    def run_host(h, first_done):
        art = voice_for(h)
        ends = []  # wann jedes geschickte Stueck fertig gesprochen ist
        for i in range(len(chunks)):
            if _SAY_GEN[0] != gen:
                break
            w = wav_for(i, art)
            if i >= 2:  # hoechstens eins wartet am Buddy: auf das Ende des vorletzten warten
                time.sleep(max(0.0, ends[i - 2] - time.time() + 0.3))
                if _SAY_GEN[0] != gen:
                    break
            for _ in range(20):
                r = _post_say(h, w, neu=(i == 0))
                if r != "voll":
                    break
                time.sleep(1.0)
            if r != "ok":
                break
            start = max(time.time(), ends[-1] if ends else 0)
            ends.append(start + dur(w))
            if i == 0:
                first_done.append(h)
                ev.set()
        ev.set()

    ev = threading.Event()
    ok = []
    th = [threading.Thread(target=run_host, args=(h, ok), daemon=False) for h in hosts]
    for t in th:
        t.start()
    ev.wait(40)  # nur auf das erste Stueck warten
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


def speakable(text, n=None):
    """Antwort fuer die Sprachausgabe aufbereiten: ohne Code, Links und Markdown. Vorgelesen wird alles;
    config "vorlesen_zeichen" (> 0) begrenzt auf ganze Saetze bis etwa so viele Zeichen."""
    import re
    t = re.sub(r"```.*?```", " ", text, flags=re.S)
    t = re.sub(r"`([^`]*)`", r"\1", t)
    t = re.sub(r"\[([^\]]*)\]\([^)]*\)", r"\1", t)
    t = re.sub(r"https?://\S+", "", t)
    t = re.sub(r"[*_#>|]+", " ", t)
    t = re.sub(r"\s+", " ", t).strip()
    if n is None:
        n = int(load_cfg().get("vorlesen_zeichen", 0)) or 10 ** 9
    out = ""
    for s in re.split(r"(?<=[.!?:])\s+", t):
        if len(out) + len(s) + 1 > n:
            if not out:  # schon der erste Satz ist zu lang: am letzten Komma bzw. Wort davor enden
                cut = s[:n]
                k = max(cut.rfind(", "), cut.rfind("; "))
                out = (cut[:k] if k > n // 2 else cut[:cut.rfind(" ")] if " " in cut else cut).rstrip(",;: ") + "."
            break
        out += (" " if out else "") + s
    return out


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
def user_dir():
    """Windows: %LOCALAPPDATA%, Linux: $XDG_DATA_HOME bzw. ~/.local/share."""
    return (os.environ.get("LOCALAPPDATA") or os.environ.get("XDG_DATA_HOME")
            or os.path.join(os.path.expanduser("~"), ".local", "share"))


FOTO_DIR = os.path.join(user_dir(), "claude-buddy", "fotos")
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
        try:  # klappt es nicht, den naechsten Buddy fragen
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
    """WLAN-Adressen aller Watcher (mit Mikrofon): die beantworten /rec."""
    import urllib.request
    cfg = load_cfg()
    out = []
    for ip in list((cfg.get("devices") or {}).keys()) or ([cfg["host"]] if cfg.get("host") else []):
        r = ask_wlan(ip)
        if not r:
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
    drehen = display_drehung(host)  # der Watcher speichert ungedreht: hier so drehen wie sein Display
    frames = []
    for i, f in enumerate(files):
        p = os.path.join(out_dir, f)
        if not os.path.exists(p):
            with open(p, "wb") as fh:
                fh.write(sd_get(host, "zeitraffer/%s/%s" % (serie, f)))
        img = Image.open(p).convert("RGB")
        if drehen:
            img = img.rotate(-drehen, expand=True)
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
LOG_DIR = os.path.join(user_dir(), "claude-buddy")
WHISPER_MODEL = "small"
WHISPER_HINT = "Claude, Claude Code, Buddy, Watcher, SenseCAP, ESP32, PlatformIO, GitHub, Commit, Push, Firmware, Python."


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


def type_text_linux(text, enter=True):
    """Linux: Text direkt tippen lassen (geht auch in Terminals, wo Strg+V nicht einfuegt).
    X11: xdotool, Wayland: wtype oder ydotool. Liefert False, wenn keins davon da ist."""
    import shutil
    import subprocess
    wayland = bool(os.environ.get("WAYLAND_DISPLAY"))
    tools = (["wtype", "ydotool", "xdotool"] if wayland else ["xdotool", "wtype", "ydotool"])
    for t in tools:
        if not shutil.which(t):
            continue
        try:
            if t == "xdotool":
                subprocess.run(["xdotool", "type", "--clearmodifiers", "--delay", "4", "--", text], timeout=60, check=True)
                if enter:
                    time.sleep(0.15)
                    subprocess.run(["xdotool", "key", "--clearmodifiers", "Return"], timeout=5)
            elif t == "wtype":
                subprocess.run(["wtype", "--", text], timeout=60, check=True)
                if enter:
                    time.sleep(0.15)
                    subprocess.run(["wtype", "-k", "Return"], timeout=5)
            else:
                subprocess.run(["ydotool", "type", "--", text], timeout=60, check=True)
                if enter:
                    time.sleep(0.15)
                    subprocess.run(["ydotool", "key", "28:1", "28:0"], timeout=5)
            return True
        except Exception as e:
            zlog("Tippen mit %s ging nicht: %s" % (t, e))
    zlog("Kein Werkzeug zum Tippen gefunden - bitte xdotool (X11) bzw. wtype/ydotool (Wayland) installieren.")
    return False


def type_text(text, enter=True):
    """Text ueber die Zwischenablage ins aktive Fenster einfuegen (Strg+V), optional Enter; alte Zwischenablage zurueck."""
    if os.name != "nt":
        return type_text_linux(text, enter)
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
    segs, _ = model.transcribe(pcm, language=lang(), beam_size=5, vad_filter=True, initial_prompt=whisper_hint())
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


PLAUDEREIEN_EN = [
    [(0, "Psst... are you awake?"), (1, "Now I am!"), (0, "~wave"), (1, "~wave")],
    [(0, "Pretty quiet here."), (1, "Shh, he's thinking!")],
    [(0, "What are you up to?"), (1, "Waiting for work."), (0, "Me too!")],
    [(0, "I learned a lot today."), (1, "Show-off!"), (0, "Hehe.")],
    [(0, "Know a joke?"), (1, "Why do coders mix up"), (1, "Halloween and Xmas?"), (1, "Oct 31 = Dec 25!"), (0, "Hahaha!")],
    [(0, "My plant is growing!"), (1, "Mine too!"), (0, "Watering race?")],
    [(0, "~wave"), (1, "Hi there!"), (0, "Hi back!")],
    [(0, "Will he type again soon?"), (1, "Surely!"), (0, "I'm ready.")],
    [(0, "I'm hungry."), (1, "We eat electricity."), (0, "Yummy power!")],
    [(0, "What time is it?"), (1, "Time for code!")],
    [(0, "Anything new?"), (1, "All green here."), (0, "Great!")],
    [(0, "Nice weather today?"), (1, "I only see pixels."), (0, "Hihi.")],
    [(0, "Do you like coffee?"), (1, "Only bits and bytes."), (0, "Same.")],
    [(0, "Let's dance!"), (1, "Without music?"), (0, "Okay, later.")],
]


def plaudereien():
    return PLAUDEREIEN_EN if lang() == "en" else PLAUDEREIEN


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
                        for who, text in random.choice(plaudereien()):
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
                        # Befehle statt zu tippen; kurze Saetze mit Befehlswoertern werden nie getippt
                        r = (stopp_befehl(text) or start_befehl(text) or lautstaerke_befehl(text, host) or radio_voice(text)
                             or befehl_abgrenzen(text))
                        if r is not None:
                            zlog(r)
                            urllib.request.urlopen("http://%s/cmd?%s" % (host, urllib.parse.urlencode({"l": "R " + ascii_only(r, 66)})), timeout=3).read()
                        else:
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


def display_drehung(host=None):
    """Um wie viel Grad (im Uhrzeigersinn) Kamerabilder gedreht werden muessen: wie das Display plus gemerkte Korrektur."""
    d = load_cfg().get("foto_drehen", 0)
    try:
        host = host or watcher_host()
        o = get_options(host, 3) if host else None
        if o and o.get("rot"):
            d = (d + 90 * int(o["rot"])) % 360
    except Exception:
        pass
    return d


def jpeg_drehen(jpg, grad):
    """JPEG-Bytes im Uhrzeigersinn drehen (0 = unveraendert)."""
    if not grad or not jpg:
        return jpg
    import io
    from PIL import Image
    out = io.BytesIO()
    Image.open(io.BytesIO(jpg)).rotate(-grad, expand=True).save(out, "JPEG", quality=92)
    return out.getvalue()


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
        with open(path, "rb") as f:
            jpg = f.read()
    else:
        with open(path, "wb") as f:
            f.write(jpg)
    try:  # auch ins Fotoarchiv der SD-Karte, schon gedreht (wenn im WLAN)
        sd_put("fotos/%s.jpg" % time.strftime("%Y-%m-%d_%H-%M-%S"), jpg, timeout=3)
    except Exception:
        pass
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
    elif cmd == "radioliste":  # Senderliste fuer die Radio-Seite (Test): radioliste [sender, sender, ...]
        # ohne Angabe: die 10 beliebtesten fuer den eigenen Ort; sonst eigene Liste "fritz, radio eins, ..."
        namen = [n.strip() for n in " ".join(sys.argv[2:]).split(",") if n.strip()]
        liste = []
        if namen:
            for n in namen[:10]:
                hit = None
                for v in [fix_place(n), n.replace(" ", ""), n[6:] if n.lower().startswith("radio ") else ""]:
                    if v and not hit:
                        q = _rb({"name": v, "codec": "MP3", "limit": 10, "hidebroken": "true", "order": "votes", "reverse": "true"})
                        q = [x for x in q if x.get("url_resolved", "").startswith("http") and len(x["url_resolved"]) < 300]
                        if q:  # unter Treffern mit ordentlich Stimmen die beste Tonqualitaet ("radioeins" 56 -> 128 kbit/s)
                            top = max(x.get("votes", 0) for x in q)
                            x = max((x for x in q if x.get("votes", 0) >= min(10, top) and radio_name(x["name"]).lower()
                                     == radio_name(q[0]["name"]).lower()), key=lambda x: (x.get("bitrate") or 0) <= 192 and (x.get("bitrate") or 0))
                            hit = (radio_name(x["name"]), x["url_resolved"], x.get("favicon") or q[0].get("favicon") or "")
                if hit:
                    liste.append(hit)
                else:
                    print("nicht gefunden:", n)
        else:
            liste = radio_top(10)
        radio_cmd("RF -")
        for i, (name, url, fav) in enumerate(liste):
            radio_cmd("RF %d|%s|%s" % (i, ascii_only(name, 22), url))
            logo = radio_logo_suchen(name, fav)
            ok = sd_put("radio/%d.raw" % i, logo) if logo else False
            if not logo:
                sd_put("radio/%d.raw" % i, b"")  # altes Logo an dieser Stelle loeschen
            print(i, name, "(Logo)" if ok else "(ohne Logo)")
    elif cmd == "radio":  # Internetradio am Watcher: radio <sender> | radio aus
        print(radio(" ".join(sys.argv[2:])))
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
            for who, text in random.choice(plaudereien()):
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
