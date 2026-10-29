# I nostri limiti, detti onestamente

English version: [LIMITS.md](LIMITS.md).

Il Campanile 0.1 è sperimentale. Qui trovi cosa non abbiamo dimostrato e cosa non sa fare. Se manca
un limite, diccelo e lo aggiungiamo.

## Se domani internet sparisce

**Cosa continua a funzionare, se è stato preparato prima**

- Sulla Wi-Fi del Campanile: avvisi ufficiali, bacheca, "sto bene" e piano familiare. Nessuna di
  queste cose ha bisogno di internet.
- Mappe, ricerca e navigatore, per le mappe già scaricate.
- Le voci mediche di Wikipedia, se scaricate con il programma che le serve (sul portatile, il
  pulsante *Medicina offline* della pagina di preparazione).
- Gli avvisi firmati, se è stata aggiunta la chiave pubblica dell'autorità.
- Altri Campanili. Una chiavetta fatta con *Prepara per tutti i computer* parte su un computer
  senza niente installato. Mappe e Wikipedia passano anche via Wi-Fi fra Campanili.

**Cosa non funziona, o ha bisogno d'altro**

- **Senza preparazione, quasi niente.** Il pacchetto non contiene mappe, Wikipedia né Python.
  Senza internet, l'unica strada è una chiavetta preparata da qualcuno.
- **Servono corrente e una rete Wi-Fi.** Il portatile ha bisogno di un router acceso (internet non
  serve) o dell'hotspot di un telefono. Nel nostro test sul campo un telefono Android (TCL 40 SE)
  l'ha creato con i dati spenti, per al massimo 8 apparecchi. Un iPhone no. Il Raspberry crea
  la sua rete da solo, provato solo su radio virtuali. Quanto dura una batteria è una stima.
- **Il cartello.** Sul portatile l'indirizzo cambia con la rete, quindi stampa il cartello, o
  ricopia il suo indirizzo, quando la rete del giorno è pronta. L'indirizzo del Raspberry non
  cambia mai.
- **Niente oltre poche decine di metri.** Nessun messaggio ai parenti lontani, nessuna chiamata
  (il 112 ha bisogno della rete telefonica). I Campanili non si scambiano ancora annunci né nomi
  di "sto bene". Ogni quartiere è un'isola.
- **Niente di nuovo da fuori.** Le mappe invecchiano dal giorno in cui sono state scaricate.
  Correzioni e lingue nuove arrivano solo con una chiavetta, perché via Wi-Fi passano solo mappe e
  Wikipedia.
- **L'orologio del Raspberry** non ha batteria. Senza internet riparte dall'ora in cui è stato
  spento. I telefoni mostrano la propria ora e la pagina di gestione può correggere quella del
  Campanile. Finché nessuno lo fa, gli avvisi firmati e la cancellazione degli annunci vecchi
  seguono un orologio indietro.
- **Telefoni su una Wi-Fi senza internet.** Nel nostro test sul campo due iPhone con i dati spenti
  hanno scritto "Nessuna connessione a Internet" e sono rimasti collegati. Altri telefoni, o i
  dati lasciati accesi, possono comportarsi diversamente. Visto una volta.

## Non provato sul campo

- **Ancora nessun Raspberry Pi vero.** Installazione, nginx, systemd e firewall sono girati in
  container su un Mac, compresa la vera Raspberry Pi OS. Hotspot, portale automatico, firewall e
  telefoni tenuti separati sono girati su radio Wi-Fi virtuali. Mai sul chip Wi-Fi di un
  Raspberry, né con telefoni veri.
- **L'aggiornamento da chiavetta** è girato da capo a fondo su un Mac, dalla pagina di
  preparazione con un disco FAT32 che il Mac prende per una chiavetta, e su Windows 11 ARM in una
  macchina virtuale, con il vero doppio clic (compreso un file bloccato da Windows). Mai con una
  chiavetta vera in mano a una persona. Sul Raspberry è girata solo la parte che controlla:
  l'installatore era una controfigura.
- **Nessuna folla di telefoni veri.** Ne abbiamo simulati fino a 1.000, in container su un solo Mac
  e su una rete virtuale. Una vera radio Wi-Fi ne regge molti meno insieme.
- **Un test sul campo, quattro apparecchi.** Il 26 ottobre 2026, senza internet: un Mac, due iPhone
  e un telefono Android che faceva la Wi-Fi. La bacheca ha funzionato tra i due iPhone, e un
  annuncio è comparso subito sull'altro. Un test, una casa, un modello di Android.
