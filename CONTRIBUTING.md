# Contribuire · Contributing

Per collaborare · To collaborate: **[info@carrotstudio.it](mailto:info@carrotstudio.it)**

**Chiunque può contribuire, e nessuno giudica.** Una correzione, una funzione nuova, una
traduzione, una frase scritta meglio, il resoconto di una prova. Il Campanile deve restare
**semplice, affidabile e comprensibile da chi non è tecnico**, e ogni modifica risponde a una
domanda: *aiuta qualcuno durante un'emergenza?*

**Anyone can contribute, and nobody judges.** A fix, a new feature, a translation, a
better-worded sentence, a test report. Campanile has to stay **simple, reliable and
understandable for non-technical people**, and every change answers one question: *does it
help someone during an emergency?*

Dove serve più aiuto: i limiti che conosciamo, in [docs/LIMITI.md](docs/LIMITI.md).
Where help is needed most: the limits we know about, in [docs/LIMITS.md](docs/LIMITS.md).

## Il test delle famiglie · The family test

Prima di ogni release: cinque persone senza competenze informatiche, di età diverse, il kit e
una breve istruzione, nient'altro. Riescono da sole a collegarsi, leggere un avviso, chiedere
aiuto e capire quando un'informazione non è verificata? Se no, non sono loro a dover imparare
l'informatica. Siamo noi a dover migliorare il Campanile.

Before every release: five non-technical people of different ages, the kit and a short
instruction, nothing else. Can they connect, read a notice, ask for help and tell when
information isn't verified, on their own? If not, it's not on them to learn computing. It's on
us to improve Campanile.

## Principi · Principles

- **Nessuna dipendenza Python** · **No Python dependencies**: solo la libreria standard, Python 3.9
  o più recente · standard library only, Python 3.9 or newer.
- **Tutto offline** · **Fully offline**: nessuna risorsa da internet nelle pagine; le librerie
  esterne passano da `scripts/prepare.sh`, con versione fissata e impronta SHA-256 · nothing from
  the internet in the pages; outside libraries come through `scripts/prepare.sh`, pinned and
  checked by SHA-256.
- **Il testo degli utenti non diventa mai HTML** · **User text never becomes HTML**: si usa
  `textContent` · use `textContent` (see `el()` in `campanile/web/common.js`).
- **Parole per tutti** · **Words for everyone**: frasi brevi, niente gergo · short sentences, no
  jargon.

## Prima di una pull request · Before a pull request

```bash
python3 -m unittest discover -s tests -v
ruff check campanile tests scripts/sign-notice.py && ruff format --check campanile tests scripts/sign-notice.py
shellcheck -S warning scripts/*.sh raspberry/*.sh "Avvia Campanile (Mac).command"
```

Ogni comportamento nuovo del server vuole un test, compreso il caso che deve essere rifiutato. Se
tocchi le pagine, provale su un telefono vero.

Every new server behavior needs a test, including the case that must be refused. If you change
the pages, try them on a real phone.

Le vulnerabilità non si segnalano con una issue · Vulnerabilities are not reported in an issue:
see [SECURITY.md](SECURITY.md).

## For developers

```
campanile/
  server.py       HTTP server: pages, API, maps with Range requests, captive portal
  store.py        data (SQLite), validation, rate limits
  devices.py      per-device limits (the phone's MAC, never stored)
  signing.py      signed notices (Ed25519, standard cryptography package)
  cap.py          official alerts in CAP, read from a file; pfif.py: the names as PFIF
  messages.py     server messages in every language
  places.py       the map search: names read from the map files, with bounded costs
  routes.py       the navigator: streets from the map files, routes, blocked streets
  copying.py      the copy to a USB stick; sharing.py: maps and Wikipedia between Campaniles
  preparation.py  the setup page's downloads (laptop only)
  launch.py       easy start on a laptop; firewall.py: Windows Firewall check and repair
  web/            the portal: HTML, CSS and JavaScript, no framework
scripts/          setup, map and Wikipedia downloads, notice signing, release package, demo
raspberry/        installer, uninstaller, nginx and systemd configuration
demo/             the static online demo (a service worker plays the server)
tests/            tests: run on Linux, Windows and macOS at every change
```

- **No Python dependencies**: standard library only, Python 3.9 or newer.
- **Fully offline**: the map's libraries, fonts and icons are downloaded by
  `scripts/prepare.sh` with pinned versions and verified SHA-256 checksums.
- **Development server:** `python3 campanile/server.py` (this computer only) or
  `python3 campanile/server.py --host 0.0.0.0` (whole network). `--help` lists the options.
- **Tests:** `python3 -m unittest discover -s tests -v`
- **Lint:** `ruff check campanile tests scripts/*.py && ruff format --check campanile tests scripts/*.py`
- **Release package:** `scripts/build-package.sh`. A `v*` tag publishes it to Releases with
  its `SHA256SUMS` and a signed build provenance. `gh attestation verify campanile-0.1.0.zip
  -R Carrotstudiosoftwarehouse/campanile` shows which commit and which workflow built it.
- **Release signature (maintainers):** CarrotStudio signs every version offline, with a key that
  never touches a network. Build the package, then `scripts/sign-release.py sign --key ...
  dist/campanile-VERSION.zip` writes `campanile/release-signature.json`: commit it and tag. The
  release workflow publishes only a package whose files match that signature
  (`python3 campanile/release.py FOLDER` checks one by hand).
- **Online demo:** `scripts/build-demo.sh data/maps/area.pmtiles` builds a static site in
  `dist/demo/`. A service worker plays the server inside each visitor's browser, with invented
  data, nothing shared between visitors and nothing to moderate. Serve it from a domain root.

The code and its comments are in English. The pages are in Italian and English, picked from the
phone's language. A few documents are only in Italian.

What has been tested and how: [docs/TESTING.md](docs/TESTING.md). Reporting a vulnerability:
[SECURITY.md](SECURITY.md).
