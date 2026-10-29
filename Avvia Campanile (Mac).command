#!/bin/bash
# DEVELOPED BY CARROTSTUDIO software house
# Double click on a Mac to start Campanile on this computer.
cd "$(dirname "$0")" || exit 1

# On a new Mac, python3 is only Apple's placeholder: it offers to install the developer
# tools and fails. A candidate counts only if it really runs Python 3.9 or newer.
if ! python3 -c 'import sys; sys.exit(sys.version_info < (3, 9))' >/dev/null 2>&1; then
  echo
  if [ -d tools/python ]; then  # a copy from a USB stick brings Python's official installer
    echo "  Serve Python 3: e' gia' qui, nella cartella tools/python."
    echo "  Fai doppio clic sul file .pkg, poi di nuovo doppio clic qui."
    echo
    echo "  Python 3 is needed: it's right here, in the folder tools/python."
    echo "  Double-click the .pkg file, then double-click here again."
    echo
    open tools/python
    read -r -p "  Premi Invio per chiudere / Press Enter to close. "
    exit 1
  fi
  echo "  Serve Python 3, gratuito: https://www.python.org/downloads/"
  echo "  Se il Mac propone di installare gli strumenti per sviluppatori, puoi anche accettare."
  echo "  Poi fai di nuovo doppio clic qui."
  echo
  echo "  Python 3 is needed, free: https://www.python.org/downloads/"
  echo "  If the Mac offers to install the developer tools, accepting works too."
  echo "  Then double-click here again."
  echo
  read -r -p "  Premi Invio per chiudere / Press Enter to close. "
  exit 1
fi
python3 campanile/launch.py
read -r -p "  Campanile spento / Campanile is off. Premi Invio per chiudere / Press Enter to close. "