- **Ancora nessun test delle famiglie.** La nostra promessa principale, abbastanza semplice per
  chiunque, non è ancora stata provata con persone non tecniche.
- **Windows** è girato su Windows 11 per ARM in una macchina virtuale, non su un normale PC Intel o
  AMD, e con la richiesta Sì/No del Controllo dell'account utente spenta.
- **Gli stacchi di corrente, provati a metà.** Il database ha retto 30 uccisioni brutali del
  processo, senza perdere niente di ciò che era stato confermato a un telefono. Un vero stacco,
  che perde anche ciò che non era ancora scritto, e le schede SD che non scrivono quello che hanno
  promesso: mai provati. Quanto dura una batteria: mai misurato.

## Misurato, ma solo qui

- **Tutti i tempi e i consumi di memoria** vengono da un solo portatile (Apple M3, 16 GB) o da
  container sopra di lui. Un Raspberry è parecchie volte più lento, quindi nessuno di quei numeri
  vale lì finché non si misura.
- **I percorsi del navigatore** sono stati controllati sulla mappa di Torino e nei test, non fatti
  a piedi o in auto.
- **L'accessibilità è stata controllata solo dalla macchina** (WCAG 2.2 AA, zoom al 200%), non
  ancora da chi usa un lettore di schermo o fa fatica a leggere.

## Sicurezza: cosa non è stato fatto

- **Nessun audit esterno né test di penetrazione professionale.** Ogni revisione finora è stata
  nostra, fatta da attaccanti: ogni difetto riprodotto, corretto e coperto da un test che fallisce
  sul codice di prima.
- **Il server web è nostro, e nessuno l'ha rivisto da fuori.** I telefoni parlano con codice
  scritto da noi sopra `http.server` di Python (con nginx davanti sul Raspberry): è la parte che più
  merita uno sguardo esterno.
- **Il lettore delle mappe è passato sotto un fuzzer solo nostro, per qualche ora.**
  `tests/fuzz_maps.py` dà alla ricerca e al navigatore pezzi di mappe vere alterati come farebbe
  un file ostile. 40.000 casi su un processore hanno trovato sei tipi di difetto, tutti corretti.
  Il peggiore, pochi byte, faceva riempire al lettore 2 GB di memoria. Una seconda corsa di 15.000
  casi sul codice corretto non ne ha trovato nessuno. È un fuzzer a mutazioni scritto da noi, non
  guidato dalla copertura come AFL o Atheris, e il disegno della mappa nel telefono (MapLibre) non
  l'abbiamo mai passato sotto un fuzzer. Ci sono passate anche le richieste di rete (250.000) e la
  verifica delle firme (200.000). Un buon punto da cui cominciare.
- **Gli strumenti trovano schemi noti, non ogni difetto.** Bandit, Semgrep e axe-core non hanno
  trovato più niente da correggere. Non è una prova. CodeQL gira a ogni modifica. Dei suoi primi
  6 allarmi, uno ha portato a una correzione (password più lunghe per chi gestisce un Campanile);
  gli altri 5 li abbiamo letti nel codice e chiusi, ognuno con il motivo.
- **Il codice di altri** (Python, nginx, MapLibre, PMTiles, kiwix-serve) ha versioni fissate e
  impronte controllate, e sul Raspberry kiwix-serve gira isolato. Non l'abbiamo revisionato.

## Per come è fatto, per ora

- **Gli allarmi CAP si caricano a mano** da un file, non si ricevono. Se e come un Campanile possa
  usare il canale di IT-alert per altri sistemi non l'abbiamo verificato. Il lettore segue il CAP
  1.1 e 1.2, a cui i profili italiani aggiungono solo regole. Provato sugli otto messaggi
  pubblicati da IT-alert, tutti test pubblici (rifiutati come esercitazioni, come deve essere, e
  letti per intero una volta segnati come reali), e su cinque allarmi veri del Servizio
  Meteorologico dell'Aeronautica Militare. Mai su un allarme vero di IT-alert, perché non ne è
  stato pubblicato nessuno. La firma dell'allarme non viene controllata. Il certificato pubblicato
  da IT-alert verifica i suoi messaggi del 2023 ma è scaduto a giugno 2024 (vedi la roadmap).
- **Wi-Fi aperta, niente cifratura.** Chi è nei paraggi può leggere annunci, nomi e percorsi
  chiesti.
