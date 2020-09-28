#!/usr/bin/python3

import argparse
import pathlib
import re
import sys

sys.path.insert(0, "/cdedb2")

parser = argparse.ArgumentParser()
parser.add_argument("input_file", action="store", type=str)
args = parser.parse_args()

description_file = pathlib.Path(args.input_file)

with open(description_file, "r") as f:
    line_iter = iter(f.readlines())

normalized = []
for line in line_iter:
    if (re.match(r"\(\d+ Zeilen\)", line.strip())
            or (line.strip().count("-") + line.strip().count("+")
                == len(line.strip()))
            or not line.strip()):
        continue
    normalized.append("|".join(s.strip() for s in line.split("|")))

with open(description_file, "w") as f:
    f.write("\n".join(normalized))
