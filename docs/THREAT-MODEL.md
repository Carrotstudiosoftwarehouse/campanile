# Security and privacy

Italian version: [SICUREZZA.md](SICUREZZA.md).

## In short, for everyone

- The Wi-Fi is **open and unencrypted**. Anyone nearby can join and see all posts, "sto bene" (I'm
  safe) names and notices.
- **No connection log.** No IP addresses or visited pages are saved.
- Deleted posts, names and notices are **overwritten on disk**, not just hidden.
- The family plan **never reaches the Campanile and isn't kept on the phone**. It lives in the open
  page, and you print it.
- Management (notices, moderation) works **only on the Campanile itself**, so the password never
  crosses the Wi-Fi.
- **Nothing stays forever.** Posts go after 14 days, names after 60 (adjustable at start), deleted
  from the database, not hidden (tested).
- **Admin actions are logged**: what, when and who, since each volunteer can have a password of
  their own (made by the Campanile, kept only as a hash). The last 1,000 are kept.
- **The admin can fix the clock**, which a Raspberry loses offline (no clock battery). Up to a year
  from the computer's clock, and logged. Post times, deletion of old posts, signed notices and the
  phones' time follow it (tested).

## What anyone connected can do

We assume someone on the network wants to cause trouble.

| Threat | Defense |
|---|---|
| Text that fools the eye | Invisible formatting characters (reversed text, zero-width spaces) are removed, except the joiner emoji need. |
| Code injection (XSS) | User text only via `textContent`, never as HTML. The CSP blocks scripts and styles the Campanile didn't serve. |
| Flooding from many addresses | Limits **per device**, by the MAC the Raspberry sees. A new IP doesn't help, a new MAC forces a reconnect each time. 5 open posts, 10 names. Over 30 posts in 5 minutes, new ones wait for approval and the board stays readable. One click closes a device's posts, or the last few minutes'. Only a daily-changing hash is stored, no MAC or IP (tested). |
| Filling board or disk | 10 submissions per 10 minutes per device. Caps of 2,000 open posts, 5,000 names, 50 notices. Requests up to 8 KB. |
| Closing others' posts | Needs the poster's 8-character code (about 40 bits). 20 wrong tries in 10 minutes block the device. |
| Guessing the admin password | Local-only admin page, same 20-try lockout, constant-time comparison. |
| An internet page talking to the Campanile under its own name (DNS rebinding) | Needs the Campanile laptop's browser, online. Internet domain names get 421. Addresses, `.local` and the computer's name still work, and nobody can register those. A page could once read the board and lock out the admin with 20 wrong passwords (tested, second adversarial review). Now it gets nothing and the lockout doesn't move. |
| Reading system files | Paths must resolve inside the portal or maps folder (`.pmtiles` only). Windows tricks are rejected: streams (`index.html:Zone.Identifier` leaked the download origin, tested), trailing dot or space, backslash, `con`, `nul` and similar. |
| Saturating the server | 256 connections, 16 per device, 10 seconds to send a request (drip-feed, tested with a real attack). On the Raspberry the hotspot firewall caps each MAC at 64 connections, before nginx. Thousands of one-byte connections from one device made others fail 27 of 60 requests and logged 1.7 MB a minute. Now 0 and 0 (tested). |
| Posing as another phone or the Campanile | On the Raspberry, limits, lockout and local-only admin rely on the address nginx writes (`X-Real-IP`). Request smuggling could forge it: a GET with a body ran 8 of 8 hidden requests. Two fixes, each enough alone (tested one at a time, then 0 of 16). nginx sends one request per connection. The Campanile takes a body only on POST, one `Content-Length`, no `chunked`. |
| Power loss | Accepted posts and notices hit disk before the reply (SQLite `synchronous=FULL`). |
| Framing by other sites | `frame-ancestors 'none'`, `X-Frame-Options: DENY`. |

**Signed notices (Ed25519):**

- Checked by OpenSSL, through the standard `cryptography` library, where it is installed (the
  Raspberry). Without it (laptops), by our `ed25519.py`: checking only, no secrets, following
  RFC 8032, and giving OpenSSL's answer on the RFC vectors, on Google's 210 Wycheproof cases and
  on 12,000 random signatures. Signing always uses `cryptography`.
- Trusted keys are installed **beforehand** as a file, never received from the network, or a forger
  would forge the key too.
- The signature covers title, text, urgency, date and **expiry** (7 days max). The prefix
  `campanile-notice-v1` binds it to this use only.
