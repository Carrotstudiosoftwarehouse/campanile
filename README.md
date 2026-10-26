<p align="right"><b>English</b> · <a href="README.it.md">Italiano</a></p>

# Campanile

### No internet. Still together.

A neighborhood information and help point that keeps working when the internet is gone. For
centuries the bells of the campanile, the Italian bell tower, warned the village of danger and
called everyone together: Campanile does the same when the network goes down.

> [!WARNING]
> **Version 0.1 is experimental.** Tested on Mac, Windows and Linux and in one field test with no
> internet at all; not yet on a real Raspberry Pi, with a crowd of phones, or by an external
> security audit. Don't rely on it alone. Our limits, honestly: [docs/LIMITS.md](docs/LIMITS.md).

<p align="center">
  <img src="docs/immagini/campanile.gif" width="600" alt="Campanile with no internet: official notices, asking the neighbors for help, I'm safe, the offline map and the nearest pharmacy, a route around a closed street, offline medicine">
</p>
<p align="center"><em>Shown here on a computer: the pages are made for phones and work on any screen.</em></p>

## What it does

A laptop or a Raspberry Pi becomes a small Wi-Fi network for the neighborhood. Anyone joins with
their own phone, with no app, no account and no mobile credit, and finds:

| | |
|---|---|
| **Official notices** | Whoever runs the Campanile (town hall, civil protection, volunteers) posts where water is handed out, where a shelter opens, what to avoid. Official alerts in CAP, IT-alert's format, can be loaded too. |
| **"I need / I can help" board** | Water, food, medicine, power, shelter, rides: neighbors ask and offer. |
| **"I'm safe"** | Leave your name for whoever is looking for you, or search for someone. |
| **Offline map** | Your area street by street. Search, or tap **Hospital, Pharmacy, Water, Police** for the nearest. |
| **Navigator** | The way there, on foot or by car, around the streets marked as blocked. |
| **Offline medicine** | Wikipedia's medical articles, through Kiwix. |
| **Family plan** | Meeting points, contacts and medicines: filled in beforehand and printed. |

Pages in English and Italian, picked from the phone's language. Maps for any area of the world.

## Turn it on

**On a laptop**, with [Python 3](https://www.python.org/downloads/):

1. Download the package from [Releases](https://github.com/Carrotstudiosoftwarehouse/campanile/releases) and unzip it.
2. Double-click **Avvia Campanile (Mac)** or **Avvia Campanile (Windows)**.
3. The first time, with internet, the setup page downloads the map and the medical articles.
4. Print the sign: its QR code opens the Campanile.
5. Everyone joins the same Wi-Fi. With no internet, an Android phone's hotspot can make it.

**On a Raspberry Pi**, a fixed station that makes its own Wi-Fi and opens the portal by itself:
[Raspberry Pi setup](docs/SETUP.md#raspberry-pi).

**More:** [setting up](docs/SETUP.md) (maps, Wikipedia, USB sticks, power) ·
[running it](docs/ADMIN.md) (notices, moderation, signed notices, CAP alerts, PFIF) ·
[the navigator and the encyclopedia](docs/FEATURES.md) · [security](docs/THREAT-MODEL.md) ·
[how it was tested](docs/TESTING.md) · [roadmap](ROADMAP.md)

## What it is not

- **Not a replacement for emergency services.** In danger, call 112 if the phone network works.
- **Not private.** The network is open: everything posted is public to whoever is connected.
- **Not for a whole city.** It covers a block, a square or a gym.
- **Not yet safe from a fake "Campanile"** with the same Wi-Fi name: HTTPS for each Campanile is
  the first open problem on the [roadmap](ROADMAP.md).
- **A civil project**, for neighborhoods, volunteers and civil protection: no tool for secret or
  military communication.

## Build it with us

Engineers, ethical hackers, volunteers, anyone: no title or permission needed. One rule: it has to
be simple enough for our own parents. If it takes an engineer to use Campanile, we're not done.

- **Not technical?** Try it with family or friends and tell us where you got stuck.
- **Technical?** Start from [CONTRIBUTING.md](CONTRIBUTING.md) and what we couldn't test yet,
  in [docs/LIMITS.md](docs/LIMITS.md).
- **Security researcher?** Try to break it, and report privately: [SECURITY.md](SECURITY.md).

Like a fire extinguisher: you set it up calmly and hope you never need it.

## How it is built

Made by CarrotStudio, with the help of an AI coding assistant. Every change is tested, and what
we checked is written down in [docs/TESTING.md](docs/TESTING.md).

## Licenses

Code: [MIT](LICENSE). Maps, Wikipedia and the libraries we use keep their own licenses: [the list](docs/SETUP.md#licenses).
