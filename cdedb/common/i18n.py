#!/usr/bin/env python3

"""All about translations."""

from typing import TYPE_CHECKING, List, Tuple

from cdedb.common.sorting import xsorted
from cdedb.common.validation.data import COUNTRY_CODES

if TYPE_CHECKING:
    from cdedb.common import RequestState
else:
    RequestState = None


def n_(x: str) -> str:
    """
    Alias of the identity for i18n.
    Identity function that shadows the gettext alias to trick pybabel into
    adding string to the translated strings.
    """
    return x


def format_country_code(code: str) -> str:
    """Helper to make string hidden to pybabel.

    All possible combined strings are given for translation
    in `i18n_additional.py`
    """
    return f'CountryCodes.{code}'


def get_localized_country_codes(rs: RequestState, lang: str = None
                                ) -> List[Tuple[str, str]]:
    """Generate a list of country code - name tuples in current language."""

    if not hasattr(get_localized_country_codes, "localized_country_codes"):
        localized_country_codes = {
            lang: xsorted(
                ((cc, rs.translations[lang].gettext(format_country_code(cc)))
                 for cc in COUNTRY_CODES),
                key=lambda x: x[1]
            )
            for lang in rs.translations
        }
        get_localized_country_codes.localized_country_codes = localized_country_codes  # type: ignore[attr-defined]
    return get_localized_country_codes.localized_country_codes[lang or rs.lang]  # type: ignore[attr-defined]


def get_country_code_from_country(rs: RequestState, country: str) -> str:
    """Match a country to its country code."""

    if not hasattr(get_country_code_from_country, "reverse_country_code_map"):
        reverse_map = {
            lang: {
                rs.translations[lang].gettext(format_country_code(cc)): cc
                for cc in COUNTRY_CODES
            }
            for lang in rs.translations
        }
        get_country_code_from_country.reverse_map = reverse_map  # type: ignore[attr-defined]
    for lang, v in get_country_code_from_country.reverse_map.items():  # type: ignore[attr-defined]
        if ret := v.get(country):
            return ret
    return country
