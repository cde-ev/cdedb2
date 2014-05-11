#!/usr/bin/env python3

"""This provides a rather trivial i18n (= internationalization)
implementation. Currently we only have one output language (german). But
this module should provide two benefits. First it'll hopefully be easier
to add any i18n or even a more sophisticadet i18n solution, once we want
one. Second this allows us to use no strange german string constants in
the source code.

For easier handling string constants in need of i18n should end with a
dot (only were feasible, but this is pretty natural for error messages).
"""

import re
import logging
from cdedb.internationalizationdata import I18N_STRINGS, I18N_REGEXES

_LOGGER = logging.getLogger(__name__)

class I18N:
    """I18n machinery -- this provides the technical means for our i18n. We
    allow for two variants: simple string replacement and a more
    sophisticated (and much more expensive!) regex replacement."""
    def __init__(self):
        self.strings = {}
        self.regexes = {}

    def add_string(self, internal_string, translated_string, lang='de'):
        """
        :type internal_string: str
        :type translated_string: str
        :type lang: str
        """
        self.strings.setdefault(internal_string, {})[lang] = translated_string
        _LOGGER.debug("Added i18n string '{}'->'{}' for {}.".format(
            internal_string, translated_string, lang))

    def add_regex(self, internal_regex, translated_regex, lang='de'):
        """This will be used with :py:func:`re.sub`.

        :type internal_regex: str
        :type translated_regex: str
        :type lang: str
        """
        self.regexes.setdefault(re.compile(internal_regex), {})[lang] = \
          translated_regex
        _LOGGER.debug("Added i18n regex '{}'->'{}' for {}.".format(
            internal_regex, translated_regex, lang))

    def __call__(self, internal_string, lang='de'):
        """
        :type internal_string: str
        :type lang: str
        :rtype: str
        """
        if internal_string in self.strings:
            ret = self.strings[internal_string].get(lang, None)
            if ret is not None:
                return ret
        for regex in self.regexes:
            if regex.match(internal_string):
                if lang in self.regexes[regex]:
                    return regex.sub(self.regexes[regex][lang], internal_string)
        _LOGGER.info("String '{}' is not internationalized to {}.".format(
            internal_string, lang))
        return internal_string

def i18n_factory():
    """Create a ready-to-use instance of :py:class:`I18N`, which has been
    loaded with the data from
    :py:mod:`cdedb.internationalizatiodata`.

    :rtype: :py:class:`I18N`"""
    i18n = I18N()
    for key, value in I18N_STRINGS.items():
        i18n.add_string(key, value)
    for key, value in I18N_REGEXES.items():
        i18n.add_regex(key, value)
    return i18n
