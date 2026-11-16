# Claude-Buddy

Ein kleiner Begleiter auf dem **LILYGO T-Display-S3**, der zeigt, was **Claude Code** gerade macht:
denken, lesen, schreiben, Terminal, suchen, Internet, Helfer, Frage an dich, fertig – mit Animationen,
einer WS2812B-LED hinter einem weißen Diffusor und leisen Tönen aus einem passiven Buzzer.
Im Leerlauf spielt er Jo-Jo, liest, gießt seine Pflanze (sie wächst mit jeder erledigten Aufgabe) oder pustet Seifenblasen.

*Inoffizielles Bastelprojekt, kein Produkt von Anthropic.*

**Simulation, Flasher und Anleitung:** https://prod-byte.github.io/claude-buddy/ · [daveslab.de/basteln](https://daveslab.de/basteln/)

## In drei Schritten

1. **Firmware** über den Browser-Flasher auf der Seite oben aufspielen (Chrome oder Edge, USB-C).
2. **PC:** Python installieren, [`buddy.py`](buddy.py) herunterladen, dann
   ```
   pip install pyserial
   python buddy.py install
   ```
   Das trägt Hooks in `~/.claude/settings.json` ein (eine Sicherung wird angelegt). Entfernen: `python buddy.py uninstall`.
3. **Optional WLAN:** am Gerät beide Tasten 2 s halten → mit dem Handy ins WLAN „Claude-Buddy“ → eigenes WLAN wählen.
   Dann kommt alles auch ohne USB-Datenverbindung an.

## Anschlüsse (optional)

| Bauteil | Anschluss |
|---|---|
| Passiver Buzzer (9 mm) | + an IO16, − an GND |
| WS2812B-LED | DIN über 330 Ω an IO13, 5V, GND |

## Bedienung

- **IO0** kurz: anstupsen · lang: stumm
- **IO14** kurz: Info / „gesehen“ · lang: Einstellungen (Lautstärke, Ticks, LED, Display-Helligkeit, Bild drehen)
- **beide 2 s:** WLAN per Handy einrichten

## English

A little companion on the LILYGO T-Display-S3 that shows what Claude Code is doing. Flash the firmware from the page above,
then run `pip install pyserial` and `python buddy.py install` on your PC. The display speaks German.
