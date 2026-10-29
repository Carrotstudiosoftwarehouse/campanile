<p align="right"><b>English</b> · <a href="#italiano">Italiano</a></p>

# Roadmap

## Where we want to go

Campanile is the first brick of something bigger: open civil infrastructure, built by the
community, that keeps working when the central one fails after an attack, a hybrid war or a
disaster.

Today a Campanile is one node: a neighborhood, a square, a gym. The goal is a **network of nodes**
that pass notices from neighborhood to neighborhood without the internet. No company owns it and
it tracks no one (no accounts, no analytics, no record of who connects). It belongs to whoever
switches it on.

Nobody can build this alone. Everything below is an open idea, not a promise. If one speaks to
you, open an issue.

**The order matters.** First one node that works, that anyone can use and that is honest about
its limits. Then many. A network nobody can rely on would only spread the problem.

**Available is not proven.** A ticked box means released and tested in the lab, not proven in the
field with many real people. What we tested: [docs/TESTING.md](docs/TESTING.md). Our limits:
[docs/LIMITS.md](docs/LIMITS.md).

## Now: 0.1, a single node (available, tested in the lab)

- [x] Official notices, "I offer / I need" board, "I'm safe" registry
- [x] Offline map and Wikipedia, family plan, printable sign with QR code
- [x] Offline map search: streets, towns, the nearest hospital, pharmacy, water or police
- [x] Navigator on foot or by car inside your area, around streets the admin marks as blocked
- [x] Laptop mode (double click) and Raspberry Pi mode (hotspot and captive portal)
- [x] Browser setup on a laptop: world map, your area (framed by itself), offline medicine in
  Italian and English
- [x] English and Italian, picked from the phone's language
- [x] One-page printable guide for whoever runs it, static online demo
- [x] More Campaniles without internet: a full copy on a USB stick that starts on a computer with
  nothing installed, and maps and Wikipedia over Wi-Fi between Campaniles, signed with a code
- [x] Signed notices checked by the Campanile (Ed25519). Flood defenses: limits per device, posts
  held for approval, cleanup in batches
- [x] One password per person on the admin page, made by the Campanile: the log says who did what
- [x] Signed versions: every release signed offline by CarrotStudio, and GitHub publishes only a
  package that matches. A Campanile updates from a USB stick only to a newer signed version, and a
  power cut halfway is finished at the next start
- [x] Pages ready for right-to-left languages such as Arabic: only the translation is missing
- [x] Ready for North America: the laptop's window in the computer's language, the emergency
  number set on the admin page (911 by itself on a computer set to the US or Canada), miles,
  addresses written the American way
- [x] A simpler home page: official notices first (one in view, the rest behind a button),
  then "I need" and "I can give", then medicine, map and family plan
- [x] Accessibility checked by machine: every page in both languages passes axe-core's WCAG 2.2 AA
  check and stays readable at 200% zoom without sideways scrolling. Large buttons, black on white,
  red only for warnings, ink blue only for section titles
- [x] Tested on a real iPhone and on Windows 11 as an ordinary person would. Installer tested on
  Debian 12 and 13. Tests on Linux, Windows and macOS at every change
- [x] Our own security reviews, as attackers: every finding fixed with a test that fails on the
  old code (no external audit yet)

## First: one node you can rely on

This comes before any network, roughly in this order.

**1. Proven in the field**

- [ ] **Real Raspberry Pi**: hotspot and captive portal on Android and iPhone
- [ ] **Field drill**: 20-30 phones at once in a gym or a square, measuring speed and power draw
- [ ] **Android**, and the other parts we couldn't test ([docs/TESTING.md](docs/TESTING.md))
- [ ] **Field checks of the defenses**: phones isolated by the Raspberry's Wi-Fi chip, Android
  with "private DNS" on, the family plan in the iPhone's captive-portal window (its storage may
  not persist)
- [ ] **Maps made by others in the automatic tests**, not only our test generator's. Today real
  maps are tried by hand
- [ ] **An external security audit**, by people outside the project, starting from our web server
- [ ] **Sharing over a channel authenticated by the code**, so whoever stands between two
  Campaniles can't hold the downloads
- [x] **A shorter `server.py`**: the request handling split from what each request does, in
  five modules, by moving code only, with the same tests green before and after

**2. Usable by everyone, starting now**

An automatic check finds only some of the problems. The rest takes people.

