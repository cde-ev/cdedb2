#!/usr/bin/env python3

"""Skript um Stimmen in Ergebnisdateien von Wahlen zu verifizieren.

Dies kann auf keine anderen Dateien der CdEDB zugreifen, weshalb wir
eine gewisse unvermeidbare Duplikation haben.
"""

import argparse
import hmac
import json
import pathlib
from typing import Collection, Dict, Optional


def encrypt_vote(salt: str, secret: str, vote: str) -> str:
    """Berechne Hash zum Datensatz einer Stimme."""
    h = hmac.new(salt.encode('ascii'), digestmod="sha512")
    h.update(secret.encode('ascii'))
    h.update(vote.encode('ascii'))
    return h.hexdigest()


def retrieve_vote(votes: Collection[Dict[str,str]], secret: str
                  ) -> Optional[Dict[str,str]]:
    """Ermittle Stimme, die mit dem Geheimnis abgegeben wurde."""
    for v in votes:
        if v['hash'] == encrypt_vote(v['salt'], secret, v['vote']):
            return v
    return None


if __name__ == "__main__":
    # Analysiere Kommandozeilenargumente
    parser = argparse.ArgumentParser(
        description='Verifiziere die eigene Stimme in Ergebnisdateien.')
    parser.add_argument('secret', help="persönliches Geheimnis")
    parser.add_argument('results', help="Pfad zu Ergebnisdateien", nargs='+')
    args = parser.parse_args()

    # Iteriere durch Ergebnisdateien ...
    first = True
    for path in args.results:
        path = pathlib.Path(path)
        if not path.exists():
            print("Datei {} nicht gefunden".format(path))
            continue
        with open(path, encoding='UTF-8') as f:
            data = json.load(f)
        if not first:
            print("\n")
        first = False
        print("Versammlung: {}".format(data['assembly']))
        print("Abstimmung: {}".format(data['ballot']))
        candidates = ", ".join(
            "{} ({})".format(value, key)
            for key, value in sorted(data['candidates'].items()))
        print("Optionen: {}".format(candidates))
        # ... und ermittle die eigene Stimme
        vote_dict = retrieve_vote(data['votes'], args.secret)
        if not vote_dict:
            vote = "Keine Stimme abgegeben"
        else:
            vote = vote_dict['vote']
        print("Eigene Stimme: {}".format(vote))
