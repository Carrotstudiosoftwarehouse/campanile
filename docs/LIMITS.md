# Our limits, honestly

Italian version: [LIMITI.md](LIMITI.md).

Campanile 0.1 is experimental. Here is what we have not proven and what it can't do. If a limit is
missing, tell us and we will add it.

## If the internet goes down tomorrow

**What keeps working, if it was prepared beforehand**

- On the Campanile's Wi-Fi: official notices, the board, "I'm safe" and the family plan. None of
  them needs the internet.
- Maps, search and the navigator, for the maps already downloaded. Street search, the nearest
  pharmacy and the navigator need your area's detailed map.
- Wikipedia's medical articles, if downloaded with the program that serves them (on a laptop, the
  *Offline medicine* button of the setup page).
- Signed notices, if the authority's public key was added.
- More Campaniles. A USB stick made with *Prepare for every computer* starts on a computer with
  nothing installed. Maps and Wikipedia also pass over Wi-Fi between Campaniles.

**What doesn't work, or needs something else**

- **Without preparation, almost nothing.** The package has no maps, Wikipedia or Python. Offline,
  the only way in is a USB stick someone prepared.
- **Power and a Wi-Fi network.** A laptop needs a powered router (no internet needed) or a phone's
  hotspot. In our field test an Android phone (TCL 40 SE) made one with mobile data off, for up to
  8 devices. An iPhone wouldn't. The Raspberry makes its own, tested only on virtual radios.
  Battery life is an estimate.
- **Managing a Raspberry needs a computer or a screen.** The admin page opens only on the
  Raspberry itself, or from a computer on its cable through SSH. Never from a phone: the password
  would cross the open Wi-Fi. With only a phone, for now, you can't manage it.
- **The sign.** A laptop's address changes with the network, so print the sign, or copy its
  address, once the day's network is up. A Raspberry's hotspot address, 10.42.0.1, doesn't change.
- **Nothing beyond a few tens of meters.** No messages to faraway relatives, no calls (emergency
  calls need the phone network). Campaniles don't share posts or "I'm safe" names yet. Each
  neighborhood is an island.
- **Nothing new from outside.** Maps age from the day they were downloaded. Fixes and new
  languages come only on a USB stick, since over Wi-Fi only maps and Wikipedia pass.
- **The Raspberry's clock** has no battery. Offline, it restarts at the time it was switched off.
  Phones show their own time and the admin page can set the Campanile's. Until someone does,
  signed notices and the deletion of old posts follow a clock that is behind.
- **Phones on a Wi-Fi without internet.** In our field test two iPhones with mobile data off said
  "No internet connection" and stayed connected. Other phones, or data left on, may differ. Seen
  once.

## Not proven in the field

- **No real Raspberry Pi yet.** Installer, nginx, systemd and firewall ran in containers on a Mac,
  the real Raspberry Pi OS included. Hotspot, captive portal, firewall and phone isolation ran on
  virtual Wi-Fi radios. Never on a Raspberry's own Wi-Fi chip, nor with real phones.
- **Updating from a stick** ran end to end on a Mac, through the setup page from a FAT32 disk the
  Mac takes for a stick, and on Windows 11 ARM in a virtual machine, with the real double click
  (a file locked by Windows included). Never with a real stick in a person's hands. On a
  Raspberry only its checking part ran: the installer was a stand-in.
- **No crowd of real phones.** Up to 1,000 were simulated, in containers on one Mac over a virtual
  network. A real Wi-Fi radio handles far fewer at once.
- **One field test, four devices.** On 26 October 2026, with no internet: a Mac, two iPhones and an
  Android phone making the Wi-Fi. The board worked between the iPhones, a post appearing on the
  other at once. One test, one home, one Android model.
- **No family test yet.** Our main promise, simple enough for anyone, is untried with people who
  aren't technical.
- **Windows** ran on Windows 11 for ARM in a virtual machine, not an ordinary Intel or AMD PC, with
  the Yes/No prompt of User Account Control off.
- **Power cuts, half tried.** The database survived 30 hard kills of the process, losing nothing
  confirmed to a phone, and an update was stopped at each of its steps. A real power cut, which also
  loses unwritten data, and SD cards that don't write what they promised: never tried. Battery life:
  never measured.

## Measured, but only here

- **All time and memory figures** come from one laptop (Apple M3, 16 GB) or containers on it. A
  Raspberry is several times slower, so none of them holds there until measured.
- **The navigator's routes** were checked on Turin's map and in tests, not walked or driven.
- **Accessibility was checked by machine only** (WCAG 2.2 AA, 200% zoom), not yet by people who
  use a screen reader or find reading hard.

## Security: what has not been done

- **No external audit or professional penetration test.** Every review so far was ours, done as
  attackers: each finding reproduced, fixed and covered by a test that fails on the old code.
- **Our own web server, never reviewed from outside.** Phones talk to code we wrote on Python's
  `http.server` (behind nginx on the Raspberry): the part most worth an outside look.
- **The map reader was fuzzed only by us, for a few hours.** `tests/fuzz_maps.py` feeds search and
  the navigator real tiles altered like a hostile file. 40,000 cases on one processor found six
  kinds of flaw, all fixed. The worst, a few bytes, made the reader fill 2 GB of memory. A rerun of
  15,000 cases on the fixed code found none. It is our own mutation fuzzer, not coverage-guided
  like AFL or Atheris, and we never fuzzed the map drawing on the phone (MapLibre). Network
  requests (250,000) and signature checks (200,000) were fuzzed too. A good place to start.
