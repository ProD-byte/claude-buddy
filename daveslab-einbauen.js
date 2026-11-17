// Baut den "Claude-Buddy" in den Rohinhalt von daveslab.de/basteln ein
// (eigene Projektkarte oben und eigener Abschnitt ganz unten, hinter dem Axolotl-Aquarium, mit eingebetteter Simulation).
// Gleiches Prinzip wie basteln-aquarium.js und basteln-wetter.js: jede Ersetzung muss genau einmal passen,
// sonst wird nichts gespeichert. Firmware, Flasher, Simulation und PC-Skript liegen auf GitHub Pages
// (https://prod-byte.github.io/claude-buddy/) und werden bei jedem Release (tools/release.py) neu
// hochgeladen - auf daveslab.de muss man danach nichts mehr aendern.
//
// SO BENUTZEN (selbst, in Chrome):
//   1. Bei https://daveslab.de/wp-admin/ anmelden
//   2. F12 -> Reiter "Console" -> diese ganze Datei hineinkopieren -> Enter
//      (fragt Chrome nach "allow pasting": einmal  allow pasting  eintippen, Enter, nochmal einfuegen)
//   3. Es kommt eine Rueckfrage "Speichern?" -> OK. Danach https://daveslab.de/basteln/ neu laden.
//   WordPress hebt die alte Fassung als Revision auf (Seite bearbeiten -> Revisionen).
function buddyEinbauen(raw) {
  const fehler = [];
  let out = raw;
  function ersetze(name, such, neu) {
    const treffer = typeof such === 'string' ? out.split(such).length - 1 : (out.match(new RegExp(such.source, 'g')) || []).length;
    if (treffer !== 1) { fehler.push(name + ': ' + treffer + ' Treffer'); return; }
    out = out.replace(such, typeof neu === 'function' ? neu : () => neu);
  }
  if (out.includes('id="buddy"')) return {out: raw, fehler: ['Claude-Buddy ist schon eingebaut']};

  // --- Projektkarte oben (hinter dem Aquarium) ---
  ersetze('karte', /<a class="dl-karte" href="#aquarium"[\s\S]*?<\/a>/, m => m + '\n        ' + BUDDY_KARTE);
  ersetze('anzahl de', '</b>5 Projekte', '</b>6 Projekte');
  ersetze('anzahl en', '<b>MAKING</b>5 projects', '<b>MAKING</b>6 projects');

  // --- Abschnitt ganz unten, vor dem Fuss ---
  ersetze('abschnitt', '<footer class="dl-foot">', BUDDY_ABSCHNITT + '\n\n  <footer class="dl-foot">');

  // --- Karte -> Abschnitt (die Karten oeffnen immer nur ein Projekt) ---
  ersetze('proj', "aquarium:['aquarium']};", "aquarium:['aquarium'],buddy:['buddy']};");

  // --- Englische Uebersetzungen (hinter den Aquarium-Texten) ---
  ersetze('en buddy', "aq_web_btn:'Open aquarium →',", "aq_web_btn:'Open aquarium →',\n" + BUDDY_EN + ',');

  // --- Build-Nummer anzeigen ---
  ersetze('var build', "buildMaerchen=null,buildAquarium=null;", "buildMaerchen=null,buildAquarium=null,buildBuddy=null;");
  ersetze('setze ver', "if(va&&buildAquarium!==null)va.textContent=(W.ver||DE.ver).replace('{0}',buildAquarium);",
    "if(va&&buildAquarium!==null)va.textContent=(W.ver||DE.ver).replace('{0}',buildAquarium);\n" +
    "  var vb=document.getElementById('dl-ver-buddy');if(vb&&buildBuddy!==null)vb.textContent=(W.ver||DE.ver).replace('{0}',buildBuddy);");
  ersetze('fetch buddy', "fetch('https://prod-byte.github.io/axolotl-aquarium/version.json'",
    BUDDY_SKRIPT + "\nfetch('https://prod-byte.github.io/axolotl-aquarium/version.json'");

  return {out: fehler.length ? raw : out, fehler};
}

var BUDDY_SEITE = 'https://prod-byte.github.io/claude-buddy';
var BUDDY_GH = '<a href="https://github.com/ProD-byte/claude-buddy" target="_blank" rel="noopener">GitHub</a>';

var BUDDY_KARTE = `<a class="dl-karte" href="#buddy" data-p="buddy" aria-expanded="false"><span class="ic">✳️</span><h3>Claude-Buddy</h3><p data-t="k_buddy">Zeigt oben am Laptop, was Claude Code gerade macht.</p><small>LILYGO T-Display-S3</small><span class="auf-zu" data-t="k_auf">Öffnen</span></a>`;

