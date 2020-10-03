#!/usr/bin/env python3

import re
import pathlib

main_dir = pathlib.Path.resolve(pathlib.Path(__file__).parent).parent
infile = str(main_dir / "i18n/de/LC_MESSAGES/cdedb.po")
outfile = str(main_dir / "i18n/de/LC_MESSAGES/cdedb.spellcheck")


with open(infile, mode="r") as infile:
    text = infile.read()
    text = re.sub(r'(#.*\n)*msgid (".*?"\n)+msgstr ', "", text)
    text = re.sub(r'"\n"', "", text)

with open(outfile, mode="w") as outfile:
    outfile.write(text)
