# Sicurezza e privacy

English version: [THREAT-MODEL.md](THREAT-MODEL.md).

## In breve, per tutti

- La Wi-Fi è **aperta e non cifrata**. Chiunque nei dintorni può collegarsi e vedere tutti gli
  annunci, i nomi in "sto bene" e gli avvisi.
- **Nessun registro dei collegamenti.** Non si salvano indirizzi IP né pagine visitate.
- Annunci, nomi e avvisi cancellati vengono **sovrascritti sul disco**, non solo nascosti.
- Il piano famigliare **non arriva mai al Campanile e non resta nel telefono**. Vive nella pagina
  aperta, e si stampa.
- La gestione (avvisi, moderazione) funziona **solo dal Campanile stesso**, così la password non
  passa mai sulla Wi-Fi.
- **Niente resta per sempre.** Gli annunci si cancellano dopo 14 giorni, i nomi dopo 60
  (modificabili all'avvio), dal database, non nascosti (provato).
- **Le azioni di chi gestisce restano scritte**: cosa, quando e chi, perché ogni volontario può
  avere una password sua (la crea il Campanile, e se ne tiene solo l'impronta). Si tengono le
  ultime 1.000.
- **Chi gestisce può correggere l'orologio**, che il Raspberry perde senza internet (non ha batteria
  per l'orologio). Al massimo a un anno dall'ora del computer, e resta scritto. Lo seguono gli orari
  degli annunci, la cancellazione di quelli vecchi, gli avvisi firmati e l'ora dei telefoni
  (provato).

## Cosa può fare chi è collegato

Diamo per scontato che sulla rete ci sia anche chi vuole disturbare.

| Minaccia | Difesa |
|---|---|
| Testo che inganna l'occhio | Si tolgono i caratteri invisibili di formattazione (testo al contrario, spazi a larghezza zero), tranne quello che serve alle emoji. |
| Inserire codice nelle pagine (XSS) | Il testo degli utenti passa solo da `textContent`, mai come HTML. La CSP blocca script e stili non serviti dal Campanile. |
| Inondare da molti indirizzi | Limiti **per dispositivo**, dal MAC che vede il Raspberry. Cambiare IP non serve, cambiare MAC obbliga a ricollegarsi ogni volta. 5 annunci aperti, 10 nomi. Oltre 30 annunci in 5 minuti, i nuovi aspettano l'approvazione e la bacheca resta leggibile. Un clic chiude gli annunci di un dispositivo, o degli ultimi minuti. Si salva solo un'impronta che cambia ogni giorno, niente MAC né IP (provato). |
| Riempire bacheca o disco | 10 pubblicazioni ogni 10 minuti per dispositivo. Tetti di 2.000 annunci aperti, 5.000 nomi, 50 avvisi. Richieste fino a 8 KB. |
| Chiudere annunci altrui | Serve il codice di 8 caratteri (circa 40 bit) di chi ha pubblicato. 20 tentativi sbagliati in 10 minuti bloccano il dispositivo. |
| Indovinare la password di gestione | Gestione solo in locale, stesso blocco dopo 20 tentativi, confronto a tempo costante. |
| Una pagina di internet che parla col Campanile sotto il proprio nome (DNS rebinding) | Serve il browser del portatile che fa da Campanile, mentre è in rete. I nomi di dominio di internet ricevono 421. Indirizzi, nomi `.local` e il nome del computer funzionano, e nessuno può registrarli. Prima una pagina poteva leggere la bacheca e bloccare chi gestisce con 20 password sbagliate (provato, seconda revisione da attaccante). Ora non ottiene niente e il blocco non si muove. |
| Leggere file del sistema | I percorsi devono risolversi nella cartella del portale o delle mappe (solo `.pmtiles`). Trucchi di Windows rifiutati: flussi nascosti (`index.html:Zone.Identifier` rivelava da dove era stato scaricato il pacchetto, provato), punto o spazio finale, barra rovesciata, `con`, `nul` e simili. |
| Saturare il server | 256 connessioni, 16 per dispositivo, 10 secondi per mandare la richiesta (connessioni "a goccia", provato con un attacco reale). Sul Raspberry il firewall dell'hotspot, prima di nginx, lascia 64 connessioni per MAC. Migliaia di connessioni da un byte da un solo dispositivo facevano fallire agli altri 27 richieste su 60 e scrivevano 1,7 MB di registro al minuto. Ora 0 e 0 (provato). |
| Fingersi un altro telefono o il Campanile | Sul Raspberry limiti, blocco e gestione solo locale poggiano sull'indirizzo che scrive nginx (`X-Real-IP`). Il "request smuggling" poteva falsificarlo: una GET con un corpo eseguiva 8 richieste nascoste su 8. Due correzioni, ciascuna sufficiente da sola (provato una per una, poi 0 su 16). nginx manda una richiesta per connessione. Il Campanile accetta un corpo solo su POST, con un solo `Content-Length`, senza `chunked`. |
| Calo di corrente | Annunci e avvisi accettati sono su disco prima della risposta (SQLite `synchronous=FULL`). |
| Pagine dentro altri siti | `frame-ancestors 'none'`, `X-Frame-Options: DENY`. |

**Avvisi firmati (Ed25519):**

- Controllati da OpenSSL, tramite la libreria standard `cryptography`, dove c'è (il Raspberry).
  Senza (i portatili), dal nostro `ed25519.py`: solo verifica, nessun segreto, segue l'RFC 8032 e
  dà la stessa risposta di OpenSSL sui vettori dell'RFC, sui 210 casi Wycheproof di Google e su
  12.000 firme casuali. Per firmare si usa sempre `cryptography`.
- Le chiavi di fiducia si installano **prima**, su file, mai ricevute dalla rete, altrimenti chi
  falsifica l'avviso falsificherebbe anche la chiave.
- La firma copre titolo, testo, urgenza, data e **scadenza** (massimo 7 giorni). Il prefisso
  `campanile-notice-v1` la lega a questo solo uso.
- Lo stesso avviso firmato non si pubblica due volte, e sparisce alla scadenza.
- Il testo firmato non si ripulisce. Se ha caratteri non validi, si rifiuta.
- Chiavi JSON duplicate rifiutate ovunque, e si salva il documento verificato, riscritto, così due
  programmi non leggono due avvisi diversi.
- Un file delle chiavi rotto spegne solo gli avvisi firmati, non il Campanile.
- La scadenza segue l'orologio del Raspberry, che senza internet può sbagliare.

**Allarmi ufficiali CAP, da file nella pagina di gestione:**

- Il nostro lettore (`campanile/cap.py`, sul parser di Python) rifiuta qualsiasi DTD o entità, e
  così ferma la "billion laughs" e le entità esterne che leggono file del computer. Entrambi
  provati, con file oltre 512 kB (i messaggi veri di IT-alert, con i poligoni delle zone, arrivano a
  108 kB).
- Solo dalla pagina di gestione, quindi solo dal Campanile stesso. I telefoni non possono mandare la
  richiesta più grande che serve a un allarme e restano al limite di 8 kB (provato).
- Ogni blocco dev'essere CAP 1.1 o 1.2 valido, in qualunque lingua. Esercitazioni, prove,
  annullamenti, allarmi non pubblici, scaduti o ripetuti si rifiutano con il motivo. Il testo si
  ripulisce come quello di ogni avviso, mai accorciato.
- Un Campanile che vuole solo avvisi firmati rifiuta gli allarmi CAP.

**I nomi di "sto bene" in PFIF**, per un registro più grande dopo l'emergenza. Solo dalla pagina di
gestione, e resta scritto. I codici che tolgono un nome e le etichette dei telefoni non escono mai
(provato). Ogni voce dice che non è verificata, e i numeri delle voci portano un nome casuale
(`campanile-1a2b3c4d.invalid`) che non dice dove si trova il Campanile.

**Limiti noti, accettati consapevolmente:**

- **La firma la verifica il Campanile, non il telefono.** In HTTP su Wi-Fi aperta chi intercetta può
  alterare ciò che un telefono mostra, compresa l'etichetta "firmato". Una verifica nel browser non
  servirebbe, perché anche quel codice arriva dalla stessa rete. Un verificatore che non dipenda da
  questa rete (un'app o un secondo Campanile) è nella roadmap.
- **La firma propria di un allarme CAP non si controlla.** Il CAP ne prevede una, il Campanile la
  ignora. La fonte mostrata è quella che dichiara il file, e ci si fida perché chi gestisce ha
  scelto di caricarlo.
- **"Sto bene" non verifica l'identità.** Chiunque può registrare qualunque nome. La pagina lo dice
  chiaramente, perché una voce falsa darebbe una falsa rassicurazione.
- **Molte schede Wi-Fi, o un MAC o un indirizzo nuovo a ogni ricollegamento**, superano i limiti per
  dispositivo, compreso quello delle 10 pubblicazioni. Il freno d'emergenza manda i loro annunci in
  attesa, da togliere a gruppi, e restano i tetti globali e la moderazione. Sul portatile, che non
  vede i MAC, i limiti valgono per IP.
- **Un falso Campanile** (stesso nome di Wi-Fi, portale finto) non si distingue. Per il browser è
  *lo stesso sito* (`http://10.42.0.1`), quindi può leggere ciò che il vero ha lasciato nel telefono
  e lasciare in cache pagine e script che poi girano anche sulla rete vera, perfino dopo un
  ricaricamento (provato con Chrome). Per questo il piano famigliare non resta nel telefono. Restano
  solo numeri e codici dei propri annunci, che al massimo permettono di chiuderli. La soluzione vera
  è HTTPS con un certificato per ogni Campanile, che il telefono verifica da solo offline, più un
  rilevatore di reti gemelle (roadmap). Senza HTTPS i browser non offrono rimedi, perché i comandi
  per svuotare la cache di un sito funzionano solo in HTTPS.
- **Il registro si può leggere quasi tutto** cercando molti nomi (almeno 2 lettere). È il suo scopo,
  far trovare le persone, e la pagina lo dice a chi si registra.
- **I codici degli annunci viaggiano in chiaro.** Chi intercetta potrebbe chiudere un annuncio
  altrui. Danno limitato e reversibile.
- **I codici salvati sono SHA-256 senza "sale"**, ricavabili in pochi minuti da un database rubato.
  Il database lo legge solo il Campanile (nemmeno `kiwix-serve`, provato), quindi rubarlo vuol dire
  aver già preso il Campanile.
- **Le pagine `https://` aperte prima di collegarsi danno un errore di certificato**, perché il
  captive portal usa `http://`. È normale. Non va "accettato".

## La pagina di preparazione (solo portatile)

L'unica parte che scarica da internet ed esegue programmi, quindi la più chiusa.

- **Solo sul portatile** (`--setup`, lo accende `launch.py`). Sul Raspberry non è raggiungibile.
- **Solo da questo computer, con la password.** Mai dalla rete, nemmeno con `--admin-from-network`.
  Solo se il browser la chiama `localhost` o `127.0.0.1`, il che sventa il DNS rebinding verso
  127.0.0.1.
- **Nessun indirizzo arriva dalla pagina.** Tre operazioni fisse. La zona è un rettangolo di numeri
  controllato, al massimo 0,25 gradi quadrati.
- **Solo HTTPS**, anche nei reindirizzamenti verso i mirror. I certificati si verificano con quelli
  del sistema più l'elenco di Mozilla (certifi, fissato con SHA-256), perché il Python di python.org
  sul Mac non ne ha e a un Windows appena installato ne mancano alcuni.
- **Programmi verificati.** Lo SHA-256 di `pmtiles` e `kiwix-serve` è scritto nel codice. Si
  estraggono solo i file nominati, col loro nome semplice. Niente shell, argomenti in lista, e
  "Annulla" li ferma.
- **Wikipedia** deve corrispondere allo SHA-256 pubblicato da Kiwix, letto dal server di Kiwix e non
  dal mirror. Un file sbagliato si cancella, uno interrotto riprende.
- **Niente a metà.** I file `.partial` prendono il loro posto solo completi e controllati. Una mappa
  che non supera `pmtiles verify` non sostituisce mai quella buona.
- `kiwix-serve` parte con `--attachToProcess` (si spegne con il Campanile), `--blockexternal` e 16
  connessioni per dispositivo.
- **La posizione** la chiede il browser, con il consenso, solo per inquadrare la zona. Non arriva
  mai al Campanile. Senza, si cerca il comune o si sposta la mappa.
- **Su Windows un file aperto non si sostituisce** (misurato: errore 5). Una mappa nuova aspetta
  fino a 60 secondi che la ricerca o i telefoni lascino la vecchia. Kiwix si ferma prima che si
  cancelli la sua Wikipedia vecchia.

## La ricerca nella mappa

- **Senza internet.** I nomi vengono dalle mappe (vie, paesi, quartieri, ospedali, farmacie, acqua
  potabile...). Provato in un container senza rete e nel browser: nessuna richiesta esce dal
  Campanile.
- **Non si registra niente.**
- **Costa poco.** Due lettere possono corrispondere a decine di migliaia di nomi (Milano, 101.425
  nomi: 65 ms a ricerca), quindi se ne valutano al massimo 500. Una parola ripetuta conta una volta,
  al massimo 4 parole, prima la più rara. Una parola che compare in più di 30.000 nomi vale solo per
  i nomi che cominciano con ciò che si è scritto. Una lettera ripetuta quaranta volte, su 250.000
  nomi, è passata da 162 a 5 ms, e nessuna ricerca su una mappa così costa più di qualche
  millisecondo. 30 ricerche ogni 10 secondi per dispositivo, una alla volta. La successiva aspetta
  al massimo un quarto di secondo, poi riceve "riprova tra un attimo". Con 30 telefoni che cercano
  senza sosta, le ricerche degli altri richiedono 14 ms (provato).
- **I nomi restano testo** (`textContent`), quindi un nome ostile in una mappa non diventa codice.
- **Mappe ostili.** Una mappa che arriva da un altro Campanile può essere fatta per tenerlo occupato
  o riempirgli la memoria, quindi leggere qualunque file costa un lavoro limitato. Una directory ha
  al massimo un milione di voci e si legge una volta sola, anche sotto un'altra lunghezza. Voci,
  pezzi, byte, nomi e confronti hanno ciascuno un tetto, parecchie volte le mappe vere più grandi
  (il mondo intero, l'area metropolitana di Milano). Oltre il tetto la mappa si vede ma non si cerca
  finché il file non cambia, anche dopo un riavvio. L'indice in memoria ha un tetto di 24 parole per
  nome e 250.000 parole diverse. Letture o indici interrotti da un crollo si contano, e dopo tre il
  Campanile parte senza quella mappa. Tutte le mappe insieme: al massimo un milione di nomi.
  - Provato con 12 file ostili: quella mappa non si cerca, il resto funziona. Col codice di prima
    costavano un tempo che cresceva col file (uno stesso flusso letto 3.000 volte: 1,7 s) o tenevano
    1.000 paesi con lo stesso nome invece di 256. Le mappe vere danno gli stessi nomi.
  - Il fuzzing di 40.000 mappe alterate (`tests/fuzz_maps.py`) ha trovato sei tipi di difetto, il
    peggiore pochi byte che facevano riempire 2 GB di memoria. Tutti corretti, e ogni file rovinato
    ora finisce in un rifiuto pulito ([PROVE.md](PROVE.md)).

## Il navigatore

- **Senza internet.** Le strade vengono dai file delle mappe sul Campanile (incroci, sensi unici,
  sentieri, scale, ponti, gallerie). Non si scarica niente, i percorsi non si salvano né si
  registrano. Partenza e destinazione viaggiano in chiaro, leggibili da chi è nei paraggi con gli
  strumenti giusti.
- **Un tocco chiude un luogo, non una linea**: tutto ciò che sta entro 20 m dal punto e dalla sua
  strada, e un ponte o una galleria per tutta la larghezza (le linee della stessa struttura entro 50
  m, come l'altra carreggiata, i marciapiedi o l'altra canna). Le linee entro 60 m che restano
  aperte vengono indicate a chi gestisce, che può chiudere anche quelle. Misurato sull'area
  metropolitana di Torino, toccando a metà ogni tratto di ponte e di galleria di 50 m o più e
  chiedendo i percorsi per attraversarlo, in auto e a piedi, nei due sensi. Prima restavano
  attraversabili accanto 58 ponti su 294 e 22 gallerie su 168. Ora nessuno. Sul vero Ponte Regina
  Margherita un tocco chiudeva 2 delle sue 4 linee. Ora tutte e 4, e ogni percorso passa ad almeno
  94 m.
- **Cosa è interrotto lo decide solo il database**, modificato solo dalla pagina di gestione sul
  Campanile. Il navigatore non riceve elenchi da fuori. A ogni modifica rilegge il database, una
  lettura alla volta, così coincide sempre, anche con due modifiche insieme (provato con richieste
  simultanee). Rilegge dopo un riavvio, un numero di versione recupera le modifiche sfuggite, e una
  mappa con le interruzioni non ancora lette non dà percorsi. Al massimo 300 luoghi interrotti.
- **Le regole della strada dalla mappa.** Le auto rispettano sensi unici e verso delle rotonde,
  anche quando i bordi delle tessere tagliano una rotonda in archi (170 tratti di Torino erano a
  doppio senso). I pedoni evitano autostrade e gallerie delle strade principali. Autostrade e
  superstrade incontrano altre strade solo dove lo dice la mappa, mai a un incrocio indovinato.
- **Costa poco ed è equo.** Un percorso alla volta, con la stessa attesa di un quarto di secondo e
  lo stesso "riprova tra un attimo" della ricerca. Per dispositivo, 10 percorsi e 2 secondi di
  calcolo ogni 10 secondi. I percorsi oltre 5 secondi si fermano e chiedono punti più vicini.
  Misurato in un container con un telefono che chiede percorsi lunghi senza sosta. Su Torino con un
  quarto di processore, più o meno un Raspberry, i rifiuti "occupato" dell'altro telefono sono scesi
  da 9 su 15 a 1 su 19, e su una mappa ai tetti qui sotto da 16 su 17 a 5 su 20. Sul portatile delle
  prove l'area metropolitana di Torino (129.326 tratti, 88.091 incroci) dà un percorso in auto di
  20-30 km da un capo all'altro in 30-118 ms. Su un Raspberry è più lento, non ancora misurato.
- **Mappe ostili**, come per la ricerca. Le strade vengono solo dai pezzi più dettagliati: al
  massimo 4.000 (una zona della pagina di preparazione ne ha circa 2.900), 4 milioni di punti, e un
  tetto di lavoro (segmenti nelle celle, coppie di segmenti confrontate, per pezzo e per mappa) di
  circa 12 volte l'area metropolitana di Torino. I pezzi di grandezza insolita si rifiutano. File da
  poche centinaia di byte a 11 KB che impilavano migliaia di strade in un punto, o stendevano una
  strada su un pezzo enorme, facevano durare la costruzione minuti o esaurivano la memoria. Ora
  ognuno si rifiuta in meno di un decimo di secondo, e le mappe vere si costruiscono come prima
  (area metropolitana di Torino: 3,2 secondi, 16 MiB). Le costruzioni interrotte da un crollo si
  contano, e dopo tre la mappa si abbandona finché il file non cambia (provato uccidendo davvero il
  processo).
- **La mappa giusta** si sceglie da dove sono davvero le sue strade, non dalla sua intestazione. Se
  sono troppo lontane da un punto si prova la successiva, così una mappa minuscola che dichiara il
  mondo intero non si prende più tutti i percorsi.
- **Al telefono si dice** la data dei dati e, se il punto era a 40 m o più da una strada, di quanto
  si sono spostati partenza o arrivo.
- **Le interruzioni sono pubbliche**, in rosso su ogni telefono con la nota di chi gestisce. Va
  scritto solo ciò che tutti possono leggere.
- **Quello che arriva si controlla.** Solo numeri finiti e nell'intervallo (NaN, Infinity o un
  numero di 400 cifre si rifiutano come non validi). Una nota nella forma sbagliata riceve un
  rifiuto chiaro, non un errore interno (provato).
- **Cosa non può sapere.** Modifiche successive, interruzioni che nessuno ha segnato, e i divieti di
  svolta, che i file delle mappe non hanno. Su Torino 60 degli 8.415 tratti a senso unico cambiano
  verso fra due livelli di dettaglio, e vince il più dettagliato. La pagina mostra la data dei dati
  e dice di seguire i cartelli e le strade aperte.

## Copie su chiavetta

Un Campanile pronto può accenderne altri: la pagina di preparazione copia tutto su una chiavetta.
Così viaggiano i programmi, quindi le regole sono strette.

- **I programmi viaggiano solo su chiavetta, consegnata di persona**, mai via Wi-Fi, dove un
  computer nuovo non distingue il Campanile vero da uno falso. La guida lo dice.
- **Un Campanile già installato si aggiorna solo a una versione più nuova firmata da
  CarrotStudio**, controllata sulla copia che ha fatto, mai sulla chiavetta: esattamente i file
  firmati, né uno in più né uno in meno, mai una versione più vecchia. Le chiavi di firma restano
  offline. La prima volta una chiavetta vale ancora come una chiave di casa: chi avvia un
  Campanile direttamente da una chiavetta esegue quello che c'è sopra.
- **Un elenco chiuso**: programma, mappe, Wikipedia, chiavi pubbliche degli avvisi firmati, Kiwix,
  Python. Mai il database (nomi, annunci, contatti) né la password. Nessuna cartella si copia così
  com'è.
- **Una chiavetta ostile non può infilare niente.** Una cartella Campanile già presente si usa solo
  se contiene esattamente ciò che la copia scrive. Un modulo, una libreria accanto a `kiwix-serve`,
  un installatore, un database o una password nota infilati lì verrebbero usati da chi avvia la
  copia. Qualunque altra cosa ferma la copia senza toccare niente (provati 10 tipi, compreso
  l'attacco della nostra seconda revisione da attaccante, che faceva girare il suo codice dalla
  copia e ora viene rifiutato). Si tolgono solo gli avanzi: copie interrotte, la cache di Python, i
  file che aggiunge un Mac.
- **Nessun collegamento si segue o si accetta.** Una "mappa" che punta al database resta fuori
  (provato). Le cartelle si creano una per una, e ogni file, anche il leggimi e l'elenco, si scrive
  a parte e prende il suo posto solo completo. Un collegamento sulla chiavetta deviava due scritture
  e sovrascriveva il database in uso (dalla revisione). Ora la copia si ferma. Togliendo ciascuna
  difesa, il suo test fallisce.
- **Python e i comandi vengono dal sistema, mai dalla cartella.** `install.sh` e gli script di
  preparazione usano `python3 -I` (un `secrets.py` accanto non viene importato, provato, e un test
  controlla tutti gli script). Il servizio del Raspberry ignora i pacchetti nella sua cartella
  personale (`-s`). Il file di avvio per Windows non cerca comandi nella propria cartella
  (`NoDefaultCurrentDirectoryInExePath`). Su Windows un `py.bat` accanto parte senza quella riga,
  non con essa (provato).
- **Il Python sulla chiavetta è quello ufficiale.** Impronte fissate, verificate con la firma
  Sigstore di python.org. Windows controlla la firma della Python Software Foundation (provato:
  valida), il Mac quella di Apple.
- **Una copia incompleta si riconosce.** L'elenco delle impronte si scrive per ultimo, e all'avvio
  un file del programma mancante o di dimensione sbagliata viene segnalato.

## Mappe e Wikipedia via Wi-Fi fra Campanili

Un Campanile può passare mappe e Wikipedia a un altro sulla stessa rete, senza internet.

- **Solo dati**: mappe e Wikipedia dalle loro cartelle, per nome. Mai programmi, il database o
  altro.
- **Un codice di 80 bit**, mostrato solo nella pagina di gestione (dal Campanile stesso), si legge
  di persona. Firma l'elenco dei file e i loro SHA-256 (HMAC-SHA256), così l'elenco di un falso con
  lo stesso nome viene rifiutato e un file sostituito per strada non corrisponde all'impronta. Il
  codice non passa mai sulla rete.
- **Chi riceve controlla** nomi (niente `../`), dimensioni, impronte, doppioni. Niente
  reindirizzamenti né proxy. Non sovrascrive mai i propri file (il nuovo prende `-2`). L'indirizzo
  dev'essere della rete locale.
- **Per scaricare serve un permesso** derivato dal codice, valido solo dall'indirizzo di chi riceve.
  I telefoni non possono consumare la banda con file da un GB, e chi lo intercetta non può usarlo da
  altrove per occupare gli scaricamenti (attraverso nginx: 206 per chi riceve, 404 da altri
  indirizzi; l'attacco della revisione ora fallisce e chi riceve ha la sua mappa). 2 scaricamenti
  insieme, 2 MB/s ciascuno. La condivisione si ferma dopo due ore, o con un clic.
- **Sul Raspberry** i file passano da nginx senza buffer su disco (misurato: la sua cartella resta
  uguale), con i soliti limiti per telefono.
- **Provato con impostori veri** (un altro codice, file sostituiti, un reindirizzamento al Campanile
  vero, il codice giusto con nomi `../`). Tutti fermati. Togliendo ciascuna difesa, il suo test
  fallisce.

## Windows: il firewall

Se alla domanda di Windows si preme «Annulla», Windows blocca i telefoni e non lo chiede più. Il
Campanile se ne accorge (leggere le regole non richiede l'amministratore) e propone di sistemarlo.

- **Solo con INVIO** della persona davanti allo schermo, con il permesso che Windows chiede.
- **Apre solo ciò che usa.** Toglie le regole «Blocca» del suo `python.exe` e del suo
  `kiwix-serve.exe` e aggiunge permessi solo TCP sulle loro porte (8080, 8081), con un nome
  riconoscibile («Campanile - python.exe - TCP 8080»). Sulle altre porte Windows chiede come di
  norma.
- **Il percorso del programma entra nel comando da amministratore solo in base64.** PowerShell
  tratta gli apostrofi tipografici (’) come apici, quindi raddoppiare gli apici non bastava
  (provato: un comando nascosto in un nome di cartella veniva eseguito). PowerShell si chiama col
  percorso completo di sistema, mai dalla cartella corrente.
- **Provato a ogni modifica** sul Windows della CI: regole di blocco per percorsi ostili,
  riparazione, nessun comando eseguito.

## Connessioni: chiudere bene

- A posti pieni si chiudono le connessioni ferme da più tempo (il browser le riapre) e chi arriva
  aspetta in coda invece di essere rifiutato. Su Windows vuol dire chiudere il socket, perché lì
  `shutdown()` non sveglia chi sta leggendo (misurato).
- Se nessuna è ferma, cede un posto il dispositivo che ne tiene di più, a partire dalla risposta più
  vecchia. Chi scarica lentissimo su molte connessioni scalza sé stesso, non i telefoni (provato:
  prima 0 richieste su 23, dopo 90 su 90).
- Una risposta data prima di aver letto tutta la richiesta si chiude in due tempi (RFC 9112, 9.6),
  con limiti di 2 secondi e 64 KB perché non occupi un posto.

## Raspberry Pi: chi parla con chi

```
telefono ──porta 80────▶ nginx ──127.0.0.1:8080──▶ Campanile (Python)
telefono ──porta 8081──▶ nginx ──127.0.0.1:8082──▶ Kiwix (Wikipedia)
         (firewall sull'hotspot: solo DHCP, DNS, 80 e 8081; telefoni isolati tra loro)
```

I punti delicati sono i **collegamenti** tra i pezzi, e ognuno ha una prova.

- **L'indirizzo del telefono.** Dietro nginx, Python vede `127.0.0.1`. nginx **sovrascrive**
  `X-Real-IP` con l'indirizzo vero. Python se ne fida solo se viene da nginx sulla stessa macchina,
  e se manca considera la richiesta **non locale**. Provato: un telefono che finge
  `X-Real-IP: 127.0.0.1` o `X-Forwarded-For` resta fuori dalla gestione.
- **Dove finisce una richiesta.** nginx e Python devono essere d'accordo, altrimenti il resto di una
  richiesta diventa una nuova scritta dal telefono. nginx respinge le forme ambigue classiche
  (provato) e manda una richiesta per connessione. Python non tiene mai aperta una connessione con
  un corpo non letto.
- **Le porte interne** 8080 e 8082 ascoltano solo su `127.0.0.1` (provato che dalla rete non si
  raggiungono).
- **Wikipedia su un'origine separata** (porta 8081). Un difetto in Kiwix non può leggere ciò che le
  pagine del Campanile tengono nel browser (il piano famigliare aperto) né usare le API del
  Campanile a nome del telefono.
- **Firewall sull'hotspot.** Dai telefoni passano solo DHCP, DNS, 80 e 8081. Nessun altro servizio
  (SSH compreso), nessun inoltro. Provato da un secondo dispositivo, con la controprova a firewall
  spento.
- **Telefoni isolati** (`ap-isolation`), così nessuno si finge router o DNS per gli altri. Provato
  con NetworkManager 1.42 e 1.52. Che il chip Wi-Fi del Raspberry lo rispetti va verificato sul
  campo.
- **nginx non registra gli accessi.** Nessun indirizzo dei telefoni su disco, e un'inondazione non
  riempie la scheda SD.
- **Limiti per telefono in nginx**: 16 connessioni, 10 secondi per la richiesta, 20 richieste al
  secondo alle API. Quelli sulle pubblicazioni restano nel Campanile, per indirizzo vero. Provato
  con 300 connessioni lente: gli altri dispositivi continuano a funzionare.
- **Le mappe.** Anche nginx serve solo file `.pmtiles` dalla cartella mappe. La cartella dati si
  attraversa ma non si elenca, e il database lo legge solo il servizio.
- **I tipi di file.** `.mjs` (il codice della mappa) e i font sono dichiarati, perché Debian non li
  conosce e il browser li rifiuterebbe.
- **Kiwix 3.7** legge le interfacce di rete all'avvio, quindi la sua gabbia systemd permette quel
  solo tipo di socket in più (`AF_NETLINK`). Senza, su Debian 13 non partiva.

## Raspberry Pi: il resto

- Il servizio gira come utente `campanile`, senza privilegi, con le protezioni di systemd
  (`ProtectSystem=strict`, `NoNewPrivileges`, `PrivateTmp`, filesystem in sola lettura tranne
  `/var/lib/campanile`, solo il permesso di aprire la porta 80).
- `/opt/campanile` appartiene a root. Il servizio non può modificarlo.
- La password di gestione, `/etc/campanile/password`, la leggono solo root e il servizio.
- Kiwix ha le stesse restrizioni più `--blockexternal`, che blocca i link verso internet.
- `scripts/prepare.sh` fissa le versioni delle librerie e ne verifica lo SHA-256. Font e icone
  vengono da un commit git fissato.

Per segnalare una vulnerabilità: [SECURITY.md](../SECURITY.md).
