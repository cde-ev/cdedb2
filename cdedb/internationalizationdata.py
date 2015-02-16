#!/usr/bin/env python3

"""Actual translations used by :py:module:`cdedb.internationalization`."""

from cdedb.common import glue

I18N_STRINGS = {
    "Must be printable ASCII.": glue("Darf nur aus druckbaren ASCII-Zeichen",
                                     "bestehen."),
    "Session expired.": "Die Sitzung ist abgelaufen.",
    "": "",
    None: "Undefiniert.",
}

I18N_REGEXES = {
    r"No persona with id ([0-9]+)\.": r"Kein Nutzer mit ID \1 gefunden.",
}
