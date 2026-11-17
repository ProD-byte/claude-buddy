// Aktualisiert den "Claude-Buddy" auf daveslab.de/basteln (der mit basteln-buddy.js eingebaut wurde):
// drei Geraete, Windows-Programm als empfohlener Weg, Handbuch, Browser-Flasher fuer alle drei Geraete.
// Ersetzt nur Projektkarte, Abschnitt und die englischen Texte des Buddys; jede Ersetzung muss genau einmal
// passen, sonst wird nichts gespeichert. WordPress hebt die alte Fassung als Revision auf.
//
// SO BENUTZEN (selbst, in Chrome):
//   1. Bei https://daveslab.de/wp-admin/ anmelden
//   2. F12 -> Reiter "Console" -> diese ganze Datei hineinkopieren -> Enter
//      (fragt Chrome nach "allow pasting": einmal  allow pasting  eintippen, Enter, nochmal einfuegen)
//   3. Rueckfrage "Speichern?" -> OK. Danach https://daveslab.de/basteln/ neu laden.
var BUDDY_SEITE = 'https://prod-byte.github.io/claude-buddy';
var BUDDY_SETUP = 'https://github.com/ProD-byte/claude-buddy/releases/latest/download/ClaudeBuddySetup.exe';
var BUDDY_GH = '<a href="https://github.com/ProD-byte/claude-buddy" target="_blank" rel="noopener">GitHub</a>';

var BUDDY_KARTE_NEU = `<a class="dl-karte" href="#buddy" data-p="buddy" aria-expanded="false"><span class="ic">✳️</span><h3>Claude-Buddy</h3><p data-t="k_buddy">Zeigt am Schreibtisch, was Claude Code gerade macht – mit Sprache, Licht und Ton.</p><small>T-Display-S3 · SenseCAP Watcher · AMOLED 1.75C</small><span class="auf-zu" data-t="k_auf">Öffnen</span></a>`;

function flasher(id, manifest, knopf, schluessel) {
  return `<esp-web-install-button id="${id}" manifest="${BUDDY_SEITE}/${manifest}">
            <button slot="activate" data-t="${schluessel}">${knopf}</button>
            <span slot="unsupported" data-t="unsup"><b>Dieser Browser kann das leider nicht.</b> Bitte Chrome oder Edge am Computer verwenden.</span>
            <span slot="not-allowed" data-t="notall"><b>Nur über https möglich.</b></span>
          </esp-web-install-button>`;
}

