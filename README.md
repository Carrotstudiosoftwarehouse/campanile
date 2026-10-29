<p align="right"><b>English</b> · <a href="README.it.md">Italiano</a></p>

<h1>
  <picture>
    <source media="(prefers-color-scheme: dark)" srcset="docs/immagini/campanile-logo-bianco.svg">
    <img src="docs/immagini/campanile-logo.svg" height="96" alt="Campanile. No internet. Still together.">
  </picture>
</h1>

[![Tests](https://github.com/Carrotstudiosoftwarehouse/campanile/actions/workflows/ci.yml/badge.svg)](https://github.com/Carrotstudiosoftwarehouse/campanile/actions/workflows/ci.yml) [![Release](https://img.shields.io/github/v/release/Carrotstudiosoftwarehouse/campanile)](https://github.com/Carrotstudiosoftwarehouse/campanile/releases) [![License: MIT](https://img.shields.io/badge/license-MIT-blue)](LICENSE)

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
| **"I need / I can give" board** | Water, food, medicine, power, shelter, rides: neighbors ask and offer. At the top of "I need": in danger, call the emergency number; the board is not one. |
| **Offline medicine** | Wikipedia's medical articles, through Kiwix. |
| **Offline map** | Your area street by street. Search, or tap **Hospital, Pharmacy, Water, Police** for the nearest. |
| **Navigator** | The way there, on foot or by car, around the streets marked as blocked. |
| **Family plan** | Meeting points, contacts and medicines: filled in beforehand and printed. |
| **Look for someone** | At the bottom of the home page: whoever is safe leaves their name, whoever is looking for someone finds it. |

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
[talking with no network](docs/RADIO.md) (radios and apps for families) ·
[running it](docs/ADMIN.md) (notices, moderation, signed notices, CAP alerts, PFIF) ·
[the navigator and the encyclopedia](docs/FEATURES.md) · [security](docs/THREAT-MODEL.md) ·
[how it was tested](docs/TESTING.md) · [roadmap](ROADMAP.md)

## What it is not

- **Not a replacement for emergency services.** In danger, call your emergency number (112 in
  Europe, 911 in North America) if the phone network works.
- **Not private.** The network is open: everything posted is public to whoever is connected.
- **Not for a whole city.** It covers a block, a square or a gym.
- **Not yet safe from a fake "Campanile"** with the same Wi-Fi name: HTTPS for each Campanile is
  the first open problem on the [roadmap](ROADMAP.md).
- **A civil project**, for neighborhoods, volunteers and civil protection: no tool for secret or
  military communication.

## Build it with us

> **Want to help?** We're building a community of engineers, ethical hackers and everyday people
> to test Campanile on real devices and bring it to more neighborhoods.
>
> Write to **[info@carrotstudio.it](mailto:info@carrotstudio.it)**: tell us who you are and what you'd like to try.

No title or permission needed. One rule: it has to be simple enough for our own parents. If it
takes an engineer to use Campanile, we're not done.

- **Not technical?** Try it with family or friends and tell us where you got stuck.
- **Technical?** Start from [CONTRIBUTING.md](CONTRIBUTING.md) and what we couldn't test yet,
  in [docs/LIMITS.md](docs/LIMITS.md).
- **Security researcher?** Try to break it, and report privately: [SECURITY.md](SECURITY.md).

Like a fire extinguisher: you set it up calmly and hope you never need it.

## Friends

Small projects with the same idea: helping people when the internet is gone. Each belongs to its
own authors; we link them because together they reach further. Built something like this? Tell
us, and it goes here.

- **[OFFGRID](https://github.com/lyle-leif/OFFGRID)**: an offline map and an AI assistant that runs
  on a laptop, for Batangas, in the Philippines.
- **[Prometheus Station](https://github.com/Guillain-RDCDE/Prometheus-Station)**: a battery box that
  serves all of Wikipedia with no internet and no network.
- **[ConnectBox](https://github.com/ConnectBox/connectbox-pi)**: a Raspberry Pi that shares media
  offline. Their [offline captive portal](https://github.com/ConnectBox/simple-offline-captive-portal)
  taught us how Android phones behave on a Wi-Fi with no internet.
- **[PirateBox](https://github.com/teklynk/piratebox)**: a Raspberry Pi as an offline, anonymous
  file-sharing hotspot, brought back to life.
- **[MeshBoard](https://github.com/VeggieVampire/MeshBoard)**: a bulletin board over Meshtastic radios.
- **[Algeria Fire Map](https://github.com/MoussaabBadla/algeria-fire-map)**: live satellite wildfire
  monitoring for Algeria.
- **[Donde Ayudo CL](https://github.com/P1ngu-Dev/Donde-Ayudo-CL)**: an offline-first map of aid
  points during emergencies in Chile.
- **[RangerTrak](https://github.com/SteadyEOC/RangerTrak)**: a map of where emergency field teams
  are and how they are doing, built from what they report by radio. Runs in the browser, no
  internet needed.

## How it is built

Made by CarrotStudio, with the help of an AI coding assistant. Every change is tested, and what
we checked is written down in [docs/TESTING.md](docs/TESTING.md).

## Licenses

Code: [MIT](LICENSE). Maps, Wikipedia and the libraries we use keep their own licenses: [the list](docs/SETUP.md#licenses).
