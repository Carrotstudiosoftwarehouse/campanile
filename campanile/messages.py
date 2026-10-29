# DEVELOPED BY CARROTSTUDIO software house
"""Messages shown to people, in every language Campanile speaks.

Errors carry a key and parameters; the text is picked when the response is sent, in the
language of the phone (Accept-Language). Add a language by adding a column.
"""

from __future__ import annotations

import locale
import os
import plistlib
import re
import sys
from pathlib import Path
from xml.parsers.expat import ExpatError

LANGUAGES = ("it", "en")
DEFAULT = "it"
# For a phone in a language we don't have yet, English is understood by more people.
FALLBACK = "en"

FIELDS = {
    "description": {"it": "descrizione", "en": "description"},
    "area": {"it": "zona", "en": "area"},
    "contact": {"it": "contatto", "en": "contact"},
    "name": {"it": "nome", "en": "name"},
    "search": {"it": "ricerca", "en": "search"},
    "message": {"it": "messaggio", "en": "message"},
    "place": {"it": "luogo", "en": "place"},
    "code": {"it": "codice", "en": "code"},
    "title": {"it": "titolo", "en": "title"},
    "text": {"it": "testo", "en": "text"},
    "note": {"it": "nota", "en": "note"},
    "source": {"it": "fonte", "en": "source"},
}

