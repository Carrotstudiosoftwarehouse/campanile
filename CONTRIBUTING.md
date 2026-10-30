# Contribuire · Contributing

Per collaborare · To collaborate: **[info@carrotstudio.it](mailto:info@carrotstudio.it)**

**Chiunque può contribuire.** Una correzione, una funzione nuova, una traduzione, una frase
scritta meglio, il resoconto di una prova. Il Campanile deve restare **semplice per chi non è
tecnico**, e ogni modifica risponde a una domanda: *aiuta qualcuno durante un'emergenza?*

**Anyone can contribute.** A fix, a new feature, a translation, a better-worded sentence, a test
report. Campanile has to stay **simple for non-technical people**, and every change answers one
question: *does it help someone during an emergency?*

Dove serve più aiuto: i limiti che conosciamo, in [docs/LIMITI.md](docs/LIMITI.md).
Where help is needed most: the limits we know about, in [docs/LIMITS.md](docs/LIMITS.md).

## Il test delle famiglie · The family test

Il test che vogliamo prima di ogni release, non ancora fatto: cinque persone senza competenze
informatiche, di età diverse, il kit e una breve istruzione, nient'altro. Riescono da sole a
collegarsi, leggere un avviso, chiedere aiuto e capire quando un'informazione non è verificata?
Se no, si cambia il Campanile.

The test we want before every release, not yet done: five non-technical people of different
ages, the kit and a short instruction, nothing else. Can they connect, read a notice, ask for
help and tell when information isn't verified, on their own? If not, we change Campanile.

## Principi · Principles

- **Nessuna dipendenza obbligatoria** · **No required dependencies**: solo la libreria standard,
  Python 3.9 o più recente; `cryptography` serve solo per firmare · standard library only, Python
  3.9 or newer; `cryptography` only to sign.
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
ruff check campanile tests scripts/*.py && ruff format --check campanile tests scripts/*.py
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
  server.py       the web server put together: settings, which part answers, command line
  transport.py    connections, deadlines and HTTP framing; nothing about what a request is for
  files.py        pages and maps from disk: never outside their folder, Range, a whole map paced
  api.py          what phones and other Campaniles ask: status, board, names, search, routes
  admin.py        the admin and setup pages, from the Campanile itself only
  store.py        data (SQLite), validation, rate limits
  devices.py      per-device limits (the phone's MAC, never stored)
  signing.py      signed notices (Ed25519); ed25519.py checks them where `cryptography` is missing
  strictjson.py   the JSON reader for requests, signatures and share lists: no key twice, no NaN
  cap.py          official alerts in CAP, read from a file; pfif.py: the names as PFIF
  messages.py     messages in every language: the server's and the laptop window's
  places.py       the map search: names read from the map files, with bounded costs
  routes.py       the navigator: streets from the map files, routes, blocked streets
  copying.py      the copy to a USB stick; sharing.py: maps and Wikipedia between Campaniles
  preparation.py  the setup page's downloads (laptop only)
  launch.py       easy start on a laptop; firewall.py: Windows Firewall check and repair
  release.py      is this folder a version signed by CarrotStudio?
  update.py       updating from a USB stick, only to a newer signed version
  web/            the portal: HTML, CSS and JavaScript, no framework
scripts/          setup, map and Wikipedia downloads, notice and release signing, package, demo
raspberry/        installer, uninstaller, nginx and systemd configuration
demo/             the static online demo (a service worker plays the server)
tests/            tests: run on Linux, Windows and macOS at every change
```

- **Development server:** `python3 campanile/server.py` (this computer only) or
  `python3 campanile/server.py --host 0.0.0.0` (whole network). `--help` lists the options.
- **Release package:** `scripts/build-package.sh`. A `v*` tag publishes it to Releases with its
  `SHA256SUMS` and a signed build provenance. `gh attestation verify campanile-VERSION.zip -R
  offternet-org/campanile` shows which commit and which workflow built it. Versions 0.1.x were
  built before the move to offternet-org: for them use `--owner Carrotstudiosoftwarehouse`.
- **Release signature (maintainers):** CarrotStudio signs every version offline, with a key that
  never touches a network. Build the package, then `scripts/sign-release.py sign --key ...
  dist/campanile-VERSION.zip` writes `campanile/release-signature.json`: commit it and tag. The
  release workflow publishes only a package whose files match that signature
  (`python3 campanile/release.py FOLDER` checks one by hand).
- **Online demo:** `scripts/build-demo.sh data/maps/area.pmtiles` builds a static site in
  `dist/demo/`. A service worker plays the server inside each visitor's browser, with invented
  data, nothing shared between visitors and nothing to moderate. Serve it from a domain root.

The code and its comments are in English. The pages are in Italian and English, picked from the
phone's language; the laptop's window from the computer's. A new language is a column in
`campanile/messages.py` and `campanile/web/strings.js`.

**The names at the top of the program folder never change.** A Campanile already installed
copies an update with its own list of them (`copying.PROGRAM`): a renamed or new file there would
never arrive, and the signature check would refuse the update. New files go inside the existing
folders. A test guards the list.

What has been tested and how: [docs/TESTING.md](docs/TESTING.md). Reporting a vulnerability:
[SECURITY.md](SECURITY.md).