// Kasten "PC-Skript" (wie "Zur Einstellungsseite" bei der Wetterstation)
var BUDDY_PC = `      <div class="dl-auto rv" style="margin-top:14px">
        <div>
          <h3 data-t="bu_pc_h">💻 PC-Skript für Claude Code</h3>
          <p data-t="bu_pc_p">Python installieren, <code>buddy.py</code> herunterladen und im selben Ordner <code>pip install pyserial pillow</code> und <code>python buddy.py install</code> ausführen. Das trägt Hooks in Claude Code ein – jede neue Sitzung meldet dem Buddy dann, was sie gerade tut. Entfernen: <code>python buddy.py uninstall</code>, ausprobieren: <code>python buddy.py demo</code>.</p>
        </div>
        <a class="dl-btn" href="${BUDDY_SEITE}/buddy.py" download data-t="bu_pc_btn">buddy.py laden ↓</a>
      </div>`;

var BUDDY_ABSCHNITT = `  <section class="dl-sec" id="buddy">
    <div class="dl-wrap">
      <h2 class="dl-h2 rv" data-t="bu_h2">Claude-Buddy <span class="dl-grad">einrichten</span></h2>
      <p class="dl-sub rv"><span data-t="bu_sub">Ein kleiner Begleiter auf dem <b>LILYGO T-Display-S3</b>, der wie eine Webcam oben am Laptop sitzt und zeigt, was <b>Claude Code</b> gerade macht: nachdenken, Dateien lesen, Code schreiben, Befehle im Terminal, im Internet suchen – und wenn Claude dich braucht, winkt er, die LED blinkt und es klingt leise. Nach langen Aufgaben gibt es Feuerwerk, im Leerlauf spielt er Jo-Jo oder gießt seine Pflanze. Laufen mehrere Claude-Sitzungen, zeigen kleine Mini-Buddys die anderen Projekte. Er erkennt Commits, Pushes, Bauen, Aufspielen und Tests (mit grünem oder rotem Ergebnis), und Screenshots von Claude hält er kurz als Polaroid hoch. Inoffizielles Bastelprojekt, kein Produkt von Anthropic.</span> <span id="dl-ver-buddy"></span></p>
      <div class="rv" style="margin:6px 0 26px">
        <iframe id="dl-buddy-sim" src="${BUDDY_SEITE}/simulation.html?einbetten" title="Simulation des Claude-Buddys" loading="lazy" style="display:block;width:100%;height:1250px;border:0;background:transparent"></iframe>
      </div>
      <div class="dl-flash">
        <div class="dl-opt rv">
          <h3 data-t="upd_h">🔄 Update</h3>
          <p data-t="bu_upd_p">Neue Firmware aufspielen – <b>WLAN und Einstellungen bleiben erhalten.</b> Bei „Erase device?“ den Haken <b>nicht</b> setzen.</p>
          <esp-web-install-button manifest="${BUDDY_SEITE}/manifest-update.json">
            <button slot="activate" data-t="upd_btn">⚡ Update installieren</button>
            <span slot="unsupported" data-t="unsup"><b>Dieser Browser kann das leider nicht.</b> Bitte Chrome oder Edge am Computer verwenden.</span>
            <span slot="not-allowed" data-t="notall"><b>Nur über https möglich.</b></span>
          </esp-web-install-button>
        </div>
        <div class="dl-opt rot rv">
          <h3 data-t="neu_h">🧹 Neuinstallation</h3>
          <p data-t="bu_neu_p">Speicher komplett löschen und neu aufspielen – für <b>neue Boards</b> oder wenn gar nichts mehr geht. <b>WLAN und Einstellungen sind danach weg.</b></p>
          <esp-web-install-button manifest="${BUDDY_SEITE}/manifest-neu.json">
            <button slot="activate" data-t="neu_btn">🗑️ Löschen &amp; neu installieren</button>
            <span slot="unsupported" data-t="unsup"><b>Dieser Browser kann das leider nicht.</b> Bitte Chrome oder Edge am Computer verwenden.</span>
            <span slot="not-allowed" data-t="notall"><b>Nur über https möglich.</b></span>
          </esp-web-install-button>
        </div>
      </div>
      <ol class="dl-schritte" style="margin-top:28px">
        <li class="rv" data-t="bu_s1"><b>Board anschließen.</b> T-Display per <b>USB-C</b> mit dem Computer verbinden (Kabel mit Datenleitungen) und <b>Chrome</b> oder <b>Edge</b> öffnen.</li>
        <li class="rv" data-t="bu_s2"><b>Anschluss auswählen.</b> Meist „USB JTAG/serial debug unit“ – ein Treiber ist nicht nötig. <b>Keine Verbindung?</b> Taste <b>BOOT</b> gedrückt halten, kurz <b>RST</b> an der Seite drücken, BOOT loslassen – nochmal versuchen.</li>
        <li class="rv" data-t="bu_s3"><b>PC einrichten.</b> <code>buddy.py</code> laden (Knopf unten), dann <code>pip install pyserial pillow</code> und <code>python buddy.py install</code>. Ab der nächsten Claude-Code-Sitzung zeigt der Buddy mit, was passiert – solange er per USB am PC hängt.</li>
        <li class="rv" data-t="bu_s4"><b>Ohne Kabel</b> (optional): Am Buddy <b>beide Tasten 2 s</b> halten, mit dem Handy ins WLAN <b>„Claude-Buddy“</b> gehen und dein WLAN wählen. Dann kommen die Meldungen übers Netz, und abends wird er müde, nachts trägt er eine Zipfelmütze.</li>
        <li class="rv" data-t="bu_s5"><b>Bedienen.</b> <b>IO0</b> kurz stupst ihn an, lang schaltet stumm. <b>IO14</b> kurz zeigt Infos oder bestätigt „Brauche dich“, lang öffnet die Einstellungen (Lautstärke, LED, Helligkeit, Bild drehen, Sprache Deutsch/Englisch, Updates). Neue Versionen holt er sich nachts von selbst übers WLAN.</li>
        <li class="rv" data-t="bu_s6"><b>Extras</b> (optional): passiver 9-mm-Buzzer an <b>IO16</b> und GND, WS2812B-LED mit DIN über 330 Ω an <b>IO13</b>, dazu 5V und GND. Hinter einem weißen 3D-Druck-Diffusor leuchtet die LED weich in der Farbe der Tätigkeit.</li>
      </ol>
${BUDDY_PC}
      <div class="dl-auto rv" style="margin-top:14px">
        <div>
          <h3 data-t="bu_auto_h">✳️ Simulation in groß</h3>
          <p data-t="bu_auto_p">Alle Zustände, Beschäftigungen, Feiern, LED und Ton zum Ausprobieren – mit genau demselben Programmcode wie auf dem Gerät. Firmware-Versionen: ${BUDDY_GH}.</p>
        </div>
        <a class="dl-btn" href="${BUDDY_SEITE}/simulation.html" target="_blank" rel="noopener" data-t="bu_auto_btn">Simulation öffnen →</a>
      </div>
    </div>
  </section>`;