MESSAGES = {
    # input
    "field_not_text": {
        "it": "Il campo '{field}' deve essere testo.",
        "en": "The field '{field}' must be text.",
    },
    "field_required": {
        "it": "Il campo '{field}' è obbligatorio.",
        "en": "The field '{field}' is required.",
    },
    "field_too_long": {
        "it": "Il campo '{field}' supera i {max} caratteri.",
        "en": "The field '{field}' is longer than {max} characters.",
    },
    "bad_number": {"it": "Numero non valido.", "en": "Invalid number."},
    "bad_kind": {"it": "Tipo non valido.", "en": "Invalid type."},
    "choose_kind": {"it": "Scegli 'offro' o 'cerco'.", "en": "Choose 'I offer' or 'I need'."},
    "bad_category": {"it": "Categoria non valida.", "en": "Invalid category."},
    "name_too_short": {"it": "Il nome è troppo corto.", "en": "The name is too short."},
    "search_too_short": {
        "it": "Scrivi almeno 2 lettere del nome da cercare.",
        "en": "Type at least 2 letters of the name.",
    },
    # requests
    "method_not_allowed": {"it": "Metodo non consentito.", "en": "Method not allowed."},
    "not_found": {"it": "Non trovato.", "en": "Not found."},
    "map_not_found": {"it": "Mappa non trovata.", "en": "Map not found."},
    "unknown_api": {"it": "Percorso API sconosciuto.", "en": "Unknown API path."},
    "need_json": {
        "it": "Serve Content-Type: application/json.",
        "en": "Content-Type: application/json is required.",
    },
    "need_length": {"it": "Serve Content-Length.", "en": "Content-Length is required."},
    "bad_framing": {
        "it": "Corpo della richiesta non accettato.",
        "en": "Request body not accepted.",
    },
    "too_large": {"it": "Richiesta troppo grande.", "en": "Request too large."},
    "incomplete": {"it": "Richiesta incompleta.", "en": "Incomplete request."},
    "bad_json": {"it": "JSON non valido.", "en": "Invalid JSON."},
    "need_object": {"it": "Serve un oggetto JSON.", "en": "A JSON object is required."},
    "internal": {"it": "Errore interno del Campanile.", "en": "Internal Campanile error."},
    "disk_full": {
        "it": "Il Campanile ha finito lo spazio su disco: chi lo gestisce deve liberarne. "
        "Tutto si può ancora leggere.",
        "en": "The Campanile is out of disk space: whoever runs it must free some. "
        "Everything can still be read.",
    },
    # limits
    "too_many_writes": {
        "it": "Troppe pubblicazioni da questo dispositivo. Riprova tra qualche minuto.",
        "en": "Too many posts from this device. Try again in a few minutes.",
    },
    "too_many_wrong": {
        "it": "Troppi tentativi sbagliati. Riprova più tardi.",
        "en": "Too many wrong attempts. Try again later.",
    },
    "device_open_posts": {
        "it": "Hai già {count} annunci aperti: chiudine uno prima di pubblicarne altri.",
        "en": "You already have {count} open posts: close one before posting more.",
    },
    "device_names": {
        "it": "Da questo telefono sono già stati registrati {count} nomi.",
        "en": "{count} names have already been registered from this phone.",
    },
    "board_full": {
        "it": "La bacheca è piena. Chiedi a chi gestisce il Campanile "
        "di togliere gli annunci superati.",
        "en": "The board is full. Ask whoever runs this Campanile to remove outdated posts.",
    },
    "board_full_admin": {
        "it": "La bacheca è piena: togli prima gli annunci superati.",
        "en": "The board is full: remove outdated posts first.",
    },
    "pending_full": {
        "it": "Troppi annunci in attesa di controllo: riprova più tardi.",
        "en": "Too many posts waiting for review: try again later.",
    },
    "registry_full": {
        "it": "Il registro è pieno. Chiedi a chi gestisce il Campanile.",
        "en": "The registry is full. Ask whoever runs this Campanile.",
    },
    "too_many_notices": {
        "it": "Troppi avvisi: togli quelli superati.",
        "en": "Too many notices: remove the outdated ones.",
    },
    # codes
    "already_closed": {"it": "Già chiuso o già tolto.", "en": "Already closed or removed."},
    "wrong_code": {"it": "Numero o codice non corretti.", "en": "Wrong number or code."},
    # admin
    "admin_off": {
        "it": "Gestione disattivata: nessuna password impostata.",
        "en": "Admin is off: no password set.",
    },
    "admin_local_only": {
        "it": "La gestione si usa solo dal Campanile stesso. Vedi docs/GESTIONE.md.",
        "en": "Admin only works from the Campanile itself. See docs/ADMIN.md.",
    },
    "wrong_password": {"it": "Password errata.", "en": "Wrong password."},
    "update_no_program": {
        "it": "Su questa chiavetta non c'è un Campanile da cui aggiornarsi.",
        "en": "There is no Campanile on this stick to update from.",
    },
    "release_unsigned": {
        "it": "Questa copia non ha la firma di CarrotStudio.",
        "en": "This copy has no CarrotStudio signature.",
    },
    "release_unreadable": {
        "it": "La firma di questa copia è illeggibile.",
        "en": "This copy's signature can't be read.",
    },
    "release_unknown_key": {
        "it": "Questa copia è firmata, ma non da CarrotStudio.",
        "en": "This copy is signed, but not by CarrotStudio.",
    },
    "release_tampered": {
        "it": "La firma non corrisponde: la copia è stata modificata.",
        "en": "The signature doesn't match: the copy was changed.",
    },
    "release_files_differ": {
        "it": "Alcuni file non sono quelli firmati: la copia è stata modificata o è incompleta.",
        "en": "Some files aren't the signed ones: the copy was changed or is incomplete.",
    },
    "release_bad_version": {
        "it": "Il numero di versione non è valido.",
        "en": "The version number isn't valid.",
    },
    "release_not_newer": {
        "it": "Questa versione non è più nuova di quella installata.",
        "en": "This version isn't newer than the one installed.",
    },
    "main_password_only": {
        "it": "Solo la password principale aggiunge o toglie le persone.",
        "en": "Only the main password adds or removes people.",
    },
    "admin_name_taken": {
        "it": "C'è già una persona con questo nome.",
        "en": "Someone already has this name.",
    },
    "too_many_admins": {
        "it": "Si possono aggiungere al massimo {max} persone.",
        "en": "You can add at most {max} people.",
    },
    "signed_required": {
        "it": "Su questo Campanile gli avvisi ufficiali devono essere firmati.",
        "en": "On this Campanile official notices must be signed.",
    },
    "pending_not_found": {
        "it": "Annuncio in attesa non trovato.",
        "en": "Post waiting for review not found.",
    },
    "bad_device": {"it": "Dispositivo non valido.", "en": "Invalid device."},
    "bad_minutes": {
        "it": "Minuti non validi (da 1 a 1440).",
        "en": "Invalid minutes (1 to 1440).",
    },
    "item_not_found": {"it": "Voce non trovata.", "en": "Item not found."},
    "bad_table": {"it": "Tipo da eliminare non valido.", "en": "Invalid item type."},
    # setup
    "setup_busy": {
        "it": "Sta già scaricando qualcosa: aspetta che finisca.",
        "en": "Something is already downloading: wait for it to finish.",
    },
    "bad_task": {"it": "Operazione sconosciuta.", "en": "Unknown operation."},
    "bad_area": {
        "it": "Zona non valida o troppo grande: avvicinati sulla mappa.",
        "en": "Invalid or too large area: zoom in on the map.",
    },
    "bad_address": {
        "it": "Indirizzo non valido: scrivi quello dell'altro Campanile, per esempio http://10.42.0.1.",
        "en": "Invalid address: type the other Campanile's, for example http://10.42.0.1.",
    },
    "bad_code": {
        "it": "Codice non valido: sono 16 lettere e cifre.",
        "en": "Invalid code: it is 16 letters and digits.",
    },
    "share_busy": {
        "it": "Questo Campanile sta già passando file: riprova tra poco.",
        "en": "This Campanile is already passing files: try again shortly.",
    },
    "too_many_searches": {
        "it": "Troppe ricerche di fila: aspetta qualche secondo.",
        "en": "Too many searches in a row: wait a few seconds.",
    },
    "unknown_host": {
        "it": "Questo non è l'indirizzo del Campanile: usa quello scritto sul cartello.",
        "en": "This isn't the Campanile's address: use the one on the sign.",
    },
    "too_many_routes": {
        "it": "Troppi percorsi di fila: aspetta qualche secondo.",
        "en": "Too many routes in a row: wait a few seconds.",
    },
    "bad_route": {
        "it": "Servono una partenza, un arrivo e il modo: a piedi o in auto.",
        "en": "A start, a destination and a way are needed: on foot or by car.",
    },
    "route_busy": {
        "it": "Molti percorsi in corso: riprova tra un attimo.",
        "en": "Many routes under way: try again in a moment.",
    },
    "bad_time": {
        "it": "Ora non valida: deve essere entro un anno da quella del computer.",
        "en": "Invalid time: it must be within a year of the computer's.",
    },
    "bad_emergency": {
        "it": "Il numero di emergenza è fatto solo di cifre, da 2 a 6.",
        "en": "The emergency number is digits only, 2 to 6 of them.",
    },
    "route_long": {
        "it": "Percorso troppo lungo da calcolare qui: prova con punti più vicini.",
        "en": "This route is too long to work out here: try nearer points.",
    },
    "route_far": {
        "it": "Questo punto è troppo lontano dalle strade della mappa: tocca vicino a una via.",
        "en": "This point is too far from any street on the map: touch one closer to a street.",
    },
    "route_none": {
        "it": "Nessun percorso fra questi due punti: una strada interrotta, o non sono collegati.",
        "en": "No route between these two points: a street is blocked, or they are not connected.",
    },
    "route_outside": {
        "it": "Il percorso si calcola solo dentro la zona scaricata con ogni dettaglio.",
        "en": "Routes are only found inside the area downloaded in full detail.",
    },
    "route_wait": {
        "it": "Il navigatore si sta preparando: riprova tra qualche secondo.",
        "en": "The navigator is getting ready: try again in a few seconds.",
    },
    "no_street_here": {
        "it": "Qui non c'è una strada: tocca proprio sopra la via da segnare.",
        "en": "There is no street here: touch right on the street to mark.",
    },
    "too_many_closed": {
        "it": "Troppe strade segnate come interrotte: riaprine qualcuna.",
        "en": "Too many streets marked as blocked: reopen some.",
    },
    "search_busy": {
        "it": "Molte ricerche in corso: riprova tra un attimo.",
        "en": "Many searches under way: try again in a moment.",
    },
    "bad_drive": {
        "it": "Chiavetta non trovata: infilala di nuovo.",
        "en": "Drive not found: plug it in again.",
    },
    "bad_language": {"it": "Lingua non disponibile.", "en": "Language not available."},
    # official alerts in CAP
    "cap_too_big": {
        "it": "File troppo grande per un allarme CAP (max {max} kB).",
        "en": "Too big for a CAP alert (max {max} kB).",
    },
    "cap_unsafe": {
        "it": "Il file contiene una DTD o delle entità: un allarme CAP non ne ha mai bisogno.",
        "en": "The file holds a DTD or entities: a CAP alert never needs them, refused.",
    },
    "cap_bad": {
        "it": "Non è un file XML leggibile.",
        "en": "Not a readable XML file.",
    },
    "cap_not_cap": {
        "it": "Non è un allarme CAP 1.1 o 1.2.",
        "en": "Not a CAP 1.1 or 1.2 alert.",
    },
    "cap_missing": {
        "it": "Nell'allarme CAP manca il campo obbligatorio <{field}>.",
        "en": "The CAP alert lacks the required field <{field}>.",
    },
    "cap_bad_value": {
        "it": "Nell'allarme CAP il campo <{field}> ha un valore non previsto dallo standard.",
        "en": "In the CAP alert, <{field}> holds a value the standard doesn't allow.",
    },
    "cap_bad_time": {
        "it": "Nell'allarme CAP la scadenza non è una data valida.",
        "en": "In the CAP alert, the expiry is not a valid date.",
    },
    "cap_exercise": {
        "it": "È un'esercitazione: non viene pubblicata come avviso vero.",
        "en": "It's an exercise: not published as a real notice.",
    },
    "cap_not_actual": {
        "it": "Non è un allarme reale (stato: {state}): non pubblicato.",
        "en": "Not a real alert (status: {state}): not published.",
    },
    "cap_cancel": {
        "it": "Annulla un allarme precedente: togli quell'avviso tra quelli pubblicati.",
        "en": "It cancels an earlier alert: remove that notice from the published ones.",
    },
    "cap_not_alert": {
        "it": "Non è un allarme ma un messaggio di servizio ({kind}): non pubblicato.",
        "en": "Not an alert but a service message ({kind}): not published.",
    },
    "cap_not_public": {
        "it": "Questo allarme non è destinato al pubblico: non pubblicato.",
        "en": "This alert is not meant for the public: not published.",
    },
    "cap_expired": {
        "it": "Questo allarme è già scaduto.",
        "en": "This alert has already expired.",
    },
    "cap_duplicate": {
        "it": "Questo allarme è già stato pubblicato.",
        "en": "This alert has already been published.",
    },
    # signed notices
    "signed_duplicate": {
        "it": "Questo avviso firmato è già stato pubblicato.",
        "en": "This signed notice has already been published.",
    },
    "signed_field_invalid": {
        "it": "Il campo '{field}' dell'avviso firmato contiene caratteri non validi.",
        "en": "The field '{field}' of the signed notice contains invalid characters.",
    },
    "sig_bad_key": {"it": "Firma o chiave non valida.", "en": "Invalid signature or key."},
    "sig_no_keys": {
        "it": "Questo Campanile non ha chiavi di fiducia per gli avvisi firmati.",
        "en": "This Campanile has no trusted keys for signed notices.",
    },
    "sig_format": {
        "it": "Formato dell'avviso firmato non riconosciuto.",
        "en": "Unrecognized signed notice format.",
    },
    "sig_incomplete": {
        "it": "L'avviso firmato è incompleto.",
        "en": "The signed notice is incomplete.",
    },
    "sig_unknown_key": {
        "it": "Firmato con una chiave che questo Campanile non riconosce.",
        "en": "Signed with a key this Campanile doesn't know.",
    },
    "sig_tampered": {
        "it": "La firma non corrisponde: l'avviso è stato alterato.",
        "en": "The signature doesn't match: the notice was altered.",
    },
    "sig_bad_values": {
        "it": "L'avviso firmato contiene valori non validi.",
        "en": "The signed notice contains invalid values.",
    },
    "sig_validity": {
        "it": "La validità dell'avviso deve essere tra pochi minuti e 7 giorni.",
        "en": "A notice must be valid for between a few minutes and 7 days.",
    },
    "sig_expired": {
        "it": "Avviso scaduto secondo l'orologio di questo Campanile. Se l'ora è sbagliata, "
        "correggila prima di riprovare.",
        "en": "The notice has expired according to this Campanile's clock. If the time is wrong, "
        "fix it and try again.",
    },
    "sig_unreadable": {
        "it": "L'avviso firmato non è leggibile.",
        "en": "The signed notice can't be read.",
    },
}