var BUDDY_ABSCHNITT_NEU = `<section class="dl-sec" id="buddy">
    <div class="dl-wrap">
      <h2 class="dl-h2 rv" data-t="bu_h2">Claude-Buddy <span class="dl-grad">einrichten</span></h2>
      <p class="dl-sub rv"><span data-t="bu_sub">Ein kleiner Begleiter auf dem Schreibtisch, der zeigt, was <b>Claude Code</b> gerade macht: nachdenken, Dateien lesen, Code schreiben, testen, im Internet suchen – und wenn Claude dich braucht, winkt er, leuchtet und klingelt. Es gibt ihn für drei Geräte: <b>LILYGO T-Display-S3</b>, <b>SenseCAP Watcher</b> und <b>Waveshare AMOLED 1.75C</b>. Watcher und AMOLED haben Mikrofon und Lautsprecher: Knopf halten und sprechen, der Text landet bei Claude; Claudes Ergebnis wird vorgelesen, wahlweise mit Frauen- oder Männerstimme; Freigaben gehen per Knopfdruck. Inoffizielles Bastelprojekt, kein Produkt von Anthropic.</span> <span id="dl-ver-buddy"></span></p>
      <div class="rv" style="margin:6px 0 26px">
        <iframe id="dl-buddy-sim" src="${BUDDY_SEITE}/simulation.html?einbetten" title="Simulation des Claude-Buddys" loading="lazy" style="display:block;width:100%;height:1250px;border:0;background:transparent"></iframe>
      </div>
      <div class="dl-auto rv" style="border-color:var(--acc,#d97757)">
        <div>
          <h3 data-t="bu_app_h">💻 Windows-Programm – empfohlen</h3>
          <p data-t="bu_app_p">Ein Installer, der alles erledigt: Buddy per USB anstecken – der Assistent bespielt ihn bei Bedarf, bringt ihn ins WLAN, koppelt ihn sicher (ohne Passwort, per Knopfdruck), lädt die Spracherkennung und verbindet Claude Code. Danach sitzt er als Symbol neben der Uhr: Einstellungen je Buddy, Fotos, Zeitraffer, Töne – und Programm wie Buddys aktualisieren sich von selbst. Warnt Windows beim ersten Start: <b>Weitere Informationen → Trotzdem ausführen</b>.</p>
        </div>
        <a class="dl-btn" href="${BUDDY_SETUP}" data-t="bu_app_btn">Programm laden ↓</a>
      </div>
      <ol class="dl-schritte" style="margin-top:22px">
        <li class="rv" data-t="bu_s1"><b>Programm installieren.</b> <code>ClaudeBuddySetup.exe</code> laden und starten – ohne Administratorrechte.</li>
        <li class="rv" data-t="bu_s2"><b>Buddy anstecken.</b> Per USB-Kabel mit Datenleitungen. Der Assistent erkennt T-Display, Watcher und AMOLED und spielt bei neuen Geräten die Firmware auf.</li>
        <li class="rv" data-t="bu_s3"><b>Durchklicken.</b> WLAN, Kopplung, Ort fürs Wetter, Sprachmodell und Claude Code – alles im Assistenten.</li>
        <li class="rv" data-t="bu_s4"><b>Claude Code neu starten.</b> Ab dann meldet jede Sitzung dem Buddy, was sie gerade tut.</li>
        <li class="rv" data-t="bu_s5"><b>Bedienen.</b> T-Display: IO0 stupst an, IO14 zeigt Infos. Watcher: Drehknopf drücken, halten zum Sprechen, zweimal fürs Menü. AMOLED: PWR wie der Knopf, BOOT blättert weiter.</li>
      </ol>
      <div class="dl-auto rv" style="margin-top:14px">
        <div>
          <h3 data-t="bu_hb_h">📖 Handbuch</h3>
          <p data-t="bu_hb_p">Wie alles funktioniert: Geräte, Bedienung, Sprechen und Vorlesen, Kopplung, sichere Updates, Fehlersuche – mit Bildern.</p>
        </div>
        <a class="dl-btn" href="${BUDDY_SEITE}/Claude-Buddy-Handbuch.pdf" target="_blank" rel="noopener" data-t="bu_hb_btn">Handbuch öffnen (PDF) →</a>
      </div>
      <h3 class="rv" style="margin:26px 0 10px" data-t="bu_fl_h">⚡ Ohne Programm: Firmware im Browser</h3>
      <div class="dl-flash">
        <div class="dl-opt rv">
          <h3 data-t="upd_h">🔄 Update</h3>
          <p data-t="bu_upd_p"><b>T-Display-S3:</b> neue Firmware aufspielen, WLAN und Einstellungen bleiben. Bei „Erase device?“ den Haken <b>nicht</b> setzen. Watcher und AMOLED aktualisieren sich selbst.</p>
          ${flasher('dl-bu-upd', 'manifest-update.json', '⚡ Update installieren', 'upd_btn')}
        </div>
        <div class="dl-opt rot rv">
          <h3 data-t="neu_h">🧹 Neuinstallation</h3>
          <p data-t="bu_neu_p">Für <b>neue Boards</b> oder wenn nichts mehr geht – WLAN und Einstellungen sind danach weg. Gerät wählen:</p>
          ${flasher('dl-bu-neu-t', 'manifest-neu.json', '🗑️ T-Display-S3', 'bu_neu_t')}
          ${flasher('dl-bu-neu-w', 'manifest-neu-watcher.json', '🗑️ SenseCAP Watcher', 'bu_neu_w')}
          ${flasher('dl-bu-neu-a', 'manifest-neu-amoled.json', '🗑️ AMOLED 1.75C', 'bu_neu_a')}
        </div>
      </div>
      <div class="dl-auto rv" style="margin-top:14px">
        <div>
          <h3 data-t="bu_auto_h">✳️ Simulation in groß</h3>
          <p data-t="bu_auto_p">Alle Zustände, Beschäftigungen, Feiern, LED und Ton zum Ausprobieren – mit genau demselben Programmcode wie auf dem Gerät. Linux/Mac: <a href="${BUDDY_SEITE}/buddy.py" download>PC-Skript buddy.py</a>. Quellen und Versionen: ${BUDDY_GH}.</p>
        </div>
        <a class="dl-btn" href="${BUDDY_SEITE}/simulation.html" target="_blank" rel="noopener" data-t="bu_auto_btn">Simulation öffnen →</a>
      </div>
    </div>
  </section>`;

