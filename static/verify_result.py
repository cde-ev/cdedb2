#!/usr/bin/env python3

"""Skript um die Auszählung in Ergebnisdateien von Wahlen zu verifizieren.

Dies kann auf keine anderen Dateien der CdEDB zugreifen, weshalb wir
eine gewisse unvermeidbare Duplikation haben.
"""

import argparse
import json
import pathlib

# TODO use zipapp so the user is not forced to install a package from pip
from schulze_condorcet import schulze_evaluate, schulze_evaluate_detailed


if __name__ == "__main__":
    # Analysiere Kommandozeilenargumente
    parser = argparse.ArgumentParser(
        description='Verifiziere die Auszählung in Ergebnisdateien.')
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
        candidates = "\n          ".join(
            "{} ({})".format(value, key)
            for key, value in sorted(data['candidates'].items()))
        print("Optionen: {}".format(candidates))

        # ... und zähle neu aus
        votes = [entry['vote'] for entry in data['votes']]
        shortnames = list(data['candidates'])
        if data['use_bar']:
            shortnames.append("_bar_")
        condensed_result = schulze_evaluate(votes, shortnames)
        detailed_result = schulze_evaluate_detailed(votes, shortnames)

        # zeige schließlich die Ergebnisse an
        announce = "Detail:"
        for level in detailed_result:
            print(f"{announce} Optionen {level['preferred']} bekamen mehr Stimmen als"
                  f" {level['rejected']} mit {level['support']} Pro und"
                  f" {level['opposition']} Contra Stimmen.")
            announce = "       "

        print("Ergebnis: {}".format(condensed))
        if condensed != data['result']:
            print("Übereinstimmung: NEIN ({})".format(data['result']))
        else:
            print("Übereinstimmung: ja")