# The black window of a laptop, in the computer's language. Plain ASCII ("e'", not "è"): a
# Windows console may show nothing else. {0}, {1}: what the code fills in.
WINDOW = {
    "on": {
        "it": "CAMPANILE ACCESO. Lascia aperta questa finestra: chiudendola si spegne.",
        "en": "CAMPANILE IS ON. Keep this window open: closing it switches Campanile off.",
    },
    "phones": {
        "it": "Dagli altri telefoni, collegati alla stessa Wi-Fi:  {0}",
        "en": "From other phones, on the same Wi-Fi:  {0}",
    },
    "no_network": {
        "it": "Questo computer non e' collegato a nessuna rete Wi-Fi o via cavo:\n"
        "  gli altri dispositivi non possono ancora raggiungerlo.",
        "en": "This computer is not on any Wi-Fi or wired network:\n"
        "  other devices can't reach it yet.",
    },
    # The list under "on": label and address, lined up.
    "here": {"it": "Da questo computer:", "en": "On this computer:"},
    "admin": {"it": "Gestione e avvisi:", "en": "Admin and notices:"},
    "password": {"it": "Password di gestione:", "en": "Admin password:"},
    "setup": {"it": "Preparazione:", "en": "Setup:"},
    "guide": {"it": "Guida da stampare:", "en": "Guide to print:"},
    "firewall_blocked": {
        "it": "ATTENZIONE: Windows sta bloccando i telefoni, che non possono collegarsi.\n"
        "  (Succede se alla domanda di Windows sulle reti si e' premuto Annulla.)\n"
        "  Premi INVIO per sistemarlo: Windows ti chiedera' il permesso.",
        "en": "WARNING: Windows is blocking the phones, they can't connect.\n"
        "  (It happens if Cancel was pressed when Windows asked about networks.)\n"
        "  Press ENTER to fix it: Windows will ask your permission.",
    },
    "firewall_fixed": {
        "it": "Sistemato: ora i telefoni possono collegarsi.",
        "en": "Fixed: phones can connect now.",
    },
    "firewall_not_fixed": {
        "it": "Non e' stato sistemato. Riprova chiudendo e riaprendo il Campanile,\n"
        "  e a Windows rispondi Si'.",
        "en": "Not fixed. Try again: close and reopen Campanile,\n  and answer Yes to Windows.",
    },
    "not_prepared": {
        "it": "Manca la preparazione iniziale. Con internet, esegui una volta:\n"
        "    scripts/prepare.sh",
        "en": "The first preparation is missing. With internet, run once:\n    scripts/prepare.sh",
    },
    "damaged": {
        "it": "ATTENZIONE: questa copia del Campanile e' incompleta o danneggiata\n"
        "  ({0} file, per esempio {1}).\n"
        "  Rifalla dalla chiavetta originale, o chiedi una chiavetta nuova.",
        "en": "WARNING: this copy of Campanile is incomplete or damaged\n"
        "  ({0} of its files, for example {1}).\n"
        "  Copy it again from the original stick, or ask for a new stick.",
    },
    "port_busy": {
        "it": "Impossibile usare la porta {0}: forse il Campanile e' gia' acceso. ({1})",
        "en": "Can't use port {0}: maybe Campanile is already on. ({1})",
    },
    "updated": {
        "it": 'Campanile aggiornato: parte dalla cartella "{0}".',
        "en": 'Campanile updated: starting from the folder "{0}".',
    },
    "update_discarded": {
        "it": "ATTENZIONE: l'aggiornamento preparato non e' piu' quello firmato da CarrotStudio:\n"
        "  e' stato scartato. Parte la versione di prima.",
        "en": "WARNING: the prepared update is no longer the one CarrotStudio signed:\n"
        "  it was thrown away. The previous version starts.",
    },
    "update_folder_exists": {
        "it": "L'aggiornamento e' pronto, ma qui accanto c'e' gia' una cartella \"{0}\":\n"
        "  spostala altrove e riapri il Campanile. Intanto parte la versione di prima.",
        "en": 'The update is ready, but there is already a folder "{0}" next to this one:\n'
        "  move it elsewhere and reopen Campanile. For now the previous version starts.",
    },
    "update_failed": {
        "it": "L'aggiornamento non e' riuscito: parte la versione di prima.",
        "en": "The update didn't work: the previous version starts.",
    },
    "update_locked": {
        "it": "L'aggiornamento non e' finito (un file in uso?). Chiudi le altre finestre e\n"
        "  riapri il Campanile: riparte da dove si era fermato. Niente e' perso.",
        "en": "The update didn't finish (a file in use?). Close the other windows and\n"
        "  reopen Campanile: it goes on from where it stopped. Nothing is lost.",
    },
    # Why nothing starts: this Campanile would start empty while its data sits elsewhere.
    "update_folder_missing": {
        "it": "Questo Campanile e' stato aggiornato: mappe, Wikipedia e annunci\n"
        "  sono nella cartella \"{0}\", che qui accanto non c'e' piu'. Rimettila accanto e riapri.",
        "en": "This Campanile was updated: maps, Wikipedia and posts are in the\n"
        '  folder "{0}", which is no longer next to this one. Put it back and reopen.',
    },
    "update_unfinished": {
        "it": "Questo e' un aggiornamento non finito: apri il Campanile dalla cartella\n"
        '  "{0}", che lo finisce da sola.',
        "en": "This is an unfinished update: open Campanile from the folder\n"
        '  "{0}", which finishes it by itself.',
    },
    "update_data_twice": {
        "it": 'Ci sono dati sia in "{0}" sia in "{1}": per non perdere niente il\n'
        "  Campanile non parte. Tieni la cartella giusta e sposta altrove l'altra.",
        "en": 'There is data both in "{0}" and in "{1}": so that nothing is lost,\n'
        "  Campanile doesn't start. Keep the right folder and move the other elsewhere.",
    },
    "update_installing": {
        "it": "Campanile {0}, firmato da CarrotStudio: lo installo.",
        "en": "Campanile {0}, signed by CarrotStudio: installing it.",
    },
}