- A signed notice can't be published twice, and disappears at expiry.
- Signed text isn't cleaned. Invalid characters are rejected.
- Duplicate JSON keys are rejected everywhere, and the verified document is stored, rewritten, so
  two parsers can't see two notices.
- A broken keys file disables only signed notices, not the Campanile.
- Expiry follows the Raspberry's clock, which can be wrong offline.

**Official CAP alerts, from a file on the admin page:**

- Our reader (`campanile/cap.py`, on Python's parser) refuses any DTD or entity, which stops
  "billion laughs" and external entities reading local files. Both tested, with files over 512 kB
  (real IT-alert messages with area polygons reach 108 kB).
- Admin page only, so only from the Campanile itself. Phones can't send the larger request an alert
  needs and keep the 8 kB limit (tested).
- Valid CAP 1.1 or 1.2 per block, any language. Exercises, tests, cancellations, non-public, expired
  and repeated alerts are refused with a reason. Text is cleaned like any notice's, never shortened.
- A Campanile that requires signed notices refuses CAP alerts.

**"I'm safe" names as PFIF**, for a larger registry after the emergency. Admin page only, logged.
Removal codes and phone tags never leave (tested). Records are marked unverified, with ids under a
random name (`campanile-1a2b3c4d.invalid`) that reveals no location.

**Known limits, knowingly accepted:**

- **The Campanile verifies signatures, not the phone.** Over HTTP on open Wi-Fi an interceptor can
  alter what a phone shows, the "firmato" (signed) label included. A browser check wouldn't help, as
  its code comes over the same network. A verifier independent of this network (an app or a second
  Campanile) is on the roadmap.
- **A CAP alert's own signature isn't checked.** CAP allows one, the Campanile ignores it. The
  issuer shown is the file's claim, trusted because the operator chose to load it.
- **"Sto bene" doesn't verify identity.** Anyone can register any name. The page says so clearly,
  since a fake entry gives false reassurance.
- **Many adapters, or a new MAC or address per reconnect**, beat the per-device limits, the
  10-submission one included. The emergency brake holds their posts for batch removal, and the
  global caps and moderation remain. On the laptop, which can't see MACs, limits are per IP.
- **A fake Campanile** (same Wi-Fi name, fake portal) can't be told apart. To the browser it is *the
  same site* (`http://10.42.0.1`), so it can read what the real one left on the phone and plant
  cached pages and scripts that then run on the real network, even after a reload (tested with
  Chrome). Hence the family plan isn't kept on the phone. Only your posts' numbers and codes stay,
  and at most they allow closing those posts. The real fix is HTTPS with a per-Campanile certificate
  the phone checks offline, plus a twin-network detector (roadmap). Without HTTPS browsers have no
  remedy, as cache-clearing commands need HTTPS.
- **The registry can be read almost whole** by searching many names (2 letters minimum). That is its
  purpose, finding people, and the page tells whoever registers.
- **Post codes travel in clear.** An eavesdropper could close someone's post. Limited, reversible
  damage.
- **Stored codes are unsalted SHA-256**, recoverable in minutes from a stolen database. Only the
  Campanile can read it (not even `kiwix-serve`, tested), so stealing it means already owning the
  Campanile.
- **`https://` pages opened before connecting show a certificate error**, since the portal uses
  `http://`. That is normal. Don't "accept" it.

## The setup page (laptop only)

The only part that downloads from the internet and runs programs, so the most locked down.

- **Laptop only** (`--setup`, set by `launch.py`). Unreachable on the Raspberry.
- **Local, with the password.** Never from the network, not even with `--admin-from-network`. Only
  as `localhost` or `127.0.0.1`, which defeats DNS rebinding to 127.0.0.1.
- **No address comes from the page.** Three fixed operations. The area is a checked rectangle of
  numbers, at most 0.25 square degrees.
- **HTTPS only**, mirror redirects too. Certificates are checked against the system's plus Mozilla's
  (certifi, pinned by SHA-256), since python.org's Mac Python has none and a fresh Windows lacks
  some.
- **Verified programs.** The SHA-256 of `pmtiles` and `kiwix-serve` is in the code. Only named files
  are extracted, under plain names. No shell, arguments as a list, and "Annulla" (Cancel) stops
  them.
- **Wikipedia** must match the SHA-256 Kiwix publishes, read from Kiwix, not the mirror. A bad file
  is deleted, an interrupted one resumes.
- **Nothing half-done.** `.partial` files move in only when complete and checked. A map failing
  `pmtiles verify` never replaces the good one.
- `kiwix-serve` runs with `--attachToProcess` (it exits with the Campanile), `--blockexternal` and
  16 connections per device.
- **Location** comes from the browser, with consent, only to frame the area. It never reaches the
  Campanile. Without it, search the town or move the map.
- **Windows can't replace an open file** (measured: error 5). A new map waits up to 60 seconds for
  search or phones to release the old one. Kiwix stops before its old Wikipedia is deleted.

## Searching the map

- **Offline.** Names come from the maps (streets, towns, neighborhoods, hospitals, pharmacies,
  drinking water...). Tested in a container with no network and in the browser: no request leaves
  the Campanile.
- **Not logged.**
- **Cheap.** Two letters can match tens of thousands of names (Milan, 101,425 names: 65 ms a
  search), so at most 500 are ranked. Repeated words count once, 4 words at most, rarest first. A
  word in over 30,000 names only matches names starting with the typed text. Forty copies of one
  letter on 250,000 names went from 162 to 5 ms, and no search on such a map takes more than a few
  milliseconds. 30 searches per 10 seconds per device, one at a time. The next waits up to a quarter
  second, then gets "try again in a moment". With 30 phones searching nonstop, others' searches take
  14 ms (tested).
- **Names stay text** (`textContent`), so a hostile name never becomes code.
- **Hostile maps.** A map from another Campanile may be built to stall it or fill its memory, so
  reading any file costs a bounded amount. A directory holds a million entries at most and is read
  once, even under another length. Entries, tiles, bytes, names and comparisons each have a budget,
  several times the largest real maps (whole world, metropolitan Milan). Over budget, a map shows
  but isn't searchable until the file changes, across restarts. The in-memory index is capped at 24
  words a name and 250,000 distinct words. Reads or indexes cut short by a crash are counted, and
  after three the Campanile starts without that map. All maps together: a million names at most.
  - Tested with 12 hostile files: that map can't be searched, the rest works. The old code took time
    growing with the file (one stream read 3,000 times: 1.7 s) or kept 1,000 same-name towns instead
    of 256. Real maps give the same names.
  - Fuzzing 40,000 altered maps (`tests/fuzz_maps.py`) found six kinds of flaw, the worst a few
    bytes that filled 2 GB of memory. All fixed, and damaged files now end in a clean refusal
    ([TESTING.md](TESTING.md)).

## The navigator

- **Offline.** Streets come from the map files on the Campanile (junctions, one-way streets,
  footpaths, steps, bridges, tunnels). Nothing is downloaded, routes aren't saved or logged. Start
  and destination travel in clear, readable by anyone nearby with the right tools.
- **One touch closes a place, not a line**: everything within 20 m of the point and its street, and
  a bridge or tunnel across its width (the same structure's lines within 50 m, such as the other
  carriageway, sidewalks or other tube). Open lines within 60 m are flagged to the admin, who can
  close them too. Measured on metropolitan Turin, touching mid-span every bridge and tunnel stretch
  of 50 m or more and routing across, by car and on foot, both ways. Before, 58 of 294 bridges and
  22 of 168 tunnels stayed crossable alongside. Now none. On the real Ponte Regina Margherita one
  touch closed 2 of its 4 lines. Now all 4, and every route stays 94 m or more away.
- **Only the database decides closures**, set only from the admin page on the Campanile. The
  navigator takes no outside list. After each change it rereads the database, one read at a time, so
  it always matches, even with two changes at once (tested with simultaneous requests). It rereads
  on restart, a version number catches missed changes, and a map with unread closures gives no
  route. 300 closed places at most.
- **Road rules from the map.** Cars obey one-way streets and roundabout direction, even where tile
  borders split a roundabout into arcs (170 Turin stretches were two-way before). Walkers avoid
  motorways and main-road tunnels. Motorways and trunk roads join others only where the map says,
  never at a guessed junction.
- **Cheap and fair.** One route at a time, with the same quarter-second wait and "try again in a
  moment" as search. Per device, 10 routes and 2 seconds of routing per 10 seconds. Routes over 5
  seconds stop and ask for nearer points. Measured in a container with one phone requesting long
  routes nonstop. On Turin with a quarter CPU, about a Raspberry, the other phone's "busy" refusals
  fell from 9 of 15 to 1 of 19, and on a map at the limits below from 16 of 17 to 5 of 20. On the
  test laptop, metropolitan Turin (129,326 stretches, 88,091 junctions) gives a 20-30 km car route
  across the whole map in 30-118 ms. A Raspberry is slower, not yet measured.
- **Hostile maps**, as for search. Streets come only from the most detailed tiles: 4,000 at most (a
  setup-page area has about 2,900), 4 million points, and a work budget (segments into cells,
  segment pairs compared, per tile and per map) about 12 times metropolitan Turin's. Odd-sized tiles
  are refused. Files of a few hundred bytes to 11 KB stacking thousands of streets on one spot, or
  stretching one over a huge tile, took minutes or exhausted memory. Each is now refused in under a
  tenth of a second, and real maps build as before (metropolitan Turin: 3.2 seconds, 16 MiB). Builds
  cut short by a crash are counted, and after three the map is dropped until the file changes
  (tested by really killing the process).
- **The right map** is chosen by where its streets are, not by its header. If they are too far from
  a point the next is tried, so a tiny map claiming the world no longer takes every route.
- **The phone is told** the data date and, if the point was 40 m or more from a street, how far the
  start or end moved.
- **Closures are public**, in red on every phone with the admin's note. Write only what anyone may
  read.
- **Input is checked.** Finite in-range numbers only (NaN, Infinity or a 400-digit number are
  refused as invalid). A malformed note gets a clear refusal, not an internal error (tested).
- **What it can't know.** Later changes, unmarked closures, and turn bans, which map files lack. On
  Turin 60 of 8,415 one-way segments change direction between two zoom levels, and the most detailed
  wins. The page shows the data date and says to follow signs and open streets.

## Copies on a USB stick

A prepared Campanile can start others: the setup page copies everything to a USB stick. Programs
travel this way, so the rules are strict.

- **Programs travel only on a stick handed over in person**, never over Wi-Fi, where a new computer
  can't tell the real Campanile from a fake. The guide says so.
- **A closed list**: program, maps, Wikipedia, signed-notice public keys, Kiwix, Python. Never the
  database (names, posts, contacts) or the password. No folder is copied as it is.
- **A hostile stick can't slip anything in.** A Campanile folder already there is used only if it
  holds exactly what the copy writes. A planted module, library beside `kiwix-serve`, installer,
  database or known password would be used by whoever starts the copy. Anything else stops the copy
  untouched (10 kinds tested, including our second adversarial review's attack, which ran its code
  from the copy and is now refused). Only leftovers go: half-written copies, Python's cache, files a
  Mac adds.
- **No link is followed or accepted.** A "map" linking to the database stays out (tested). Folders
  are made one by one, and every file, readme and list included, is written aside and moved in when
  complete. A link on the stick once redirected two writes and overwrote the live database (from the
  review). Now the copy stops. Removing each defense fails its test.
- **Python and commands come from the system, never the folder.** `install.sh` and the preparation
  scripts run `python3 -I` (a `secrets.py` beside them isn't imported, tested, and a test checks
  every script). The Raspberry service ignores home packages (`-s`). The Windows launcher skips its
  own folder (`NoDefaultCurrentDirectoryInExePath`). On Windows a `py.bat` beside it runs without
  that line, not with it (tested).
- **The Python on the stick is official.** Pinned hashes, checked against python.org's Sigstore
  signature. Windows checks the Python Software Foundation's signature (tested: valid), the Mac
  Apple's.
- **Incomplete copies are caught.** The hash list is written last, and at start a missing or
  wrong-size program file is reported.

## Maps and Wikipedia over Wi-Fi between Campaniles

A Campanile can pass maps and Wikipedia to another on the same network, offline.

- **Data only**: maps and Wikipedia from their folders, by name. Never programs, the database or
  anything else.
- **An 80-bit code**, shown only on the admin page (on the Campanile itself), is read out in person.
  It signs the list of files and their SHA-256 (HMAC-SHA256), so a same-named fake's list is refused
  and a swapped file fails its hash. The code never crosses the network.
- **The receiver checks** names (no `../`), sizes, hashes, duplicates. No redirects or proxies. It
  never overwrites its own files (the new one gets `-2`). The address must be on the local network.
- **Downloads need a permission** derived from the code, valid only from the receiver's address.
  Phones can't burn bandwidth on gigabyte files, and an eavesdropper can't use it elsewhere to hold
  the downloads (via nginx: 206 for the receiver, 404 elsewhere; the review's attack now fails and
  the receiver gets the map). 2 downloads at once, 2 MB/s each. Sharing stops after two hours, or
  with a click.
- **On the Raspberry** files pass through nginx without disk buffering (measured: its folder is
  unchanged), under the usual per-phone limits.
- **Tested with real impostors** (another code, swapped files, a redirect to the real Campanile, the
  right code with `../` names). All stopped. Removing each defense fails its test.

## Windows: the firewall

Pressing «Annulla» (Cancel) at Windows' prompt blocks the phones, and Windows doesn't ask again. The
Campanile notices (reading rules needs no admin rights) and offers a fix.

- **Only on ENTER** from the person at the screen, with the permission Windows asks for.
- **It opens only what it uses.** It removes the «Blocca» (Block) rules for its `python.exe` and
  `kiwix-serve.exe` and adds TCP-only allow rules on their ports (8080, 8081), with a clear name
  («Campanile - python.exe - TCP 8080»). Other ports prompt as usual.
- **The program path reaches the admin command only as base64.** PowerShell treats typographic
  apostrophes (’) as quotes, so doubling quotes failed (tested: a command hidden in a folder name
  ran). PowerShell is called by full system path, never from the current folder.
- **Tested on every change** in Windows CI: block rules for hostile paths, repair, no command
  executed.

## Connections: closing them properly

- With slots full, the longest-idle connections close (browsers reopen them) and newcomers queue
  instead of being refused. On Windows that means closing the socket, since `shutdown()` doesn't
  wake the reader there (measured).
- If none is idle, the device holding the most slots gives one up, oldest response first. A slow
  downloader on many connections evicts itself, not the phones (tested: 0 of 23 requests before, 90
  of 90 after).
- A response sent before the request is fully read closes in two steps (RFC 9112, 9.6), capped at 2
  seconds and 64 KB so it can't hold a slot.

## Raspberry Pi: who talks to whom

```
phone ──port 80─────▶ nginx ──127.0.0.1:8080──▶ Campanile (Python)
phone ──port 8081───▶ nginx ──127.0.0.1:8082──▶ Kiwix (Wikipedia)
      (hotspot firewall: only DHCP, DNS, 80 and 8081; phones isolated from each other)
```

The sensitive points are the **links** between pieces, and each has a test.

- **The phone's address.** Behind nginx, Python sees `127.0.0.1`. nginx **overwrites** `X-Real-IP`
  with the real address. Python trusts it only from nginx on the same machine, and without it treats
  the request as **not local**. Tested: faking `X-Real-IP: 127.0.0.1` or `X-Forwarded-For` stays
  locked out of the admin page.
- **Where a request ends.** nginx and Python must agree, or a request's tail becomes a new one
  written by the phone. nginx rejects the classic ambiguous forms (tested) and sends one request per
  connection. Python never keeps a connection open with an unread body.
- **Internal ports** 8080 and 8082 listen only on `127.0.0.1` (tested unreachable from the network).
- **Wikipedia on its own origin** (port 8081). A Kiwix flaw can't read what Campanile pages keep in
  the browser (the open family plan) or use the Campanile's API as the phone.
- **Hotspot firewall.** Phones reach only DHCP, DNS, 80 and 8081. No other service (SSH included),
  no forwarding. Tested from a second device, with a control run with the firewall off.
- **Phones isolated** (`ap-isolation`), so none can pose as router or DNS server for the others.
  Tested with NetworkManager 1.42 and 1.52. Whether the Raspberry's Wi-Fi chip honors it must be
  checked in the field.
- **No nginx access log.** No phone addresses on disk, and floods can't fill the SD card.
- **Per-phone limits in nginx**: 16 connections, 10 seconds per request, 20 API requests a second.
  Submission limits stay in the Campanile, per real address. Tested with 300 slow connections: other
  devices keep working.
- **Maps.** nginx too serves only `.pmtiles` from the maps folder. The data folder is traversable,
  not listable, and only the service reads the database.
- **File types.** `.mjs` (the map code) and fonts are declared, since Debian doesn't know them and
  the browser would refuse them.
- **Kiwix 3.7** reads network interfaces at startup, so its systemd sandbox allows that one extra
  socket type (`AF_NETLINK`). Without it, it didn't start on Debian 13.

## Raspberry Pi: the rest

- The service runs as `campanile`, unprivileged, under systemd protections (`ProtectSystem=strict`,
  `NoNewPrivileges`, `PrivateTmp`, read-only filesystem except `/var/lib/campanile`, only the right
  to open port 80).
- `/opt/campanile` belongs to root. The service can't modify it.
- The admin password, `/etc/campanile/password`, is readable only by root and the service.
- Kiwix has the same restrictions plus `--blockexternal`, which blocks internet links.
- `scripts/prepare.sh` pins library versions and checks their SHA-256. Fonts and icons come from a
  pinned git commit.

To report a vulnerability: [SECURITY.md](../SECURITY.md).
