#!/usr/bin/env python3

"""Skript um Ergebnisdateien von Wahlen zu verifizieren.

Dies kann auf keine anderen Dateien der CdEDB zugreifen, weshalb wir
eine gewisse unvermeidbare Duplikation haben.
"""

import argparse
import hmac
import json

def encrypt_vote(salt, secret, vote):
    """Berechne Hash zum Datensatz einer Stimme."""
    h = hmac.new(salt.encode('ascii'), digestmod="sha512")
    h.update(secret.encode('ascii'))
    h.update(vote.encode('ascii'))
    return h.hexdigest()

def retrieve_vote(votes, secret):
    """Ermittle Stimme, die mit dem Geheimnis abgegeben wurde."""
    for v in votes:
        if v['hash'] == encrypt_vote(v['salt'], secret, v['vote']):
            return v
    return None

if __name__ == "__main__":
    ## Analysiere Kommandozeilenargumente
    parser = argparse.ArgumentParser(
        description='Verifiziere die eigene Stimme in Ergebnisdateien.')
    parser.add_argument('secret', help="persönliches Geheimnis")
    parser.add_argument('results', help="Pfad zu Ergebnisdateien", nargs='+')
    args = parser.parse_args()

    ## Iteriere durch Ergebnisdateien ...
    for path in args.results:
        with open(path, encoding='UTF-8') as f:
            data = json.load(f)
        print("Versammlung: {}".format(data['assembly']))
        print("Abstimmung: {}".format(data['ballot']))
        candidates = ", ".join(
            "{} ({})".format(value, key)
            for key, value in sorted(data['candidates'].items()))
        print("Optionen: {}".format(candidates))
        ## ... und ermittle die eigene Stimme
        vote = retrieve_vote(data['votes'], args.secret)
        if vote:
            print("Eigene Stimme: {}".format(vote['vote']))
        else:
            print("Keine Stimme abgegeben")
        print(80*"-")
