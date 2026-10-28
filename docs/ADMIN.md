<p align="right"><b>English</b> · <a href="GESTIONE.md">Italiano</a></p>

# Running a Campanile

## Notices and moderation

The **`/admin.html`** page posts official notices, marks blocked streets for the navigator, and
removes fake, offensive or outdated posts.

It **only works on the Campanile itself**, because on the open Wi-Fi the password would travel in
clear text for anyone nearby to read.

- **Laptop:** open `http://localhost:8080/admin.html` on the laptop. The password is in the black
  window and in `data/admin-password.txt`.
- **Raspberry Pi:** use its own browser (`http://localhost/admin.html`). With SSH enabled, a
  computer **by cable** can also use an encrypted tunnel,
  `ssh -L 8080:localhost:80 user@<the Raspberry's cable address>`, then open
  `http://localhost:8080/admin.html`. The firewall blocks SSH from the hotspot. The password is
  shown at the end of installation and saved in `/etc/campanile/password`.

Each post and registered name gets a **number and a code** (like `K7M2-QX9P`) that lets its
author remove it.

If someone floods the board, the admin page shows new posts **waiting for approval**, and can
close in one click all posts from one device or from the last 15 or 60 minutes.

Posts expire after 14 days, "I'm safe" names after 60 (`--post-days` and `--safe-days` change
this, 0 keeps them). The admin page also shows a log of what was done, when and by whom, and the
Campanile's clock, which you can set there (without internet a Raspberry restarts behind).

### More than one volunteer

With the main password, **Who runs this Campanile** gives each volunteer a password of their own.
The Campanile makes it (like `K7M2-QX9P-T2PA`) and shows it once: write it down and hand it over.
They can do everything except add or remove people, and the log shows their name. If someone
leaves, remove only them: their password stops working at once.

### Signed notices (optional)

An authority, such as civil protection, can sign its notices. Only notices signed with its key
show *"Signed notice · Protezione Civile Torino"*.

1. **The authority**, once, on its own computer (`pip install cryptography`):
   `scripts/sign-notice.py keygen --name "Protezione Civile Torino" --out keys/`.
   The private key never leaves that computer.
2. **Each Campanile**, before the emergency, adds the public part as
   `{"keys": [ ...public.json... ]}` to `/etc/campanile/trusted-keys.json` (Raspberry) or
   `data/trusted-keys.json` (laptop, which also needs `pip install cryptography`).
3. **For each notice**, run `scripts/sign-notice.py sign --key ... --title ... --text ... --urgent`
   and paste the output in the admin page. Signed notices expire (24 hours by default, 7 days at
   most) and can't be published twice.

`--require-signed` makes a Campanile refuse unsigned official notices.

### Official alerts in CAP

CAP (Common Alerting Protocol) is the standard format for public warnings, used by IT-alert and
Italian civil protection. Their Italian profiles only add rules to CAP 1.1 and 1.2.

On the admin page, **Load an official alert (CAP)** turns an alert file into a notice. It uses
the admin page's language when the alert has it, turns red if severe or extreme, shows the
issuer's name, and disappears when the alert expires. Tested on the eight messages IT-alert has
published ([pcm-dpc/IT-alert-Hub](https://github.com/pcm-dpc/IT-alert-Hub), all public tests, so
refused as exercises, and read in full once marked as real) and on five real alerts of the Italian
Air Force's weather service.

The reader is small and strict. Always saying why, it refuses any DTD or entity (how XML files
attack their reader), files over 512 kB, exercises, tests, cancellations, alerts not meant for
the public, expired ones and the same alert twice.

**What it doesn't do.** It doesn't check the alert's own digital signature, so the issuer shown is
the one the file names, trusted because the Campanile's admin loaded it. It doesn't receive alerts
by itself.

### Handing over the "I'm safe" names (PFIF)

After an emergency, the names can go to whoever gathers news of missing people. **Export the names
(PFIF)** saves a PFIF 1.4 file, the format born after Hurricane Katrina and used by Google Person
Finder after the Haiti and Japan earthquakes. Each record says it is not verified, since anyone
can register any name. The codes that remove a name and the phones' tags never leave. The file
holds names, messages and places, so it is personal data, only for those who need it.