- **Un falso "Campanile" non si distingue**, e può lasciare le sue pagine nella cache di un
  telefono (provato). La cura è HTTPS per ogni Campanile, nella [roadmap](../ROADMAP.md#italiano).
  Gli avvisi firmati li verifica il Campanile, non il telefono.
- **Nessuno è verificato.** Chiunque può scrivere qualunque annuncio, e qualunque nome in "sto
  bene".
- **I limiti per dispositivo si possono aggirare** con molte antenne Wi-Fi, o con un indirizzo del
  telefono che cambia di continuo. Il freno d'emergenza mette in attesa quegli annunci, ma una
  piena ostinata costa comunque lavoro a chi gestisce. In più ripartono ogni giorno: l'etichetta
  del telefono cambia ogni giorno, perché i giorni non si possano collegare. Un telefono può
  tenere aperti 5 annunci e registrare 10 nomi al giorno.
- **La password principale può tutto**, anche aggiungere e togliere chi gestisce il Campanile. Gli
  altri entrano con una password loro, e il registro dice chi ha fatto cosa (le ultime 1.000
  azioni). Chi usa la password principale compare solo come «Password principale».
- **Chi ha in mano il dispositivo ha tutto.** Database e password di gestione non sono cifrati sul
  disco. Ciò che si cancella, e gli annunci chiusi, vengono sovrascritti invece che lasciati nel
  file (misurato: prima, un numero di telefono cancellato si leggeva ancora). Però le schede SD e
  gli SSD spostano le scritture dentro il chip, e lì una copia vecchia può sopravvivere: solo un
  disco cifrato chiuderebbe il problema.
- **Nessun aggiornamento automatico.** Una correzione arriva a un Campanile solo quando qualcuno la
  porta, su una chiavetta controllata con la firma di CarrotStudio, o la installa.
- **Annunci e nomi si cancellano da soli**: gli annunci dopo 14 giorni, i nomi di "sto bene" dopo
  60. Chi gestisce può cambiarli all'avvio, o tenerli per sempre.
- **Il navigatore** non sa dove si trova il telefono né conosce i divieti di svolta, stima i tempi,
  è aggiornato quanto la sua mappa e conosce solo le strade interrotte che qualcuno ha segnato. Si
  fida dei sensi unici della mappa, ma su quella di Torino 60 su 8.415 hanno verso diverso fra due
  livelli di dettaglio.
- **Poche decine di metri di portata.** Non è un sistema di emergenza certificato. Non sostituisce
  il 112.

## Problemi tecnici ancora da risolvere

Più o meno in ordine di importanza:

1. **Fiducia senza internet**: HTTPS per ogni Campanile, certificati rilasciati prima
   dell'emergenza, avvisi verificati sul telefono. Darebbe anche al navigatore la posizione del
   telefono.
2. **Prove su apparecchi veri**: tutto ciò che è in "Non provato sul campo", più tempi e memoria
   su un Raspberry (lo Zero 2 W ha 512 MB).
3. **Più modelli di telefono su una Wi-Fi senza internet**, e gli Android come ospiti.
4. **Da isole a rete**: avvisi, annunci e nomi di "sto bene" che passano fra Campanili (al
   contatto, con una chiavetta, via radio LoRa) senza spargere una piena di messaggi o un nome
   falso. Un avviso firmato si verifica già da solo ovunque, ma ancora niente lo trasporta.
   Un'idea: i telefoni che passano da un Campanile all'altro portano con sé gli avvisi, pubblicati
   solo se la firma è valida, senza app, radio o internet. Un pacchetto radio porta poche
   centinaia di byte e un avviso può superare il kilobyte, quindi la radio va bene per gli avvisi
   brevi.
5. **Un orologio con batteria** per il Raspberry (il Pi 5 ha il connettore), così nessuno deve
   correggerlo dopo un lungo blackout.
6. **Un fuzzer guidato dalla copertura** (AFL, Atheris) sul lettore delle mappe e sul costruttore
   delle strade, e un audit di sicurezza esterno.
7. **Il navigatore**: i divieti di svolta, che non ci sono nei file delle mappe che usiamo, e una
   posizione che ti segue, che ha bisogno di HTTPS.

## Aiutaci a chiuderli

Ogni riga qui sopra è un modo per contribuire. Come provare le parti che noi non abbiamo potuto:
[PROVE.md](PROVE.md). Come segnalare un difetto in privato: [SECURITY.md](../SECURITY.md).