// Hoehe der Simulation anpassen und ihr die Sprache der Seite melden (wie beim Aquarium).
var BUDDY_SPRACHE = `addEventListener('message',function(e){if(e.origin==='https://prod-byte.github.io'&&e.data&&e.data.buddyHoehe){var f=document.getElementById('dl-buddy-sim');if(f){f.style.height=e.data.buddyHoehe+'px';f.contentWindow.postMessage({buddySprache:document.documentElement.lang||'de'},'https://prod-byte.github.io');}}});
(function(){function melde(){var l=document.documentElement.lang||'de',f=document.getElementById('dl-buddy-sim'),a=document.querySelector('a[data-t="bu_auto_btn"]');if(a)a.href='${BUDDY_SEITE}/simulation.html?lang='+l;if(f&&f.contentWindow)f.contentWindow.postMessage({buddySprache:l},'https://prod-byte.github.io');}melde();new MutationObserver(melde).observe(document.documentElement,{attributes:true,attributeFilter:['lang']});})();`;

var BUDDY_SKRIPT = `fetch('${BUDDY_SEITE}/version.json',{cache:'no-store'}).then(function(r){return r.json();}).then(function(j){buildBuddy=j.build;setze(sprache);var f=document.getElementById('dl-buddy-sim');if(f){var u=new URL(f.src);if(!u.searchParams.has('v')){u.searchParams.set('v',j.stand||j.build);f.src=u.href;}}}).catch(function(){});
${BUDDY_SPRACHE}`;