- **Tools find known patterns, not every flaw.** Bandit, Semgrep and axe-core found nothing left to
  fix. That is not proof. CodeQL runs on every change. Of its first 6 alerts, one led to a fix
  (longer passwords for the people who run a Campanile); the other 5 we read in the code and
  closed, each with its reason.
- **Other people's code** (Python, nginx, MapLibre, PMTiles, kiwix-serve) is pinned and
  hash-checked; on the Raspberry kiwix-serve can't see the password or the database. We have
  not audited it.

## By design, for now

- **CAP alerts are loaded by hand** from a file, not received. Whether a Campanile could use
  IT-alert's channel for other systems, we haven't checked. The reader follows CAP 1.1 and 1.2,
  which the Italian profiles only add rules to. Tried on IT-alert's eight published messages, all
  public tests (refused as exercises, as they should be, and read in full once marked real), and
  on five real alerts of the Italian Air Force weather service. Never on a real IT-alert alarm,
  since none has been published. Alert signatures are not checked. IT-alert's published
  certificate verifies its 2023 messages but expired in June 2024 (see the roadmap).
- **Open Wi-Fi, no encryption.** Anyone nearby can read posts, names and the routes asked for.
- **Anyone on the Wi-Fi, or near it with a radio, can slow it down or jam it.** Campanile keeps
  one phone from taking all the bandwidth by mistake (a whole map is paced), not someone doing
  it on purpose.
- **A fake "Campanile" can't be told apart**, and can leave its pages in a phone's cache (tested).
  The fix is HTTPS for each Campanile, on the [roadmap](../ROADMAP.md). Signed notices are checked
  by the Campanile, not the phone.
- **Whoever stands between two Campaniles can block sharing** (a fake network with the same name,
  a faked address or `.local` name): they can keep both downloads busy until sharing is stopped,
  but can't change a file. The fix, a channel authenticated by the code, is on the
  [roadmap](../ROADMAP.md).
- **Nobody is verified.** Anyone can post anything, or write any name in "I'm safe".
- **Per-device limits can be dodged** with many Wi-Fi adapters, or a phone address that keeps
  changing. The emergency brake holds those posts for approval, but a determined flood still
  costs the admin work. They also start again each day: a phone's tag changes every day, so that
  days can't be linked. One phone can keep 5 posts open and register 10 names each day.
- **The main password can do everything**, including adding and removing the people who run the
  Campanile. Everyone else signs in with their own password, and the log says who did what (the
  last 1,000 actions). Whoever uses the main password shows up only as "Main password".
- **Whoever holds the device holds everything.** Database and admin password are not encrypted on
  disk. Deleted data, and closed posts, are overwritten rather than left in the file (measured:
  before this, a deleted phone number could still be read). But SD cards and SSDs move writes
  around inside the chip, so an old copy can survive there: only an encrypted disk would close
  that.
- **Maps are read inside Campanile itself.** A map too big for the memory stops Campanile while
  it is read, board and notices included. A Raspberry starts it again by itself, a laptop with a
  double click. After three tries that map is set aside and the rest works. Measured on a laptop
  and in containers, not on a Raspberry.
- **The Raspberry installer speaks English only**, for now, also to whoever follows the Italian
  guide. The pages speak Italian and English.
- **No automatic updates.** A fix reaches a Campanile only when someone brings it, on a stick
  checked against CarrotStudio's signature, or installs it.
- **Posts and names delete themselves**: posts after 14 days, "I'm safe" names after 60. The admin
  can change both at startup, or keep them forever.
- **The navigator** doesn't know the phone's position or turn bans, estimates times, is as recent
  as its map, and knows only the blocked streets someone marked. It trusts the map's one-way
  streets, though on Turin's map 60 of 8,415 point different ways at two zoom levels.
- **The nearest hospital may have no emergency room.** The maps mark every hospital the same
  way, private clinics included: the button shows the nearest, not the one that takes
  emergencies.
- **A few tens of meters of range.** Not a certified emergency system. It doesn't replace the
  emergency number.

## Technical problems still to solve

Roughly in order of importance:

1. **Trust without the internet**: HTTPS per Campanile, certificates issued before the emergency,
   notices checked on the phone. It would also give the navigator the phone's position.
2. **Proof on real hardware**: everything under "Not proven in the field", plus timings and memory
   on a Raspberry (a Zero 2 W has 512 MB).
3. **More phone models on a Wi-Fi without internet**, and Android phones as guests.
4. **From islands to a network**: notices, posts and "I'm safe" names passed between Campaniles (by
   contact, USB stick or LoRa radio) without spreading a flood or a fake name. A signed notice
   already checks itself anywhere, but nothing carries it yet. One idea: phones going from one
   Campanile to the next carry them, published only if the signature holds, with no app, radio or
   internet. A radio packet holds a few hundred bytes and a notice can pass a kilobyte, so radio
   suits short notices.
5. **A battery-backed clock** for the Raspberry (the Pi 5 has a connector for one), so nobody has
   to set it after a long power cut.
6. **A coverage-guided fuzzer** (AFL, Atheris) on the map reader and street builder, and an
   external security audit.
7. **The navigator**: turn bans, missing from our map files, and a live position, which needs
   HTTPS.

## Help us close them

Every line above is a way to contribute. How to test what we couldn't: [TESTING.md](TESTING.md).
How to report a flaw privately: [SECURITY.md](../SECURITY.md).
