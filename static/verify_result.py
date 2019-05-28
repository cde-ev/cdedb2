#!/usr/bin/env python3

"""Skript um die Auszählung in Ergebnisdateien von Wahlen zu verifizieren.

Dies kann auf keine anderen Dateien der CdEDB zugreifen, weshalb wir
eine gewisse unvermeidbare Duplikation haben.
"""

import argparse
import json
import pathlib


def _schulze_winners(d, candidates):
    """This is the abstract part of the Schulze method doing the actual work.

    The candidates are the vertices of a graph and the metric (in form
    of ``d``) describes the strength of the links between the
    candidates, that is edge weights.

    We determine the strongest path from each vertex to each other
    vertex. This gives a transitive relation, which enables us thus to
    determine winners as maximal elements.

    :type d: {(str, str): int}
    :type candidates: [str]
    :rtype: [str]
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


def schulze_evaluate(votes, candidates):
    """Use the Schulze method to cummulate preference list into one list.

    This is used by the assembly realm to tally votes -- however this is
    pretty abstract, so we move it here.

    Votes have the form ``3>0>1=2>4`` where the monikers between the
    relation signs are exactly those passed in the ``candidates`` parameter.

    The Schulze method is described in the pdf found in the ``related``
    folder. Also the Wikipedia article is pretty nice.

    One thing to mention is, that we do not do any tie breaking. Since
    we allow equality in the votes, it seems reasonable to allow
    equality in the result too.

    For a nice set of examples see the test suite.

    :type votes: [str]
    :type candidates: [str]
    :param candidates: We require that the candidates be explicitly
      passed. This allows for more flexibility (like returning a useful
      result for zero votes).
    :rtype: str
    :returns: The aggregated preference list.
    """
    if not votes:
        return '='.join(candidates)
    split_votes = tuple(
        tuple(level.split('=') for level in vote.split('>')) for vote in votes)

    def _subindex(alist, element):
        """The element is in the list at which position in the big list.

        :type alist: [[str]]
        :type element: str
        :rtype: int
        :returns: ``ret`` such that ``element in alist[ret]``
        """
        for index, sublist in enumerate(alist):
            if element in sublist:
                return index
        raise ValueError(n_("Not in list."))

    # First we count the number of votes prefering x to y
    counts = {(x, y): 0 for x in candidates for y in candidates}
    for vote in split_votes:
        for x in candidates:
            for y in candidates:
                if _subindex(vote, x) < _subindex(vote, y):
                    counts[(x, y)] += 1

    # Second we calculate a numeric link strength abstracting the problem
    # into the realm of graphs with one vertex per candidate
    def _strength(support, opposition, totalvotes):
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

        :type support: int
        :type opposition: int
        :type totalvotes: int
        :rtype: int
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
    # Return the aggregate preference list in the same format as the input
    # votes are.
    return ">".join("=".join(level) for level in result)


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
        candidates = ", ".join(
            "{} ({})".format(value, key)
            for key, value in sorted(data['candidates'].items()))
        print("Optionen: {}".format(candidates))
        # ... und zähle neu aus
        votes = [entry['vote'] for entry in data['votes']]
        monikers = list(data['candidates'])
        if data['use_bar']:
            monikers.append("_bar_")
        result = schulze_evaluate(votes, monikers)
        print("Ergebnis: {}".format(schulze_evaluate(votes, monikers)))
        if result != data['result']:
            print("Übereinstimmung: NEIN ({})".format(data['result']))
        else:
            print("Übereinstimmung: ja")