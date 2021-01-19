#!/usr/bin/env python3

"""Evaluate performance data logged by test suite. """

import argparse
import statistics
from typing import Collection, Dict, List, Tuple

import dateutil.parser

parser = argparse.ArgumentParser(
    description='Analyze timing info from test run.')
parser.add_argument('log', help="path to log file where info was stored")
args = parser.parse_args()


class Entry:
    """One data point, corresponding to one request."""
    def __init__(self, path: str, method: str, time: str, query: str):
        """
        :param path: path component of HTTP request
        :param method: method of HTTP request
        :param time: time taken for processing of the request
        :param query: query component of HTTP request
        """
        self.path = path
        self.method = method
        tmp = dateutil.parser.parse(time).time()
        self.time = (tmp.minute*60+tmp.second) * 10**6 + tmp.microsecond
        self.query = query

    def __str__(self) -> str:
        return f"{self.path} {self.method} {self.time/10**6} {self.query}"


# read data

entries = []
with open(args.log, encoding='UTF-8') as infile:
    for line in infile:
        fields = line.replace('\n', '').split(' ')
        if len(fields) != 4:
            print("Malformed line ({})!".format(line))
        else:
            try:
                entries.append(Entry(*fields))
            except ValueError:
                # ignore errors caused by non-existant pages
                pass

# evaluate data
print("=======================================================================")
print("Worst request")
print("=======================================================================")
for entry in sorted(entries, key=lambda e: e.time)[-10:]:
    print(entry)

aggregate: Dict[Tuple[str, str], List[int]] = {}
for entry in entries:
    aggregate.setdefault((entry.path, entry.method), []).append(entry.time)


def make_stats(item: Collection[int]) -> str:
    """Generate statistics for a sequence of numbers (like mean, median, etc.).

    The numbers are assumed to be in microseconds and normalized to seconds.

    :returns: stats ready for output
    """
    if len(item) > 1:
        dev = statistics.stdev(item)/10**6
    else:
        dev = 0
    twentieth = sorted(item)[19*len(item)//20]
    return (f"num={len(item)} avg={statistics.mean(item)/10**6}"
            f" median={statistics.median(item)/10**6}"
            f" min={min(item)/10**6} max={max(item)/10**6} dev={dev}"
            f" 20th={twentieth/10**6}")


print("=======================================================================")
print("Statistics (by URL)")
print("=======================================================================")
for path, method in sorted(aggregate):
    print(f"{path} {method}: {make_stats(aggregate[(path, method)])}")

print("=======================================================================")
print("Statistics (by performance)")
print("=======================================================================")
for path, method in sorted(aggregate,
                           key=lambda k: statistics.mean(aggregate[k])):
    print(f"{path} {method}: {make_stats(aggregate[(path, method)])}")

print("=======================================================================")
print("Statistics (overall)")
print("=======================================================================")
print("all: {}".format(
    make_stats(tuple(t for item in aggregate.values() for t in item))))
print("GET: {}".format(
    make_stats(tuple(t
                     for key, item in aggregate.items() if key[1] == "GET"
                     for t in item))))
print("POST: {}".format(
    make_stats(tuple(t
                     for key, item in aggregate.items() if key[1] == "POST"
                     for t in item))))
print("/: {}".format(
    make_stats(tuple(t
                     for key, item in aggregate.items()
                     if key[0] == '/'
                     for t in item))))
print("core: {}".format(
    make_stats(tuple(t
                     for key, item in aggregate.items()
                     if key[0].startswith('/core')
                     for t in item))))
print("cde: {}".format(
    make_stats(tuple(t
                     for key, item in aggregate.items()
                     if key[0].startswith('/cde')
                     for t in item))))
print("event: {}".format(
    make_stats(tuple(t
                     for key, item in aggregate.items()
                     if key[0].startswith('/event')
                     for t in item))))
print("ml: {}".format(
    make_stats(tuple(t
                     for key, item in aggregate.items()
                     if key[0].startswith('/ml')
                     for t in item))))
