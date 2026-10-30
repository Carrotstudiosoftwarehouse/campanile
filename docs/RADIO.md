<p align="right"><b>English</b> · <a href="COMUNICARE.md">Italiano</a></p>

# Talking when there is no network

Campanile is a public neighborhood board, not a private messaging system. To talk with your family
or a group when the internet and the phone network are down, there are ready-made tools.

General rule: **every radio transmission can be located.** Someone with the right equipment (a
direction finder) can tell where you are transmitting from, encrypted or not. Keep it in mind in
a conflict.

## Briar: messages between Android phones, with no internet

[Briar](https://briarproject.org) is a free, open-source messaging app. With no internet it
passes messages over **Bluetooth or Wi-Fi** between nearby phones; with internet it goes through
the Tor network. Messages are encrypted and go through no central server.

- **Android only** (Google Play or F-Droid). Asked about an iPhone version, the project's FAQ
  answers "probably not", because of the limits iOS puts on apps in the background
  ([FAQ](https://code.briarproject.org/briar/briar/-/wikis/FAQ)).
- Range: that of Bluetooth and Wi-Fi, a few tens of meters.
- Contacts are added in person (QR code) or through a contact in common: **do it beforehand**.

## Meshtastic: text messages over kilometers

[Meshtastic](https://meshtastic.org) uses small **LoRa** radios (from about 30-40 euros) paired
with a phone over Bluetooth. Each radio repeats the others' messages, so the network grows by
itself: in open country it covers kilometers. Only short text messages.

In Europe it uses the **EU_868** region: 869.4-869.65 MHz, at most 27 dBm (500 mW), transmitting
at most 10% of the time ([documentation](https://meshtastic.org/docs/configuration/radio/lora/)).

**Mind the privacy:**

- The **default channel uses a public key**, built into Meshtastic's code: anyone can read
  those messages. For a private group, create a channel with a random key
  (`meshtastic --ch-set psk random --ch-index 1`) and share it in person
  ([documentation](https://meshtastic.org/docs/configuration/radio/channels/)).
- Direct messages between two people are encrypted with a key only the two of them can work out.
- Packet headers are **never encrypted** (they are needed to repeat the packets), and
  Meshtastic has **no forward secrecy**: whoever records the traffic and later gets the key can
  read it all ([documentation](https://meshtastic.org/docs/overview/encryption/)).

## PMR446 radios: voice, no license

**PMR446** radios are the classic walkie-talkies sold in pairs. No internet, credit or phone
needed: press and talk.

- Band 446.0-446.2 MHz, 16 channels, at most 500 mW and a built-in antenna. Repeaters and fixed
  stations are not allowed.
- In Italy they are **free to use**: no license and no fee (art. 105 of the Electronic
  Communications Code). Non-approved devices and modifications, such as a different antenna or
  more power, are not allowed. Check the rules in your country.
- Range: from a few hundred meters in a city to a few kilometers in open country.
- **No privacy:** anyone tuned to the same channel can listen.

## In practice

| Need | Tool |
|---|---|
| Know what is happening in the neighborhood, ask for and offer help | **Campanile** |
| Private messages with family nearby, Android only | **Briar** |
| Text messages over kilometers, iPhone too | **Meshtastic** (with a private channel) |
| Talk by voice with people nearby | **PMR446** |

They all need the same thing: **getting ready beforehand**. Install the app, add the contacts,
charge the batteries, agree on a channel and try it.
