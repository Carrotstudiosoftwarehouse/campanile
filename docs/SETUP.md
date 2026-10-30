<p align="right"><b>English</b> · <a href="INSTALLAZIONE.md">Italiano</a></p>

# Setting up Campanile

Two ways to run it: on a laptop, or on a [Raspberry Pi](#raspberry-pi) as a fixed station.

## On a laptop (the simplest)

You need **Python 3**, free from [python.org](https://www.python.org/downloads/). On Windows,
tick *"Add python.exe to PATH"*. On a Mac, the developer tools macOS offers work too. If Python
is missing, the launcher says what to do.

1. Download the **ready-to-use package** from [Releases](https://github.com/Carrotstudiosoftwarehouse/campanile/releases) and unzip it.
2. Double-click **Avvia Campanile (Mac)** or **Avvia Campanile (Windows)** (*avvia* is Italian
   for *start*). Its window speaks the computer's language, Italian or English.
3. The **setup page** opens the first time. With internet, download the map and the medical
   articles, one click each.
4. Print the **sign** (its QR code has the address) and the one-page
   [guide](../campanile/web/guide.html) for whoever runs it.
5. Keep the black window open. Closing it turns the Campanile off.

Everyone joins **the same Wi-Fi** as the laptop. Without internet, turn on an Android phone's
**hotspot** (usually fine without SIM or mobile data) and connect the laptop and everyone to it.
*Test it first with two phones. In our test an iPhone needed mobile data, an Android did not.
Some carriers or models block it.*

> **First launch.** Answer **Allow** when macOS or Windows asks about Python's network
> connections. A Mac asks again for **kiwix-serve** (offline Wikipedia). **Allow** it too, or
> phones can't open Wikipedia.
> - Pressed *Deny* on a Mac: *System Settings → Network → Firewall → Options*.
> - Pressed *Cancel* on Windows: after a minute the black window says so, and Enter fixes it.
> - Mac won't open `Avvia Campanile (Mac).command`: *System Settings → Privacy & Security → Open Anyway*.

## Prepare it beforehand, while the internet still works

**On a laptop**, the setup page (`http://localhost:8080/setup.html`, opens by itself the first
time) downloads the world map, your area in full detail (framed on your location if the browser
can tell, or search your town) and Wikipedia's medical articles in Italian, English or both.
Downloads resume if cut. Programs and Wikipedia are checked by SHA-256 (pinned in the code, and
Kiwix's own), maps by their structure.

<p align="center">
  <img src="immagini/setup.png" width="600" alt="Setup page: the area to download, framed where the computer is">
</p>

**From the terminal**, in the Campanile folder, with internet, once:

```bash
scripts/prepare.sh                        # libraries (already in the ready-to-use package)
scripts/download-map.sh custom area WEST,SOUTH,EAST,NORTH   # your area, see below
scripts/download-map.sh world             # the whole world, ~190 MB
scripts/download-wikipedia.sh medicine-light en   # medical articles in English, ~1 GB
```

### Your area, in detail

Street search, the nearest hospital, pharmacy or water, and the navigator work only on a map of
your town and its surroundings, up to about 30 km across. On the world map and the maps of Italy,
search finds only towns.

To get its four numbers, open [openstreetmap.org](https://www.openstreetmap.org), find your town
and zoom until the screen shows it with its surroundings. Press **Export** at the top: four
numbers appear, placed like the sides of the screen. West is on the left, east on the right,
north at the top and south at the bottom. Central Turin is `7.64,45.04,7.71,45.09`, about 7 MB.
A 30 km square around Turin is about 23 MB.

| Maps (`download-map.sh`) | Size | Detail |
|---|---|---|
| `custom NAME WEST,SOUTH,EAST,NORTH` | depends | your area, every street: search and navigator |
| `world` | ~190 MB | countries, cities and main roads of the whole world |
| `italy-light` | ~580 MB | roads across Italy, to look at |
| `italy` | ~4.5 GB | every street and building, to look at: too big for search and navigator |

| Wikipedia (`download-wikipedia.sh`) | Size in Italian |
|---|---|
| `medicine-light` (no images) | ~100 MB |
| `medicine` | ~260 MB |
| `essential` (most-read articles, no images) | ~900 MB |
| `full` (no images) | ~8.4 GB |
| `full-images` | ~30 GB |

Sizes measured on 22-24 October 2026. The word after the package is the language: `it` (the
default), `en`, `de`, `fr`, `uk`... English is bigger: `medicine-light en` is about 1 GB, as on the
setup page. Wikipedia starts by itself. On a laptop, first press an *Offline medicine* button on the
setup page once, to add the program that serves it.

Map search indexes each map once, in the background, into `data/places/`. It finds streets,
places and useful points (hospitals, pharmacies, drinking water...) in your area, countries and
cities in the world map.

**Then** fill in the family plan and test with a couple of phones. Print the sign early only for a
Raspberry, whose hotspot address doesn't change. A laptop's address changes with the network, so
print its sign (or copy the address by hand) once the day's network is up.

## More Campaniles, without internet

On the setup page, *More Campaniles*:

1. **Prepare for every computer** (with internet, once, about 250 MB) gets Wikipedia's server for
   Windows, Mac and Linux, and Python's official installers.
2. Plug in a USB stick and press **Copy to the stick** (program, maps and Wikipedia).

On the stick, double-click *Avvia Campanile*. No internet needed: if Python is missing, the
window points to its installer on the stick.

- **Hand the stick over in person.** Never install a program from a Wi-Fi network: anyone can
  name one "Campanile".
- **Never on the stick:** the database (names, posts, contacts), the admin password, anything not
  on a fixed list.
- **No stowaways.** A Campanile folder already on the stick is used only if it holds nothing but
  Campanile's files. Anything else stops the copy, untouched, and links are never followed.
  Tested against every way we know to hide a program there.
- On a Raspberry, from the terminal, with the stick's folder in place of `/media/usb`:
  `sudo python3 /opt/campanile/campanile/copying.py /media/usb --data /var/lib/campanile --keys /etc/campanile/trusted-keys.json`.
  That stick has the program, maps and Wikipedia, not Python's installers nor the Wikipedia
  server for laptops: those come from a laptop's *Prepare for every computer*.

**Updating from a stick.** On the setup page, plug in a stick with a newer Campanile and press
**Update from this stick**. It is copied next to this Campanile and checked there: only a newer
version signed by CarrotStudio passes. Close the black window and open Campanile again: before
starting, it checks once more, then the new version becomes a folder of its own, "Campanile
0.2.0", and maps, Wikipedia and posts move into it. The old double click keeps working. On a
Raspberry: `sudo python3 /opt/campanile/campanile/update.py /media/USER/STICK` checks the stick the
same way, then runs the new version's installer with the choices of last time (so far tried with
a stand-in installer).

**Maps and Wikipedia over Wi-Fi.** On the admin page, *Share with another Campanile* shows an
address and a code. Another Campanile joins this Wi-Fi and types both on its setup page. Maps and
Wikipedia arrive, never programs. The file list is signed with the code, so a fake Campanile with
the same network name but no code is refused. Downloads are paced to leave room for phones, and
sharing stops after two hours.

## Keeping it powered

> **hours of runtime ≈ battery capacity in Wh × 0.8 ÷ consumption in watts**
> (power bank mAh × 3.7 ÷ 1000 = Wh)

A 20,000 mAh power bank is about 74 Wh. If it draws 4 W, a Raspberry runs 74 × 0.8 ÷ 4 ≈
**15 hours**. Consumption depends on the model and on how many connect, so **measure it** with a
cheap USB power meter. A foldable 20-30 W USB solar panel can recharge the power bank by day.
Same rules for a laptop, with the screen dimmed.

## Raspberry Pi

It should run on a Raspberry Pi 3B+, 4, 5 or Zero 2 W. Tested in Raspberry Pi OS containers and
on virtual Wi-Fi radios, not yet on a real board. It creates the open Wi-Fi **"Campanile"**:
phones should open the page by themselves (not yet tried with real phones), and the QR code on
the sign opens it too. It can run on a power bank, for how long we haven't measured yet.

You need **Raspberry Pi OS 64-bit**, Lite or with desktop (Bookworm or newer: on 32-bit the map
can't be downloaded on the Pi), a 16 GB card (the lines below take about 1.5 GB), built-in Wi-Fi,
and internet **by cable**: the last step turns the Wi-Fi into the hotspot, so an SSH session over
Wi-Fi would drop there. A Zero 2 W has no network port: use a keyboard and screen, or a USB
network adapter.

First find [your area's four numbers](#your-area-in-detail) and write them in place of
`WEST,SOUTH,EAST,NORTH`, and your country's two letters in place of `XX`. Then paste the whole
block, braces included: they make the shell read every line before running any, so none is lost.

```bash
{
sudo apt update && sudo apt install -y git
[ -d $HOME/campanile ] || git clone https://github.com/Carrotstudiosoftwarehouse/campanile.git $HOME/campanile
cd $HOME/campanile && git pull
scripts/download-map.sh custom area WEST,SOUTH,EAST,NORTH   # your area
scripts/download-map.sh world             # optional, ~190 MB
scripts/download-wikipedia.sh medicine-light en   # optional, in English, ~1 GB
sudo raspberry/install.sh --country XX    # more options: --ssid NAME  --no-hotspot
}
```

Left as they are, `WEST,SOUTH,EAST,NORTH` stops the map line with "Invalid box" (Campanile then
has no street search and no navigator), and `XX` stops the installer before it changes anything.

Pasted again, from any folder, the same lines, options included, retry after a problem, update
Campanile, or add a map or a Wikipedia you write in. Maps and Wikipedia already there aren't
downloaded again; data and password stay. To change your area: `sudo rm
/var/lib/campanile/maps/area.pmtiles`, then paste with the new numbers.

The installer fetches the map libraries itself the first time, and waits if the Raspberry, just
switched on, is still updating itself.

`--country` is your country's two letters, for the Wi-Fi rules (`GB` for the United Kingdom,
`UK` works too). Without it the installer keeps the country already set (Raspberry Pi Imager
sets one along with the Wi-Fi); with none set, it stops before changing anything and says so.

The installer:

- installs `python3`, `python3-cryptography`, `kiwix-tools`, `nginx` and `nftables` from Debian,
  and creates the unprivileged service user `campanile`
- puts the program in `/opt/campanile`, data in `/var/lib/campanile`, configuration in `/etc/campanile`
- puts **nginx** in front of the phones, on port 80 (pages and maps) and 8081 (Wikipedia), so a
  slow or greedy phone can't hold up the others. The app (127.0.0.1:8080) and Wikipedia's server
  (127.0.0.1:8082) listen only inside the Raspberry, restricted by systemd, and start at boot
- creates the **open** Wi-Fi "Campanile" on `10.42.0.1` with NetworkManager, and points every
  domain name to the Campanile
- asks the Wi-Fi chip to keep phones apart (not yet verified on a Pi's own chip). A hotspot
  **firewall** lets them reach only DHCP, DNS, ping and Campanile (ports 80 and 8081), nothing
  else on the Raspberry or behind it

**Network changes:** the NetworkManager connection `campanile-hotspot`,
`/etc/NetworkManager/dnsmasq-shared.d/campanile.conf` (DNS redirect, only while the hotspot is
on), the firewall `/etc/campanile/firewall.nft` with its `campanile-firewall` service. It also
sets the Wi-Fi country you give, and replaces nginx's default site (restored on uninstall).

From a computer on the same cable network, open the Raspberry's address, or the `.local` name the
installer prints, like `http://raspberrypi.local/`.

**To remove Campanile:** `cd $HOME/campanile && sudo raspberry/uninstall.sh` (keeps data and
password), or the same with `--purge` at the end (deletes them too). The packages and the Wi-Fi
country stay; nginx is stopped if it was off before Campanile. The folder you cloned stays too:
`rm -rf $HOME/campanile` removes it.

The built-in Wi-Fi serves a limited number of phones: how many, we haven't measured yet. For a
whole square, use an external access point.

## Licenses

- Campanile's code: [MIT](../LICENSE).
- Downloaded by `scripts/prepare.sh`, each under its own license (copied to
  `campanile/web/vendor/licenses/`): [MapLibre GL JS](https://maplibre.org),
  [PMTiles](https://github.com/protomaps/PMTiles) and
  [Protomaps basemaps](https://github.com/protomaps/basemaps) (BSD-3-Clause), Noto fonts
  (SIL OFL 1.1), [qrcode-generator](https://github.com/kazuhikoarase/qrcode-generator) (MIT),
  [certifi](https://github.com/certifi/python-certifi) (MPL-2.0).
- Downloaded by the setup page: [go-pmtiles](https://github.com/protomaps/go-pmtiles)
  (BSD-3-Clause), [kiwix-tools](https://github.com/kiwix/kiwix-tools) (GPL-3.0).
- Data: maps © [OpenStreetMap](https://www.openstreetmap.org/copyright) (ODbL) with ESA
  WorldCover (CC BY 4.0) via [Protomaps](https://protomaps.com). Wikipedia (CC BY-SA 4.0) via
  [Kiwix](https://kiwix.org).
