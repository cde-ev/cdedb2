#!/usr/bin/env python3

"""Skript um die Auszählung in Ergebnisdateien von Wahlen zu verifizieren.

Dies kann auf keine anderen Dateien der CdEDB zugreifen, weshalb wir
eine gewisse unvermeidbare Duplikation haben.
"""

import argparse
import json
import pathlib
from typing import Collection, Container, Dict, List, Mapping, Tuple, Union


def _schulze_winners(d: Mapping[Tuple[str, str], int],
                     candidates: Collection[str]) -> List[str]:
    """This is the abstract part of the Schulze method doing the actual work.

    The candidates are the vertices of a graph and the metric (in form
    of ``d``) describes the strength of the links between the
    candidates, that is edge weights.

    We determine the strongest path from each vertex to each other
    vertex. This gives a transitive relation, which enables us thus to
    determine winners as maximal elements.
    """
    # First determine the strongst paths
    p = {(x, y): d[(x, y)] for x in candidates for y in candidates}
    for i in candidates:
        for j in candidates:
            if i == j:
                continue
            for k in candidates:
                if i == k or j == k:
                    continue
                p[(j, k)] = max(p[(j, k)], min(p[(j, i)], p[(i, k)]))
    # Second determine winners
    winners = []
    for i in candidates:
        if all(p[(i, j)] >= p[(j, i)] for j in candidates):
            winners.append(i)
    return winners


def schulze_evaluate(votes: Collection[str], candidates: Collection[str]
                     ) -> Tuple[str, List[Dict[str, Union[int, List[str]]]]]:
    """Use the Schulze method to cummulate preference list into one list.

    This is used by the assembly realm to tally votes -- however this is
    pretty abstract, so we move it here.

    Votes have the form ``3>0>1=2>4`` where the shortnames between the
    relation signs are exactly those passed in the ``candidates`` parameter.

    The Schulze method is described in the pdf found in the ``related``
    folder. Also the Wikipedia article is pretty nice.

    One thing to mention is, that we do not do any tie breaking. Since
    we allow equality in the votes, it seems reasonable to allow
    equality in the result too.

    For a nice set of examples see the test suite.

    :param candidates: We require that the candidates be explicitly
      passed. This allows for more flexibility (like returning a useful
      result for zero votes).
    :returns: The first Element is the aggregated result,
        the second is an more extended list, containing every level
        (descending) as dict with some extended information.
    """
    split_votes = tuple(
        tuple(lvl.split('=') for lvl in vote.split('>')) for vote in votes)

    def _subindex(alist: Collection[Container[str]], element: str) -> int:
        """The element is in the list at which position in the big list.

        :returns: ``ret`` such that ``element in alist[ret]``
        """
        for index, sublist in enumerate(alist):
            if element in sublist:
                return index
        raise ValueError("Not in list.")

    # First we count the number of votes prefering x to y
    counts = {(x, y): 0 for x in candidates for y in candidates}
    for vote in split_votes:
        for x in candidates:
            for y in candidates:
                if _subindex(vote, x) < _subindex(vote, y):
                    counts[(x, y)] += 1

    # Second we calculate a numeric link strength abstracting the problem
    # into the realm of graphs with one vertex per candidate
    def _strength(support: int, opposition: int, totalvotes: int) -> int:
        """One thing not specified by the Schulze method is how to asses the
        strength of a link and indeed there are several possibilities. We
        use the strategy called 'winning votes' as advised by the paper of
        Markus Schulze.

        If two two links have more support than opposition, then the link
        with more supporters is stronger, if supporters tie then less
        opposition is used as secondary criterion.

        Another strategy which seems to have a more intuitive appeal is
        called 'margin' and sets the difference between support and
        opposition as strength of a link. However the discrepancy
        between the strategies is rather small, to wit all cases in the
        test suite give the same result for both of them. Moreover if
        the votes contain no ties both strategies (and several more) are
        totally equivalent.
        """
        # the margin strategy would be given by the following line
        # return support - opposition
        if support > opposition:
            return totalvotes * support - opposition
        elif support == opposition:
            return 0
        else:
            return -1

    d = {(x, y): _strength(counts[(x, y)], counts[(y, x)], len(votes))
         for x in candidates for y in candidates}
    # Third we execute the Schulze method by iteratively determining
    # winners
    result = []
    while True:
        done = {x for level in result for x in level}
        # avoid sets to preserve ordering
        remaining = tuple(c for c in candidates if c not in done)
        if not remaining:
            break
        winners = _schulze_winners(d, remaining)
        result.append(winners)

    # Return the aggregated preference list in the same format as the input
    # votes are.
    condensed = ">".join("=".join(level) for level in result)
    detailed = []
    for lead, follow in zip(result, result[1:]):
        level = {
            'winner': lead,
            'loser': follow,
            'pro_votes': counts[(lead[0], follow[0])],
            'contra_votes': counts[(follow[0], lead[0])]
        }
        detailed.append(level)

    return condensed, detailed


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
        condensed, detailed = schulze_evaluate(votes, shortnames)

        # zeige schließlich die Ergebnisse an
        announce = "Detail:"
        for level in detailed:
            print(f"{announce} Optionen {level['winner']} bekamen mehr Stimmen als"
                  f" {level['loser']} mit {level['pro_votes']} Pro und"
                  f" {level['contra_votes']} Contra Stimmen.")
            announce = "       "

        print("Ergebnis: {}".format(condensed))
        if condensed != data['result']:
            print("Übereinstimmung: NEIN ({})".format(data['result']))
        else:
            print("Übereinstimmung: ja")
