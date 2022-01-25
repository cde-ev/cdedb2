#!/usr/bin/env python3

"""Skript um die Auszählung in Ergebnisdateien von Wahlen zu verifizieren.

Dieses Skript kann direkt ausgeführt werden, benötigt dann allerdings das
Paket schulze_condorcet von PyPI. Die CdEDB stellt dieses Skript als Zipapp
zur Verfügung, die das Paket schulze_condorcet direkt mitbringt und keine
weiteren Abhängigkeiten hat.
"""

import argparse
import json
import pathlib

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
            print(f"Datei {path} nicht gefunden")
            continue
        with open(path, encoding='UTF-8') as f:
            data = json.load(f)
        if not first:
            print("\n")
        first = False
        print(f"Versammlung: {data['assembly']}")
        print(f"Abstimmung: {data['ballot']}")
        candidates = "\n          ".join(
            f"{value} ({key})" for key, value in sorted(data['candidates'].items()))
        print(f"Optionen: {candidates}")

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
                  f" {level['rejected']}")
            announce = "       "
            pro = [f"{key}: {value}" for key, value in level['support'].items()]
            con = [f"{key}: {value}" for key, value in level['opposition'].items()]
            print(f"{announce}   mit {', '.join(pro)} Pro")
            print(f"{announce}   und {', '.join(con)} Contra Stimmen.")

        print(f"Ergebnis: {condensed_result}")
        if condensed_result != data['result']:
            print(f"Übereinstimmung: NEIN ({data['result']})")
        else:
            print("Übereinstimmung: ja")
