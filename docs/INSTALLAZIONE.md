<p align="right"><a href="SETUP.md">English</a> · <b>Italiano</b></p>

# Installare il Campanile

Due modi per farlo funzionare: su un portatile, o su un [Raspberry Pi](#raspberry-pi) come
stazione fissa.

## Su un portatile (il più semplice)

Serve **Python 3**, gratuito su [python.org](https://www.python.org/downloads/). Su Windows spunta
*"Add python.exe to PATH"*. Sul Mac vanno bene anche gli strumenti per sviluppatori che propone.
Se Python manca, il file di avvio dice cosa fare.

1. Scarica il **pacchetto pronto** dalla pagina [Releases](https://github.com/Carrotstudiosoftwarehouse/campanile/releases) e scompattalo.
2. Doppio clic su **Avvia Campanile (Mac)** o **Avvia Campanile (Windows)**.
3. La prima volta si apre la **pagina di preparazione**. Con internet, scarica la mappa e le voci
   mediche, un clic ciascuna.
4. Stampa il **cartello** (il suo codice QR ha l'indirizzo) e la
   [guida](../campanile/web/guide.html) di una pagina per chi lo gestisce.
5. Lascia aperta la finestra nera. Chiudendola il Campanile si spegne.

Tutti si collegano **alla stessa Wi-Fi** del portatile. Senza internet, attiva l'**hotspot** di un
telefono Android (in genere va anche senza SIM o senza dati) e collega lì il portatile e tutti
gli altri. *Provalo prima con due telefoni. Nella nostra prova l'iPhone voleva i dati accesi,
l'Android no. Alcuni operatori o modelli lo bloccano.*

> **Primo avvio.** Quando Mac o Windows chiedono se Python può accettare connessioni dalla rete,
> rispondi **Consenti**. Il Mac lo chiede di nuovo per **kiwix-serve** (Wikipedia offline).
> **Consenti** anche a lui, o i telefoni non aprono Wikipedia.
> - Premuto *Rifiuta* su un Mac: *Impostazioni di Sistema → Rete → Firewall → Opzioni*.
> - Premuto *Annulla* su Windows: dopo un minuto la finestra nera lo dice, e Invio lo sistema.
> - Il Mac non apre `Avvia Campanile (Mac).command`: *Impostazioni di Sistema → Privacy e sicurezza → Apri comunque*.

## Prepararlo prima, quando internet c'è ancora

**Sul portatile**, la pagina di preparazione (`http://localhost:8080/setup.html`, si apre da sola
la prima volta) scarica la mappa del mondo, la tua zona con ogni dettaglio (inquadrata dove sei se
il browser può dirlo, oppure cerchi il tuo comune) e le voci mediche di Wikipedia in italiano,
inglese o tutte e due. Gli scaricamenti riprendono se interrotti e sono controllati con SHA-256
(fissati nel codice per i programmi, quello di Kiwix per Wikipedia).

<p align="center">
  <img src="immagini/setup.png" width="600" alt="Pagina di preparazione: la zona da scaricare, inquadrata dove si trova il computer">
</p>

**Dal terminale, o per il Raspberry**, nella cartella del Campanile, con internet, una volta:

```bash
scripts/prepare.sh                        # librerie (già incluse nel pacchetto pronto)
scripts/download-map.sh custom area OVEST,SUD,EST,NORD   # la tua zona, vedi sotto
scripts/download-map.sh world             # il mondo intero, ~190 MB
scripts/download-wikipedia.sh medicine it   # voci mediche in italiano, ~260 MB
```

### La tua zona, in dettaglio

La ricerca delle vie, l'ospedale, la farmacia o l'acqua più vicini e il navigatore funzionano solo
con una mappa del tuo comune e dei dintorni, fino a circa 30 km di lato. Sulla mappa del mondo e
su quelle dell'Italia la ricerca trova solo i paesi.

Per avere i suoi quattro numeri apri [openstreetmap.org](https://www.openstreetmap.org), cerca il
tuo comune e ingrandisci finché lo schermo mostra lui e i dintorni. Premi **Esporta** in alto:
compaiono quattro numeri, messi come i lati dello schermo. A sinistra c'è l'ovest, a destra l'est,
in alto il nord e in basso il sud. Torino centro è `7.64,45.04,7.71,45.09`, circa 7 MB. Un quadrato
di 30 km attorno a Torino pesa circa 23 MB.

| Mappe (`download-map.sh`) | Dimensione | Dettaglio |
|---|---|---|
| `custom NOME OVEST,SUD,EST,NORD` | dipende | la tua zona, ogni via: ricerca e navigatore |
| `world` | ~190 MB | stati, città e strade principali di tutto il mondo |
| `italy-light` | ~580 MB | strade di tutta Italia, da guardare |
| `italy` | ~4,5 GB | ogni strada ed edificio, da guardare: troppo grande per ricerca e navigatore |

| Wikipedia (`download-wikipedia.sh`) | Dimensione in italiano |
|---|---|
| `medicine-light` (senza immagini) | ~100 MB |
| `medicine` | ~260 MB |
| `essential` (voci più lette, senza immagini) | ~900 MB |
| `full` (senza immagini) | ~8,4 GB |
| `full-images` | ~30 GB |

Dimensioni misurate tra il 22 e il 24 ottobre 2026. La parola dopo il pacchetto è la lingua: `it`
(se non la scrivi), `en`, `de`, `fr`, `uk`... L'inglese pesa di più: `medicine-light en` è circa
1 GB, come nella pagina di preparazione. Wikipedia parte da sola. Sul portatile, prima premi una volta un pulsante
di *Medicina offline* nella pagina di preparazione, per aggiungere il programma che la serve.

La ricerca nella mappa legge ogni mappa una volta sola, in sottofondo, e mette il risultato in
`data/places/`. Trova vie, luoghi e punti utili (ospedali, farmacie, acqua potabile...) nella tua
zona, stati e città nella mappa del mondo.

**Poi** compila il piano familiare e fai una prova con un paio di telefoni. Stampa il cartello in
anticipo solo per il Raspberry, il cui indirizzo non cambia mai. Quello del portatile cambia con la
rete, quindi stampa il suo cartello (o ricopia a mano l'indirizzo) quando la rete del giorno è
pronta.

## Altri Campanili, senza internet

Nella pagina di preparazione, *Altri Campanili*:

1. **Prepara per tutti i computer** (con internet, una volta, circa 250 MB) scarica il programma
   di Wikipedia per Windows, Mac e Linux, e gli installatori ufficiali di Python.
2. Infila una chiavetta USB e premi **Copia sulla chiavetta** (programma, mappe e Wikipedia).

Sulla chiavetta, doppio clic su *Avvia Campanile*. Non servono internet né installazioni. Se manca
Python, la finestra indica il suo installatore sulla chiavetta.

- **La chiavetta si dà di persona.** Mai installare un programma da una rete Wi-Fi: chiunque può
  chiamarne una «Campanile».
- **Mai sulla chiavetta:** il database (nomi, annunci, contatti), la password di gestione, niente
  che non sia in un elenco fisso.
- **Niente passeggeri nascosti.** Una cartella Campanile già sulla chiavetta si usa solo se
  contiene soltanto i file del Campanile. Qualunque altra cosa ferma la copia, senza toccare
  niente, e i collegamenti non si seguono. Provato con tutti i modi che conosciamo per nascondere
  lì un programma.
- Sul Raspberry, dal terminale, con la cartella della chiavetta al posto di `/media/usb`:
  `sudo python3 /opt/campanile/campanile/copying.py /media/usb --data /var/lib/campanile --keys /etc/campanile/trusted-keys.json`.
  Quella chiavetta porta programma, mappe e Wikipedia, non gli installatori di Python né il
  programma di Wikipedia per i portatili: quelli vengono da *Prepara per tutti i computer* su un
  portatile.

**Aggiornare da una chiavetta.** Nella pagina di preparazione infila una chiavetta con un
Campanile più nuovo e premi **Aggiorna da questa chiavetta**. Viene copiato accanto a questo
Campanile e controllato lì: passa solo una versione più nuova firmata da CarrotStudio. Chiudi la
finestra nera e riapri il Campanile: prima di partire ricontrolla, poi la versione nuova diventa una
cartella sua, "Campanile 0.2.0", e ci si spostano mappe, Wikipedia e annunci. Il vecchio doppio
clic continua a funzionare. Sul Raspberry: `sudo python3 /opt/campanile/campanile/update.py
/media/UTENTE/CHIAVETTA` controlla la chiavetta allo stesso modo, poi lancia l'installatore della
versione nuova con le scelte dell'ultima volta.

**Mappe e Wikipedia via Wi-Fi.** Nella pagina di gestione, *Condividi con un altro Campanile*
mostra un indirizzo e un codice. Un altro Campanile si collega a questa Wi-Fi e li scrive nella
sua pagina di preparazione. Arrivano mappe e Wikipedia, mai programmi. L'elenco dei file è firmato
con il codice, quindi un Campanile finto con lo stesso nome di rete ma senza codice viene
rifiutato. Gli scaricamenti vanno piano, così i telefoni non restano senza Wi-Fi, e la
condivisione si ferma dopo due ore.

## Tenerlo acceso

> **ore di autonomia ≈ capacità della batteria in Wh × 0,8 ÷ consumo in watt**
> (mAh di una power bank × 3,7 ÷ 1000 = Wh)

Una power bank da 20.000 mAh vale circa 74 Wh. Se consuma 4 W, un Raspberry va avanti
74 × 0,8 ÷ 4 ≈ **15 ore**. Il consumo dipende dal modello e da quanti si collegano, quindi
**misuralo** con un misuratore USB da pochi euro. Un pannello solare pieghevole da 20-30 W con
uscita USB può ricaricare la power bank di giorno. Sul portatile valgono le stesse regole, con lo
schermo meno luminoso.

## Raspberry Pi

Dovrebbe funzionare su un Raspberry Pi 3B+, 4, 5 o Zero 2 W. Provato in container con Raspberry
Pi OS e su radio Wi-Fi virtuali, non ancora su una scheda vera. Crea la rete Wi-Fi aperta
**"Campanile"**: i telefoni dovrebbero aprire la pagina da soli (non ancora provato con telefoni
veri), e la apre anche il codice QR del cartello. Può andare avanti con una power bank, per quanto
non l'abbiamo ancora misurato.

Serve **Raspberry Pi OS a 64 bit**, Lite o con desktop (Bookworm o più recente: a 32 bit la mappa
non si può scaricare dal Pi), una scheda da 16 GB (le righe qui sotto occupano circa 1 GB), con
il Wi-Fi integrato, collegato a internet **via cavo**: l'ultimo
passo trasforma il Wi-Fi nell'hotspot, e una sessione SSH via Wi-Fi lì cadrebbe. Lo Zero 2 W non ha
la porta di rete: usa tastiera e schermo, oppure un adattatore di rete USB.

Prima trova [i quattro numeri della tua zona](#la-tua-zona-in-dettaglio) e scrivili al posto di
`OVEST,SUD,EST,NORD`; se non sei in Italia, cambia anche `IT` con le due lettere del tuo paese.
Poi incolla tutto il blocco, graffe comprese: fanno leggere alla shell ogni riga prima di
eseguirne una, così non se ne perde nessuna.

```bash
{
sudo apt update && sudo apt install -y git
[ -d $HOME/campanile ] || git clone https://github.com/Carrotstudiosoftwarehouse/campanile.git $HOME/campanile
cd $HOME/campanile && git pull
scripts/download-map.sh custom area OVEST,SUD,EST,NORD   # la tua zona
scripts/download-map.sh world             # facoltativo, ~190 MB
scripts/download-wikipedia.sh medicine it   # facoltativo, in italiano, ~260 MB
sudo raspberry/install.sh --country IT    # altre opzioni: --ssid NOME  --no-hotspot
}
```

Se lasci `OVEST,SUD,EST,NORD`, la riga della mappa si ferma con "Invalid box" e il Campanile
resta senza ricerca delle vie e senza navigatore.

Incollate di nuovo, da qualsiasi cartella, le stesse righe (opzioni comprese) riprovano dopo un
problema, aggiornano Campanile, o portano dentro una mappa o una Wikipedia che ci aggiungi. Mappe e
Wikipedia già presenti non si riscaricano, quelle nuove vanno dove il Campanile le legge, e dati e
password restano. Per cambiare zona: `sudo rm /var/lib/campanile/maps/area.pmtiles`, poi incolla
con i numeri nuovi.

L'installatore scarica da solo le librerie delle mappe la prima volta, e aspetta se il Raspberry,
appena acceso, si sta ancora aggiornando.

`--country` sono le due lettere del tuo paese, per le regole del Wi-Fi (per esempio `IT`, `CH`).
Senza, l'installatore tiene il paese già impostato (Raspberry Pi Imager lo imposta insieme al
Wi-Fi); se non ce n'è nessuno, si ferma prima di cambiare qualunque cosa e lo dice.

L'installazione:

- installa `python3`, `python3-cryptography`, `kiwix-tools`, `nginx` e `nftables` da Debian, e
  crea l'utente di servizio `campanile`, senza privilegi
- mette il programma in `/opt/campanile`, i dati in `/var/lib/campanile`, la configurazione in `/etc/campanile`
- mette **nginx** davanti ai telefoni, sulla porta 80 (pagine e mappe) e sulla 8081 (Wikipedia),
  così un telefono lento o ingordo non blocca gli altri. Il Campanile (127.0.0.1:8080) e il server
  di Wikipedia (127.0.0.1:8082) ascoltano solo dentro il Raspberry, con i limiti di systemd, e
  partono a ogni accensione
- crea con NetworkManager la Wi-Fi **aperta** "Campanile" su `10.42.0.1`, e fa rispondere ogni
  nome di dominio con il Campanile
- chiede al chip Wi-Fi di tenere separati i telefoni (non ancora verificato sul chip di un Pi). Un
  **firewall** sull'hotspot fa raggiungere solo DHCP, DNS, ping e il Campanile (porte 80 e 8081),
  niente altro del Raspberry e nessuna rete dietro di lui

**Cosa cambia nella rete:** la connessione NetworkManager `campanile-hotspot`,
`/etc/NetworkManager/dnsmasq-shared.d/campanile.conf` (reindirizzamento DNS, solo con l'hotspot
acceso), il firewall `/etc/campanile/firewall.nft` con il servizio `campanile-firewall`. Imposta
anche il paese del Wi-Fi che gli dai e sostituisce il sito predefinito di nginx (rimesso com'era
alla disinstallazione).

Da un computer sulla stessa rete via cavo, apri l'indirizzo del Raspberry, o il nome `.local` che
l'installatore stampa, come `http://raspberrypi.local/`.

**Per togliere il Campanile:** `cd $HOME/campanile && sudo raspberry/uninstall.sh` (conserva dati
e password), oppure la stessa riga con `--purge` in fondo (cancella anche quelli). Restano i
pacchetti e il paese del Wi-Fi; nginx si ferma se era spento prima del Campanile. Resta anche la
cartella clonata: `rm -rf $HOME/campanile` la toglie.

Il Wi-Fi integrato regge un numero limitato di telefoni: quanti, non l'abbiamo ancora misurato.
Per una piazza intera serve un access point esterno.

## Licenze

- Codice del Campanile: [MIT](../LICENSE).
- Scaricati da `scripts/prepare.sh`, ciascuno con la propria licenza (copiata in
  `campanile/web/vendor/licenses/`): [MapLibre GL JS](https://maplibre.org),
  [PMTiles](https://github.com/protomaps/PMTiles) e
  [Protomaps basemaps](https://github.com/protomaps/basemaps) (BSD-3-Clause), font Noto
  (SIL OFL 1.1), [qrcode-generator](https://github.com/kazuhikoarase/qrcode-generator) (MIT),
  [certifi](https://github.com/certifi/python-certifi) (MPL-2.0).
- Scaricati dalla pagina di preparazione: [go-pmtiles](https://github.com/protomaps/go-pmtiles)
  (BSD-3-Clause), [kiwix-tools](https://github.com/kiwix/kiwix-tools) (GPL-3.0).
- Dati: mappe © [OpenStreetMap](https://www.openstreetmap.org/copyright) (ODbL) con ESA
  WorldCover (CC BY 4.0) tramite [Protomaps](https://protomaps.com). Wikipedia (CC BY-SA 4.0)
  tramite [Kiwix](https://kiwix.org).
