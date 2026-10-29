<p align="right"><a href="ADMIN.md">English</a> · <b>Italiano</b></p>

# Gestire un Campanile

## Avvisi e moderazione

La pagina **`/admin.html`** pubblica gli avvisi ufficiali, segna le strade interrotte per il
navigatore e toglie annunci falsi, offensivi o superati.

**Funziona solo dal Campanile stesso**, perché sulla Wi-Fi aperta la password viaggerebbe in
chiaro e chiunque nei dintorni potrebbe leggerla.

- **Portatile:** apri `http://localhost:8080/admin.html` sul portatile. La password è nella
  finestra nera e in `data/admin-password.txt`.
- **Raspberry Pi:** da un computer **via cavo**, con SSH attivo e un tunnel cifrato,
  `ssh -L 8080:localhost:80 utente@<indirizzo del Raspberry sul cavo>`, poi apri
  `http://localhost:8080/admin.html`. Se il Raspberry ha il desktop, va bene anche il suo browser
  (`http://localhost/admin.html`). Dall'hotspot SSH è bloccato dal firewall. La password viene
  mostrata alla fine dell'installazione ed è in `/etc/campanile/password`.

Ogni annuncio e ogni nome registrato riceve un **numero e un codice** (tipo `K7M2-QX9P`), con cui
chi l'ha pubblicato può toglierlo da solo.

Se qualcuno inonda la bacheca, la gestione mostra i nuovi annunci **in attesa di approvazione**, e
può chiudere in un clic tutti quelli di un dispositivo o degli ultimi 15 o 60 minuti.

Gli annunci si cancellano da soli dopo 14 giorni, i nomi di "sto bene" dopo 60 (`--post-days` e
`--safe-days` li cambiano, 0 li tiene). La gestione mostra anche il registro di cosa è stato fatto,
quando e da chi, e l'orologio del Campanile, che lì si può correggere (senza internet il
Raspberry riparte indietro).

### Il numero di emergenza

Le pagine dicono di chiamare il 112, il numero europeo. Fuori dall'Europa, scrivi quello della
tua zona in **Numero di emergenza**, nella gestione. Un portatile impostato su Stati Uniti o
Canada parte già con il 911.

### Più di un volontario

Con la password principale, **Chi gestisce il Campanile** dà a ogni volontario una password sua.
La crea il Campanile (tipo `K7M2-QX9P-T2PA-8WNE`) e la mostra una volta sola: scrivila e
consegnala. Può fare tutto tranne aggiungere o togliere persone, e nel registro compare il suo
nome. Se qualcuno se ne va, togli solo lui: la sua password smette subito di funzionare.

### Avvisi firmati (facoltativi)

Un'autorità, come la protezione civile, può firmare i propri avvisi. Solo quelli firmati con la sua
chiave mostrano *"Avviso firmato · Protezione Civile Torino"*.

1. **L'autorità**, una volta sola, sul proprio computer (`pip install cryptography`):
   `scripts/sign-notice.py keygen --name "Protezione Civile Torino" --out keys/`.
   La chiave privata non lascia mai quel computer.
2. **Ogni Campanile**, prima dell'emergenza, aggiunge la parte pubblica nella forma
   `{"keys": [ ...public.json... ]}` a `/etc/campanile/trusted-keys.json` (Raspberry) o a
   `data/trusted-keys.json` (portatile).
3. **Per ogni avviso**, lancia `scripts/sign-notice.py sign --key ... --title ... --text ... --urgent`
   e incolla il risultato nella pagina di gestione. Gli avvisi firmati scadono (24 ore di default,
   al massimo 7 giorni) e non si possono pubblicare due volte.

Con `--require-signed` un Campanile rifiuta gli avvisi ufficiali non firmati.

### Allarmi ufficiali in CAP

Il CAP (Common Alerting Protocol) è il formato standard degli allarmi pubblici, usato da IT-alert e
dalla protezione civile italiana. I profili italiani aggiungono solo regole al CAP 1.1 e 1.2.

Nella pagina di gestione, **Carica un allarme ufficiale (CAP)** trasforma il file di un allarme in
un avviso. Usa la lingua della pagina di gestione quando l'allarme la contiene, diventa rosso se è
grave o estremo, mostra chi l'ha emesso e sparisce quando l'allarme scade. Provato sugli otto
messaggi pubblicati da IT-alert ([pcm-dpc/IT-alert-Hub](https://github.com/pcm-dpc/IT-alert-Hub),
tutti test pubblici, quindi rifiutati come esercitazioni, e letti per intero una volta segnati
come reali) e su cinque allarmi veri del Servizio Meteorologico dell'Aeronautica Militare.

Il lettore è piccolo e severo. Dicendo sempre perché, rifiuta qualsiasi DTD o entità (è così che
un file XML attacca chi lo legge), i file oltre 512 kB, esercitazioni, prove, annullamenti,
allarmi non destinati al pubblico, quelli scaduti e lo stesso allarme due volte.

**Cosa non fa.** Non controlla la firma digitale propria dell'allarme, quindi la fonte mostrata è
quella che il file dichiara, e ci si fida perché chi gestisce il Campanile l'ha caricato. Non
riceve gli allarmi da solo.

### Consegnare i nomi di "sto bene" (PFIF)

Dopo un'emergenza i nomi possono andare a chi raccoglie le notizie sulle persone disperse.
**Esporta i nomi (PFIF)** salva un file PFIF 1.4, il formato nato dopo l'uragano Katrina e usato
da Google Person Finder dopo i terremoti di Haiti e del Giappone. Ogni voce dice che non è
verificata, perché chiunque può registrare qualunque nome. I codici che tolgono un nome e le
etichette dei telefoni non escono mai. Il file contiene nomi, messaggi e luoghi, quindi dati
personali, da dare solo a chi ne ha bisogno.
