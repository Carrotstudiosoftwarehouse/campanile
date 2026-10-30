<p align="right"><a href="RADIO.md">English</a> · <b>Italiano</b></p>

# Comunicare quando non c'è rete

Il Campanile è una bacheca pubblica di quartiere, non un sistema di messaggi privati. Per parlare
con la propria famiglia o con un gruppo quando internet e la rete telefonica non funzionano,
esistono strumenti già pronti.

Regola generale: **ogni trasmissione radio si può localizzare.** Chi ha l'attrezzatura
adatta (un radiogoniometro) può capire da dove trasmetti, cifrata o no. Teniamone conto
in situazioni di conflitto.

## Briar: messaggi tra telefoni Android, senza internet

[Briar](https://briarproject.org) è un'app di messaggistica gratuita e open source. Senza
internet passa i messaggi via **Bluetooth o Wi-Fi** tra telefoni vicini; con internet
passa attraverso la rete Tor. I messaggi sono cifrati e non passano da un server centrale.

- **Solo Android** (Google Play o F-Droid). La FAQ del progetto, alla domanda su una
  versione per iPhone, risponde "probabilmente no", per i limiti che iOS pone alle app in
  background ([FAQ](https://code.briarproject.org/briar/briar/-/wikis/FAQ)).
- Portata: quella di Bluetooth e Wi-Fi, cioè decine di metri.
- I contatti si aggiungono di persona (codice QR) o tramite un contatto in comune:
  **va fatto prima**.

## Meshtastic: messaggi di testo a chilometri di distanza

[Meshtastic](https://meshtastic.org) usa piccole radio **LoRa** (da circa 30-40 euro)
collegate al telefono via Bluetooth. Ogni radio ripete i messaggi delle altre, quindi la
rete si allarga da sola: in campo aperto si coprono chilometri. Si scrivono solo messaggi
di testo brevi.

In Europa si usa la regione **EU_868**: 869,4-869,65 MHz, potenza massima 27 dBm (500 mW),
trasmissione al massimo per il 10% del tempo
([documentazione](https://meshtastic.org/docs/configuration/radio/lora/)).

**Attenzione alla riservatezza:**

- Il **canale predefinito usa una chiave pubblica**, inclusa nel codice di Meshtastic:
  chiunque può leggere quei messaggi. Per un gruppo privato si crea un canale con chiave
  casuale (`meshtastic --ch-set psk random --ch-index 1`) e la si condivide di persona
  ([documentazione](https://meshtastic.org/docs/configuration/radio/channels/)).
- I messaggi diretti tra due persone sono cifrati con una chiave che solo i due
  possono calcolare.
- L'intestazione dei pacchetti **non è mai cifrata** (serve per ripeterli), e Meshtastic
  **non ha forward secrecy**: chi registra il traffico e in seguito ottiene la chiave può
  leggere tutto ([documentazione](https://meshtastic.org/docs/overview/encryption/)).

## Radio PMR446: voce, senza licenza

Le ricetrasmittenti **PMR446** sono i classici walkie-talkie che si comprano in coppia.
Non servono internet, credito o telefoni: si preme e si parla.

- Banda 446,0-446,2 MHz, 16 canali, potenza massima 500 mW e antenna integrata. Sono
  vietati ripetitori e stazioni fisse.
- In Italia sono di **libero uso**: niente autorizzazioni né canoni (art. 105 del Codice
  delle comunicazioni elettroniche). Sono vietati gli apparati non omologati e le
  modifiche, come antenne diverse o potenza maggiore. Fuori dall'Italia, controlla le regole
  del paese in cui sei.
- Portata: da qualche centinaio di metri in città a qualche chilometro in campo aperto.
- **Nessuna riservatezza:** chiunque sia sintonizzato sullo stesso canale ascolta.

## In pratica

| Esigenza | Strumento |
|---|---|
| Sapere cosa succede nel quartiere, chiedere e offrire aiuto | **Campanile** |
| Messaggi privati con la famiglia vicina, solo Android | **Briar** |
| Messaggi di testo a chilometri, anche con iPhone | **Meshtastic** (con canale privato) |
| Parlare a voce con chi è vicino | **PMR446** |

Tutti richiedono la stessa cosa: **prepararsi prima**. Installare l'app, aggiungere i
contatti, caricare le batterie, decidere un canale e provarlo.