var BUDDY_EN = [
  `k_buddy:'Shows on top of your laptop what Claude Code is doing right now.'`,
  `bu_h2:'Set up the <span class="dl-grad">Claude buddy</span>'`,
  `bu_sub:'A little companion on the <b>LILYGO T-Display-S3</b> that sits on top of your laptop like a webcam and shows what <b>Claude Code</b> is doing: thinking, reading files, writing code, running commands, searching the web – and when Claude needs you, it waves, the LED blinks and it chimes softly. Long tasks end with fireworks, when idle it plays with a yo-yo or waters its plant. With several Claude sessions, little mini buddies show the other projects. It recognises commits, pushes, builds, flashing and tests (with a green or red result), and holds up Claude’s screenshots as a polaroid for a moment. Unofficial hobby project, not a product of Anthropic.'`,
  `bu_upd_p:'Install new firmware – <b>Wi-Fi and settings are kept.</b> Do <b>not</b> tick “Erase device?”.'`,
  `bu_neu_p:'Erase everything and install from scratch – for <b>new boards</b> or when nothing works anymore. <b>Wi-Fi and settings will be gone.</b>'`,
  `bu_s1:'<b>Connect the board.</b> Plug the T-Display into the computer via <b>USB-C</b> (a cable with data lines) and open <b>Chrome</b> or <b>Edge</b>.'`,
  `bu_s2:'<b>Select the port.</b> Usually “USB JTAG/serial debug unit” – no driver needed. <b>No connection?</b> Hold <b>BOOT</b>, briefly press <b>RST</b> on the side, release BOOT – try again.'`,
  `bu_s3:'<b>Set up the PC.</b> Download <code>buddy.py</code> (button below), then run <code>pip install pyserial pillow</code> and <code>python buddy.py install</code>. From the next Claude Code session on, the buddy shows what is happening – as long as it is connected to the PC via USB.'`,
  `bu_s4:'<b>Without a cable</b> (optional): hold <b>both buttons for 2 s</b>, connect your phone to the Wi-Fi <b>“Claude-Buddy”</b> and pick your Wi-Fi. Then the messages arrive over the network – and it gets sleepy in the evening and wears a nightcap at night.'`,
  `bu_s5:'<b>Controls.</b> <b>IO0</b> short pokes it, hold to mute. <b>IO14</b> short shows info or confirms “needs you”, hold opens the settings (volume, LED, brightness, rotate image, language German/English, updates).'`,
  `bu_s6:'<b>Extras</b> (optional): passive 9 mm buzzer on <b>IO16</b> and GND, WS2812B LED with DIN via 330 Ω on <b>IO13</b>, plus 5V and GND. Behind a white 3D-printed diffuser the LED glows softly in the colour of the current activity.'`,
  `bu_pc_h:'💻 PC script for Claude Code'`,
  `bu_pc_p:'Install Python, download <code>buddy.py</code> and run <code>pip install pyserial pillow</code> and <code>python buddy.py install</code> in the same folder. This adds hooks to Claude Code – every new session then tells the buddy what it is doing. Remove: <code>python buddy.py uninstall</code>, try it: <code>python buddy.py demo</code>.'`,
  `bu_pc_btn:'Download buddy.py ↓'`,
  `bu_auto_h:'✳️ Full-size simulation'`,
  `bu_auto_p:'All states, pastimes, celebrations, LED and sound to try out – running exactly the same code as the device. Firmware versions: ${BUDDY_GH}.'`,
  `bu_auto_btn:'Open simulation →'`,
].join(',\n');

// ---------- Ausfuehren: Seite holen, einbauen, nach Rueckfrage speichern ----------
(async function buddySpeichern() {
  if (typeof location === 'undefined' || !location.hostname.endsWith('daveslab.de')) { if (typeof alert !== 'undefined') alert('Bitte auf daveslab.de/wp-admin ausfuehren.'); return; }
  const nonce = (typeof wpApiSettings !== 'undefined' && wpApiSettings.nonce) ||
                await (await fetch('/wp-admin/admin-ajax.php?action=rest-nonce', {credentials: 'include'})).text();
  if (!nonce || nonce === '0') { alert('Nicht angemeldet - bitte erst bei WordPress anmelden.'); return; }
  const kopf = {'X-WP-Nonce': nonce, 'Content-Type': 'application/json'};
  const liste = await (await fetch('/wp-json/wp/v2/pages?slug=basteln&context=edit&_fields=id,content', {headers: kopf, credentials: 'include'})).json();
  if (!Array.isArray(liste) || !liste[0]) { alert('Seite "basteln" nicht gefunden: ' + JSON.stringify(liste).slice(0, 200)); return; }
  const seite = liste[0];
  const {out, fehler} = buddyEinbauen(seite.content.raw);
  if (fehler.length) { alert('Nichts geaendert:\n' + fehler.join('\n')); return; }
  if (!confirm('Claude-Buddy einbauen und Seite "basteln" speichern?\n(' + seite.content.raw.length + ' -> ' + out.length + ' Zeichen)')) return;
  const r = await fetch('/wp-json/wp/v2/pages/' + seite.id, {method: 'POST', headers: kopf, credentials: 'include', body: JSON.stringify({content: out})});
  alert(r.ok ? 'Gespeichert! Jetzt https://daveslab.de/basteln/ neu laden.' : 'Fehler beim Speichern: ' + r.status + ' ' + (await r.text()).slice(0, 200));
})();