var BUDDY_EN_NEU = [
  `bu_h2:'Set up the <span class="dl-grad">Claude buddy</span>'`,
  `bu_sub:'A little desk companion that shows what <b>Claude Code</b> is doing: thinking, reading files, writing code, testing, searching the web – and when Claude needs you, it waves, lights up and chimes. It runs on three devices: <b>LILYGO T-Display-S3</b>, <b>SenseCAP Watcher</b> and <b>Waveshare AMOLED 1.75C</b>. Watcher and AMOLED have a microphone and speaker: hold the button and talk, the text goes to Claude; Claude\\'s result is read aloud with a female or male voice; approvals by button press. Unofficial hobby project, not a product of Anthropic.'`,
  `bu_app_h:'💻 Windows app – recommended'`,
  `bu_app_p:'One installer does it all: plug in the buddy via USB – the wizard flashes it if needed, brings it onto your Wi-Fi, pairs it securely (no password, by button press), downloads speech recognition and connects Claude Code. Afterwards it sits next to the clock: settings per buddy, photos, time-lapse, sounds – and both the app and the buddies keep themselves up to date. If Windows warns on first start: <b>More info → Run anyway</b>.'`,
  `bu_app_btn:'Download app ↓'`,
  `bu_s1:'<b>Install the app.</b> Download and run <code>ClaudeBuddySetup.exe</code> – no admin rights needed.'`,
  `bu_s2:'<b>Plug in the buddy.</b> With a USB cable that has data lines. The wizard recognizes T-Display, Watcher and AMOLED and flashes new devices.'`,
  `bu_s3:'<b>Click through.</b> Wi-Fi, pairing, location for the weather, speech model and Claude Code – all in the wizard.'`,
  `bu_s4:'<b>Restart Claude Code.</b> From then on every session tells the buddy what it is doing.'`,
  `bu_s5:'<b>Controls.</b> T-Display: IO0 pokes, IO14 shows info. Watcher: press the knob, hold to talk, double-press for the menu. AMOLED: PWR acts as the knob, BOOT moves on.'`,
  `bu_hb_h:'📖 Manual (German)'`,
  `bu_hb_p:'How it all works: devices, controls, talking and reading aloud, pairing, safe updates, troubleshooting – with pictures.'`,
  `bu_hb_btn:'Open manual (PDF) →'`,
  `bu_fl_h:'⚡ Without the app: firmware in the browser'`,
  `bu_upd_p:'<b>T-Display-S3:</b> install new firmware, Wi-Fi and settings are kept. Do <b>not</b> tick “Erase device?”. Watcher and AMOLED update themselves.'`,
  `bu_neu_p:'For <b>new boards</b> or when nothing works anymore – Wi-Fi and settings will be gone. Pick the device:'`,
  `bu_neu_t:'🗑️ T-Display-S3'`,
  `bu_neu_w:'🗑️ SenseCAP Watcher'`,
  `bu_neu_a:'🗑️ AMOLED 1.75C'`,
  `bu_auto_h:'✳️ Full-size simulation'`,
  `bu_auto_p:'All states, pastimes, celebrations, LED and sound to try out – running exactly the same code as the device. Linux/Mac: <a href="${BUDDY_SEITE}/buddy.py" download>PC script buddy.py</a>. Source and versions: ${BUDDY_GH}.'`,
  `bu_auto_btn:'Open simulation →'`,
].join(',\n');

function buddyAktualisieren(raw) {
  const fehler = [];
  let out = raw;
  function ersetze(name, such, neu) {
    const treffer = (out.match(new RegExp(such.source, 'g')) || []).length;
    if (treffer !== 1) { fehler.push(name + ': ' + treffer + ' Treffer'); return; }
    out = out.replace(such, () => neu);
  }
  if (!out.includes('id="buddy"')) return {out: raw, fehler: ['Claude-Buddy ist noch nicht eingebaut (erst basteln-buddy.js)']};
  ersetze('karte', /<a class="dl-karte" href="#buddy"[\s\S]*?<\/a>/, BUDDY_KARTE_NEU);
  ersetze('abschnitt', /<section class="dl-sec" id="buddy">[\s\S]*?<\/section>/, BUDDY_ABSCHNITT_NEU);
  ersetze('en karte', /k_buddy:'[^']*'/, "k_buddy:'Shows on your desk what Claude Code is doing – with voice, light and sound.'");
  ersetze('en texte', /bu_h2:'[\s\S]*?bu_auto_btn:'[^']*'/, BUDDY_EN_NEU);
  return {out: fehler.length ? raw : out, fehler};
}

// ---------- Ausfuehren: Seite holen, aktualisieren, nach Rueckfrage speichern ----------
(async function buddySpeichern() {
  if (typeof location === 'undefined' || !location.hostname.endsWith('daveslab.de')) { if (typeof alert !== 'undefined') alert('Bitte auf daveslab.de/wp-admin ausfuehren.'); return; }
  const nonce = (typeof wpApiSettings !== 'undefined' && wpApiSettings.nonce) ||
                await (await fetch('/wp-admin/admin-ajax.php?action=rest-nonce', {credentials: 'include'})).text();
  if (!nonce || nonce === '0') { alert('Nicht angemeldet - bitte erst bei WordPress anmelden.'); return; }
  const kopf = {'X-WP-Nonce': nonce, 'Content-Type': 'application/json'};
  const liste = await (await fetch('/wp-json/wp/v2/pages?slug=basteln&context=edit&_fields=id,content', {headers: kopf, credentials: 'include'})).json();
  if (!Array.isArray(liste) || !liste[0]) { alert('Seite "basteln" nicht gefunden: ' + JSON.stringify(liste).slice(0, 200)); return; }
  const seite = liste[0];
  const {out, fehler} = buddyAktualisieren(seite.content.raw);
  if (fehler.length) { alert('Nichts geaendert:\n' + fehler.join('\n')); return; }
  if (!confirm('Claude-Buddy auf der Seite "basteln" aktualisieren und speichern?\n(' + seite.content.raw.length + ' -> ' + out.length + ' Zeichen)')) return;
  const r = await fetch('/wp-json/wp/v2/pages/' + seite.id, {method: 'POST', headers: kopf, credentials: 'include', body: JSON.stringify({content: out})});
  alert(r.ok ? 'Gespeichert! Jetzt https://daveslab.de/basteln/ neu laden.' : 'Fehler beim Speichern: ' + r.status + ' ' + (await r.text()).slice(0, 200));
})();