- [ ] **Family test** on every release: five non-technical people use it with no help
- [ ] **Screen readers**: VoiceOver and TalkBack, tried by people who use them every day
- [ ] **Plain words**: every sentence on the pages read by someone who finds reading hard
- [ ] **More languages** (Ukrainian, Arabic, French, German, Spanish...). Each is the text of
  `campanile/web/strings.js` and `campanile/messages.py`, translated, and each opens a new
  country. Right-to-left languages are ready: pages mirror by themselves, and Arabic street
  names come out right on the map (checked on Cairo). Only the translation is missing, by a
  native speaker

**3. Trust the phone can check by itself**

- [ ] **HTTPS with a real certificate per Campanile** (a domain, certificates issued before the
  emergency), so phones can tell it from a fake network with the same name. The priority here,
  since a fake can also leave its pages in a phone's cache (tested). It would also let the
  navigator know where the phone is
- [ ] **Safe admin from a phone**: today a Raspberry is managed only with a screen, or from a
  computer over SSH, since the password would cross the open Wi-Fi in clear. It needs HTTPS first
- [ ] **Signed notices checked on the phone**, with a key that doesn't travel on the same network
- [ ] **Two keys for a signed notice**: it counts only when, say, 2 of 3 trusted people sign it, so
  one stolen key is not enough. Rules from multisigs read in real code (EtherFi's MultiSig, 0x
  Settler's Safe guard): each signer counts once and only if listed, the threshold is never 0
  nor above the number of keys, and spare keys keep notices going if one is lost. Each signature
  already binds one notice, once (own prefix, expiry, duplicates refused)
- [ ] **IT-alert's own signatures checked**, to mark alerts that really come from the civil
  protection as "verified". Tried on 26 October 2026 with signxml, a proven library. The three
  signed messages IT-alert published in summer 2023
  ([pcm-dpc/IT-alert-Hub](https://github.com/pcm-dpc/IT-alert-Hub)) verify against its published
  certificate, and one changed letter breaks them. But that certificate expired in June 2024,
  later messages are unsigned, and the registry that should vouch for it doesn't verify. A
  "verified" built on that would be false. It needs the civil protection's current keys first
- [ ] **Twin-network detector**: a second Wi-Fi adapter listens for a fake "Campanile" nearby and
  posts a warning. **Only a warning, never a proof.** It misses a fake it can't hear, or a close
  copy. HTTPS and signatures are what prove a Campanile is real
- [ ] **Encrypted open Wi-Fi** (OWE / "Enhanced Open"), if the Raspberry's chip and phones support
  it

**4. Ready to switch on**

- [ ] **The Campanile kit**: a documented, ready-made device with backup power that a family or an
  association switches on with no setup

## Then: from one node to a network

Only once a single node has proven itself in the field.

- [ ] **Sync on contact**: two Campaniles, or a USB stick carried by hand, exchange posts and "I'm
  safe" names, so families split across neighborhoods can find each other
- [ ] **Campaniles talking by radio**: notices over LoRa radios (for example Meshtastic),
  kilometers apart, without internet

---

<a id="italiano"></a>
<p align="right"><a href="#roadmap">English</a> · <b>Italiano</b></p>

# Roadmap (italiano)

## Dove vogliamo arrivare

Il Campanile è il primo mattone di qualcosa di più grande: un'infrastruttura civile aperta,
costruita dalla community, che regga quando quella centrale cade per un attacco, una guerra ibrida
o un disastro.

Oggi un Campanile è un nodo solo: un quartiere, una piazza, una palestra. L'obiettivo è una **rete
di nodi** che passano gli avvisi da un quartiere all'altro senza internet. Non è di nessuna
azienda e non traccia nessuno (niente account, niente statistiche, nessun registro di chi si
collega). È di chi lo accende.

Da soli non si costruisce. Tutto quello che segue è un'idea aperta, non una promessa. Se una di
queste ti parla, apri una issue.

**L'ordine conta.** Prima un nodo solo che funziona, che chiunque sa usare e che dice onestamente
i suoi limiti. Poi tanti. Una rete su cui nessuno può contare porterebbe soltanto il problema più
lontano.

**Disponibile non vuol dire provato sul campo.** Una casella spuntata vuol dire che c'è nella
versione ed è provato in laboratorio, non che ha funzionato sul campo con molte persone vere.
Cosa abbiamo provato: [docs/PROVE.md](docs/PROVE.md). I nostri limiti:
[docs/LIMITI.md](docs/LIMITI.md).

## Adesso: 0.1, un nodo (disponibile, provato in laboratorio)

- [x] Avvisi ufficiali, bacheca "offro / cerco", registro "sto bene"
- [x] Mappa e Wikipedia offline, piano familiare, cartello con codice QR
- [x] Ricerca nella mappa senza internet: vie, paesi, l'ospedale, la farmacia, l'acqua o la
  polizia più vicini
- [x] Navigatore a piedi o in auto dentro la tua zona, che evita le strade segnate come interrotte
  dalla gestione
- [x] Modalità portatile (doppio clic) e Raspberry Pi (hotspot e portale che si apre da solo)
- [x] Preparazione dal browser sul portatile: mappa del mondo, la tua zona (inquadrata da sola),
  medicina offline in italiano e inglese
- [x] Italiano e inglese, scelti dalla lingua del telefono
- [x] Guida di una pagina per chi lo gestisce, demo online statica
- [x] Altri Campanili senza internet: una copia completa su chiavetta che parte su un computer
  senza niente installato, e mappe e Wikipedia via Wi-Fi fra Campanili, firmate con un codice
- [x] Avvisi firmati verificati dal Campanile (Ed25519). Difese contro le inondazioni: limiti per
  dispositivo, annunci in attesa di approvazione, pulizia a gruppi
- [x] Una password per persona nella gestione, creata dal Campanile: il registro dice chi ha fatto
  cosa
- [x] Versioni firmate: ogni versione firmata offline da CarrotStudio, e GitHub pubblica solo un
  pacchetto che combacia. Un Campanile si aggiorna da chiavetta solo a una versione più nuova e
  firmata, e un blackout a metà viene completato alla riaccensione
- [x] Pagine pronte per le lingue da destra a sinistra come l'arabo: manca solo la traduzione
- [x] Pronto per il Nord America: la finestra del portatile nella lingua del computer, il numero
  di emergenza impostato nella gestione (911 da solo su un computer impostato su Stati Uniti o
  Canada), le miglia, gli indirizzi scritti all'americana
- [x] Una pagina principale più semplice: prima gli avvisi ufficiali (uno in vista, gli altri
  dietro un bottone), poi "Ho bisogno" e "Offro", poi medicina, mappa e piano familiare
- [x] Accessibilità controllata dalla macchina: ogni pagina nelle due lingue supera il controllo
  WCAG 2.2 AA di axe-core e resta leggibile con lo zoom al 200% senza scorrere di lato. Pulsanti
  grandi, nero su bianco, rosso solo per gli avvisi, blu inchiostro solo per i titoli delle sezioni
- [x] Provato su un iPhone vero e su Windows 11 come farebbe una persona qualunque. Installazione
  provata su Debian 12 e 13. Test su Linux, Windows e macOS a ogni modifica
- [x] Revisioni di sicurezza fatte da noi, da attaccanti: ogni difetto corretto con un test che
  fallisce sul codice di prima (nessun audit esterno, per ora)

## Prima di tutto: un nodo su cui contare

Viene prima di qualunque rete, più o meno in quest'ordine.

**1. Provato sul campo**

- [ ] **Raspberry Pi vero**: hotspot e portale automatico su Android e iPhone
- [ ] **Esercitazione**: 20-30 telefoni insieme in una palestra o in piazza, misurando velocità e
  consumi
- [ ] **Android**, e le altre parti che non abbiamo potuto provare ([docs/PROVE.md](docs/PROVE.md))
- [ ] **Verifiche sul campo delle difese**: telefoni isolati dal chip Wi-Fi del Raspberry, Android
  con "DNS privato" attivo, il piano familiare nella finestra del portale dell'iPhone (il suo
  spazio di memoria potrebbe non restare)
- [ ] **Mappe fatte da altri nei test automatici**, non solo quelle del nostro generatore di
  prova. Oggi le mappe vere si provano a mano
- [ ] **Un audit di sicurezza esterno**, fatto da persone fuori dal progetto, a partire dal nostro
  server web
- [ ] **Condivisione su un canale autenticato con il codice**, così chi si mette fra due
  Campanili non può tenerne occupati i download
- [x] **Un `server.py` più corto**: la gestione delle richieste separata da quello che ognuna fa,
  in cinque moduli, solo spostando codice, con gli stessi test verdi prima e dopo

**2. Usabile da tutti, da subito**

Un controllo automatico trova solo una parte dei problemi. Il resto lo trovano le persone.

- [ ] **Test delle famiglie** a ogni release: cinque persone non tecniche lo usano senza aiuto
- [ ] **Lettori di schermo**: VoiceOver e TalkBack, provati da chi li usa tutti i giorni
- [ ] **Parole semplici**: ogni frase delle pagine letta da qualcuno che fa fatica a leggere
- [ ] **Altre lingue** (ucraino, arabo, francese, tedesco, spagnolo...). Ognuna è il testo di
  `campanile/web/strings.js` e `campanile/messages.py`, tradotto, e ognuna apre un paese.
  Le lingue da destra a sinistra sono pronte: le pagine si rovesciano da sole, e sulla mappa i
  nomi arabi escono giusti (provato sul Cairo). Manca solo la traduzione, da un madrelingua

**3. Fiducia che il telefono verifica da solo**

- [ ] **HTTPS con un certificato vero per ogni Campanile** (un dominio, certificati rilasciati
  prima dell'emergenza), così i telefoni lo distinguono da una rete falsa con lo stesso nome. È
  la priorità di questo gruppo, perché una rete falsa può anche lasciare le sue pagine nella cache
  di un telefono (provato). Permetterebbe anche al navigatore di sapere dove si trova il telefono
- [ ] **Gestione sicura dal telefono**: oggi un Raspberry si gestisce solo con uno schermo, o da
  un computer via SSH, perché la password passerebbe in chiaro sulla Wi-Fi aperta. Serve prima
  HTTPS
- [ ] **Avvisi firmati verificati sul telefono**, con una chiave che non viaggia sulla stessa rete
- [ ] **Due chiavi per un avviso firmato**: vale solo se lo firmano, per esempio, 2 persone fidate
  su 3, così una chiave rubata non basta. Regole prese da multisig letti nel codice vero (il
  MultiSig di EtherFi, la Safe guard di 0x Settler): ogni firmatario conta una volta sola e solo
  se è in lista, la soglia non è mai 0 né più alta del numero di chiavi, e le chiavi di scorta
  tengono in piedi gli avvisi se se ne perde una. Ogni firma vale già per un solo avviso, una
  volta (prefisso proprio, scadenza, doppioni rifiutati)
- [ ] **Firme di IT-alert verificate**, per segnare come "verificato" un allarme che arriva
  davvero dalla protezione civile. Provato il 26 ottobre 2026 con signxml, una libreria
  collaudata. I tre messaggi firmati pubblicati da IT-alert nell'estate 2023
  ([pcm-dpc/IT-alert-Hub](https://github.com/pcm-dpc/IT-alert-Hub)) si verificano con il suo
  certificato pubblicato, e una lettera cambiata li rompe. Ma quel certificato è scaduto a giugno
  2024, i messaggi successivi non sono firmati, e il registro che dovrebbe garantirlo non si
  verifica. Un "verificato" costruito così sarebbe falso. Servono prima le chiavi attuali della
  protezione civile
- [ ] **Rilevatore di reti gemelle**: una seconda antenna Wi-Fi ascolta se nei paraggi c'è un falso
  "Campanile" e pubblica un avviso. **Solo un avviso, mai una prova.** Gli sfugge un falso che non
  sente, o una copia fedele. A provare che un Campanile è vero sono HTTPS e le firme
- [ ] **Wi-Fi aperta ma cifrata** (OWE / "Enhanced Open"), se il chip del Raspberry e i telefoni
  lo supportano

**4. Pronto da accendere**

- [ ] **Il kit Campanile**: un dispositivo pronto e documentato, con alimentazione di riserva, che
  una famiglia o un'associazione accende senza configurare niente

## Poi: da un nodo a una rete

Solo quando un nodo da solo ha dato prova di sé sul campo.

- [ ] **Sincronizzazione al contatto**: due Campanili, o una chiavetta USB portata a mano, si
  scambiano annunci e nomi di "sto bene", così le famiglie separate tra quartieri si ritrovano
- [ ] **Campanili che si parlano via radio**: avvisi via radio LoRa (per esempio Meshtastic), a
  chilometri di distanza, senza internet