def window(key: str, lang: str, *values) -> str:
    """A line for the black window."""
    return WINDOW[key][lang if lang in LANGUAGES else FALLBACK].format(*values)


def computer_language() -> str:
    """The language of this computer's own window: its first one we speak, else English."""
    for tag in _computer_tags():
        if tag[:2].lower() in LANGUAGES:
            return tag[:2].lower()
    return FALLBACK


def computer_region() -> str:
    """This computer's country, like "US", as its settings say; "" when they don't."""
    for tag in _computer_tags(region=True):
        found = re.match(r"[a-z]{2,3}[-_](?:[a-z]{4}[-_])?([a-z]{2})(?![a-z])", tag, re.I)
        if found:
            return found[1].upper()
    return ""


def _computer_tags(region: bool = False) -> list[str]:
    """Language tags like "it-IT" or "en_US.UTF-8", preferred first. Any source may be missing.

    Windows and the Mac say it in their settings; Linux and Mac terminals in the environment."""
    tags = []
    if sys.platform == "win32":
        try:
            import ctypes

            tags.append(locale.windows_locale[ctypes.windll.kernel32.GetUserDefaultUILanguage()])
        except (AttributeError, OSError, KeyError):
            pass
    if sys.platform == "darwin":
        try:
            with open(Path.home() / "Library/Preferences/.GlobalPreferences.plist", "rb") as f:
                prefs = plistlib.load(f)
            languages = prefs.get("AppleLanguages")
            languages = [str(t) for t in languages] if isinstance(languages, list) else []
            country = [str(prefs.get("AppleLocale", ""))]  # the Region setting
            tags += country + languages if region else languages + country
        # Odd or damaged settings only mean no language from here, never a failed start.
        except (OSError, ValueError, AttributeError, plistlib.InvalidFileException, ExpatError):
            pass
    tags += os.environ.get("LANGUAGE", "").split(":")
    for name in ("LC_ALL", "LC_MESSAGES", "LANG"):  # like gettext: the first one set
        if os.environ.get(name):
            tags.append(os.environ[name])
            break
    return [t for t in tags if t]


def pick_language(accept_language: str | None) -> str:
    """The best language for an Accept-Language header such as 'en-GB,en;q=0.9,it;q=0.8'."""
    if not accept_language:
        return DEFAULT
    ranked = []
    for position, part in enumerate(accept_language.split(",")[:20]):
        tag, _, quality = part.strip().partition(";q=")
        try:
            q = float(quality) if quality else 1.0
        except ValueError:
            q = 0.0
        ranked.append((-q, position, tag.strip().lower()[:2]))
    for _, _, code in sorted(ranked):
        if code in LANGUAGES:
            return code
    return FALLBACK


def text(key: str, lang: str = DEFAULT, **params) -> str:
    lang = lang if lang in LANGUAGES else DEFAULT
    if "field" in params:  # a label not listed is said as it is: never an error
        params["field"] = FIELDS.get(params["field"], {}).get(lang, params["field"])
    return MESSAGES[key][lang].format(**params)
