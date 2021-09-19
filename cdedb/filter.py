"""Filter definitions for jinja templates"""

import datetime
import decimal
import enum
import re
import threading

import logging
from typing import (
    Any, Callable, Collection, Container, Dict, Iterable, ItemsView, List, Literal,
    Mapping, Optional, Sequence, Set, Tuple, Type, TypeVar, Union, overload
)

import bleach
import icu
import jinja2
import markdown
import markdown.extensions.toc

from cdedb.common import CdEDBObject, compute_checkdigit, xsorted
import cdedb.database.constants as const

_LOGGER = logging.getLogger(__name__)

S = TypeVar("S")
T = TypeVar("T")


# Ignore the capitalization error in function name sanitize_None.
# noinspection PyPep8Naming
def sanitize_None(data: Optional[T]) -> Union[str, T]:
    """Helper to let jinja convert all ``None`` into empty strings for display
    purposes; thus we needn't be careful in this regard. (This is
    coherent with our policy that NULL and the empty string on SQL level
    shall have the same meaning).
    """
    if data is None:
        return ""
    else:
        return data


@overload
def safe_filter(val: None) -> None: ...


@overload
def safe_filter(val: str) -> jinja2.Markup: ...


def safe_filter(val: Optional[str]) -> Optional[jinja2.Markup]:
    """Custom jinja filter to mark a string as safe.

    This prevents autoescaping of this entity. To be used for dynamically
    generated code we insert into the templates. It is basically equal to
    Jinja's builtin ``|safe``-Filter, but additionally takes care about None
    values.
    """
    if val is None:
        return None
    return jinja2.Markup(val)


def date_filter(val: Union[datetime.date, str, None],
                formatstr: str = "%Y-%m-%d", lang: str = None,
                verbosity: str = "medium",
                passthrough: bool = False) -> Optional[str]:
    """Custom jinja filter to format ``datetime.date`` objects.

    :param formatstr: Formatting used, if no l10n happens.
    :param lang: If not None, then localize to the passed language.
    :param verbosity: Controls localized formatting. Takes one of the
      following values: short, medium, long and full.
    :param passthrough: If True return strings unmodified.
    """
    if val is None or val == '' or not isinstance(val, datetime.date):
        if passthrough and isinstance(val, str) and val and val != datetime.date.min:
            return val
        return None

    if val == datetime.date.min:
        return "N/A"

    if lang:
        verbosity_mapping = {
            "short": icu.DateFormat.SHORT,
            "medium": icu.DateFormat.MEDIUM,
            "long": icu.DateFormat.LONG,
            "full": icu.DateFormat.FULL,
        }
        locale = icu.Locale(lang)
        date_formatter = icu.DateFormat.createDateInstance(
            verbosity_mapping[verbosity], locale
        )
        effective = datetime.datetime.combine(val, datetime.time())
        if not hasattr(effective, '_date_to_freeze'):
            # This branch is only avoided if freezegun is in effect
            # (hence only under test).
            #
            # Sadly pyICU is incompatible with freezegun (see for example
            # https://github.com/spulec/freezegun/issues/207). Thus we have
            # to forfeit nicely formatted dates in this scenario.
            #
            # The attribute check is a bit fragile, but no better way to
            # detect freezegun was available.
            return date_formatter.format(effective)
    return val.strftime(formatstr)


@overload
def money_filter(val: None, currency: str = "EUR", lang: str = "de"
                 ) -> None: ...


@overload
def money_filter(val: decimal.Decimal, currency: str = "EUR", lang: str = "de"
                 ) -> str: ...


def money_filter(val: Optional[decimal.Decimal], currency: str = "EUR",
                 lang: str = "de") -> Optional[str]:
    """Custom jinja filter to format ``decimal.Decimal`` objects.

    This is for values representing monetary amounts.
    """
    if val is None:
        return None

    locale = icu.Locale(lang)
    formatter = icu.NumberFormatter.withLocale(locale).unit(icu.CurrencyUnit(currency))
    return formatter.formatDecimal(str(val).encode())


@overload
def decimal_filter(val: None, lang: str) -> None: ...


@overload
def decimal_filter(val: float, lang: str) -> str: ...


def decimal_filter(val: Optional[float], lang: str) -> Optional[str]:
    """Cutom jinja filter to format floating point numbers."""
    if val is None:
        return None

    locale = icu.Locale(lang)
    formatter = icu.NumberFormatter.withLocale(locale)
    return formatter.formatDouble(val)


@overload
def cdedbid_filter(val: None) -> None: ...


@overload
def cdedbid_filter(val: int) -> str: ...


def cdedbid_filter(val: Optional[int]) -> Optional[str]:
    """Custom jinja filter to format persona ids with a check digit. Every user
    visible id should be formatted with this filter. The check digit is
    one of the letters between 'A' and 'K' to make a clear distinction
    between the numeric id and the check digit.
    """
    if val is None:
        return None
    return "DB-{}-{}".format(val, compute_checkdigit(val))


@overload
def iban_filter(val: None) -> None: ...


@overload
def iban_filter(val: str) -> str: ...


def iban_filter(val: Optional[str]) -> Optional[str]:
    """Custom jinja filter for displaying IBANs in nice to read blocks."""
    if val is None:
        return None
    else:
        val = val.strip().replace(" ", "")
        return " ".join(val[x:x + 4] for x in range(0, len(val), 4))


@overload
def hidden_iban_filter(val: None) -> None: ...


@overload
def hidden_iban_filter(val: str) -> str: ...


def hidden_iban_filter(val: Optional[str]) -> Optional[str]:
    """Custom jinja filter for hiding IBANs in nice to read blocks."""
    if val is None:
        return None
    else:
        val = val[:4] + "*" * (len(val) - 8) + val[-4:]
        return iban_filter(val)


@overload
def escape_filter(val: None) -> None: ...


@overload
def escape_filter(val: str) -> jinja2.Markup: ...


def escape_filter(val: Optional[str]) -> Optional[jinja2.Markup]:
    """Custom jinja filter to reconcile escaping with the finalize method
    (which suppresses all ``None`` values and thus mustn't be converted to
    strings first).

    .. note:: Actually this returns a jinja specific 'safe string' which
      will remain safe when operated on. This means for example that the
      linebreaks filter has to make the string unsafe again, before it can
      work.
    """
    if val is None:
        return None
    else:
        return jinja2.escape(val)


LATEX_ESCAPE_REGEX = (
    (re.compile(r'\\'), r'\\textbackslash '),
    (re.compile(r'([{}_#%&$])'), r'\\\1'),
    (re.compile(r'~'), r'\~{}'),
    (re.compile(r'\^'), r'\^{}'),
    (re.compile(r'"'), r"''"),
)


@overload
def tex_escape_filter(val: None) -> None: ...


@overload
def tex_escape_filter(val: str) -> str: ...


def tex_escape_filter(val: Optional[str]) -> Optional[str]:
    """Custom jinja filter for escaping LaTeX-relevant charakters."""
    if val is None:
        return None
    else:
        val = str(val)
        for pattern, replacement in LATEX_ESCAPE_REGEX:
            val = pattern.sub(replacement, val)
        return val


@overload
def enum_filter(val: None, enum_: Type[enum.Enum]) -> None: ...


@overload
def enum_filter(val: int, enum_: Type[enum.Enum]) -> str: ...


def enum_filter(val: Optional[int], enum_: Type[enum.Enum]) -> Optional[str]:
    """Custom jinja filter to convert enums to something printable.

    This exists mainly because of the possibility of None values.
    """
    if val is None:
        return None
    return str(enum_(val))


@overload
def genus_filter(val: None, female: str, male: str, unknown: Optional[str]
                 ) -> None: ...


@overload
def genus_filter(val: int, female: str, male: str,
                 unknown: Optional[str]) -> Optional[str]: ...


def genus_filter(val: Optional[int], female: str, male: str,
                 unknown: str = None) -> Optional[str]:
    """Custom jinja filter to select gendered form of a string."""
    if val is None:
        return None
    if unknown is None:
        unknown = female
    if val == const.Genders.female:
        return female
    elif val == const.Genders.male:
        return male
    else:
        return unknown


# noinspection PyPep8Naming
def stringIn_filter(val: Any, alist: Collection[Any]) -> bool:
    """Custom jinja filter to test if a value is in a list, but requiring
    equality only on string representation.

    This has to be an explicit filter becaus jinja does not support list
    comprehension.
    """
    return str(val) in (str(x) for x in alist)


@overload
def linebreaks_filter(val: None, replacement: str) -> None: ...


@overload
def linebreaks_filter(val: Union[str, jinja2.Markup],
                      replacement: str) -> jinja2.Markup: ...


def linebreaks_filter(val: Union[None, str, jinja2.Markup],
                      replacement: str = "<br>") -> Optional[jinja2.Markup]:
    """Custom jinja filter to convert line breaks to <br>.

    This filter escapes the input value (if required), replaces the linebreaks
    and marks the output as safe html.
    """
    if val is None:
        return None
    # escape the input. This function consumes an unescaped string or a
    # jinja2.Markup safe html object and returns an escaped string.
    val = jinja2.escape(val)
    return val.replace('\n', jinja2.Markup(replacement))


#: bleach internals are not thread-safe, so we have to be a bit defensive
#: w.r.t. threads
BLEACH_CLEANER = threading.local()


def get_bleach_cleaner() -> bleach.sanitizer.Cleaner:
    """Constructs bleach cleaner appropiate to untrusted user content.

    If you adjust this, please adjust the markdown specification in
    the docs as well."""
    cleaner = getattr(BLEACH_CLEANER, 'cleaner', None)
    if cleaner:
        return cleaner
    tags = [
        'a', 'abbr', 'acronym', 'b', 'blockquote', 'code', 'em', 'i', 'li',
        'ol', 'strong', 'ul',
        # customizations
        'h1', 'h2', 'h3', 'h4', 'h5', 'h6', 'colgroup', 'col', 'tr', 'th',
        'thead', 'table', 'tbody', 'td', 'hr', 'p', 'span', 'div', 'pre', 'tt',
        'sup', 'sub', 'small', 'br', 'u', 'dl', 'dt', 'dd', 'details', 'summary']
    attributes = {
        'a': ['href', 'title'],
        'abbr': ['title'],
        'acronym': ['title'],
        # customizations
        '*': ['class', 'id'],
        'col': ['width'],
        'thead': ['valign'],
        'tbody': ['valign'],
        'table': ['border'],
        'th': ['colspan', 'rowspan'],
        'td': ['colspan', 'rowspan'],
        'details': ['open'],
    }
    cleaner = bleach.sanitizer.Cleaner(tags=tags, attributes=attributes)
    BLEACH_CLEANER.cleaner = cleaner
    return cleaner


@overload
def bleach_filter(val: None) -> None: ...


@overload
def bleach_filter(val: str) -> jinja2.Markup: ...


def bleach_filter(val: Optional[str]) -> Optional[jinja2.Markup]:
    """Custom jinja filter to convert sanitize html with bleach."""
    if val is None:
        return None
    return jinja2.Markup(get_bleach_cleaner().clean(val))


#: The Markdown parser has internal state, so we have to be a bit defensive
#: w.r.t. threads
MARKDOWN_PARSER = threading.local()


def md_id_wrapper(val: str, sep: str) -> str:
    """
    Wrap the markdown toc slugify function to attach an ID prefix.

    :param val: String to be made URL friendly.
    :param sep: String to be used instead of Whitespace.
    """

    id_prefix = "CDEDB_MD_"

    return id_prefix + markdown.extensions.toc.slugify(val, sep)


def get_markdown_parser() -> markdown.Markdown:
    """Constructs a markdown parser for general use.

    If you adjust this, please adjust the markdown specification in
    the docs as well."""
    md = getattr(MARKDOWN_PARSER, 'md', None)

    if md is None:
        extension_configs = {
            "toc": {
                "baselevel": 4,
                "permalink": True,
                "slugify": md_id_wrapper,
            },
            'smarty': {
                'substitutions': {
                    'left-single-quote': '&sbquo;',
                    'right-single-quote': '&lsquo;',
                    'left-double-quote': '&bdquo;',
                    'right-double-quote': '&ldquo;',
                },
            },
        }
        md = markdown.Markdown(extensions=["extra", "sane_lists", "smarty", "toc"],
                               extension_configs=extension_configs)

        MARKDOWN_PARSER.md = md
    else:
        md.reset()
    return md


def markdown_parse_safe(val: str) -> jinja2.Markup:
    md = get_markdown_parser()
    return bleach_filter(md.convert(val))


@overload
def md_filter(val: None) -> None: ...


@overload
def md_filter(val: str) -> jinja2.Markup: ...


def md_filter(val: Optional[str]) -> Optional[jinja2.Markup]:
    """Custom jinja filter to convert markdown to html."""
    if val is None:
        return None
    return markdown_parse_safe(val)


@jinja2.environmentfilter
def sort_filter(env: jinja2.Environment, value: Iterable[T],
                reverse: bool = False, attribute: Any = None) -> List[T]:
    """Sort an iterable using `xsorted`, using correct collation.

    TODO: With Jinja 2.11, make_multi_attrgetter should be used
    instead, since it allows to provide multiple sorting criteria.

    :param reverse: Sort descending instead of ascending.
    :param attribute: When sorting objects or dicts, an attribute or
        key to sort by. Can use dot notation like ``"address.city"``.
        Can be a list of attributes like ``"age,name"``.
    """
    key_func = jinja2.filters.make_attrgetter(env, attribute)
    return xsorted(value, key=key_func, reverse=reverse)


def dictsort_filter(value: Mapping[T, S], by: Literal["key", "value"] = "key",
                    reverse: bool = False) -> List[Tuple[T, S]]:
    """Sort a dict and yield (key, value) pairs.

    Because python dicts are unsorted you may want to use this function to
    order them by key.
    """

    def sortfunc(x: Any) -> Any:
        if by == "key":
            return x[0]
        elif by == "value":
            return x[1], x[0]
        else:
            raise ValueError

    return xsorted(value.items(), key=sortfunc, reverse=reverse)


def set_filter(value: Iterable[T]) -> Set[T]:
    """
    A simple filter to construct a Python set from an iterable object. Just
    like Jinja's builtin "list" filter, but for sets.
    """
    return set(value)


def xdictsort_filter(value: Mapping[T, S], attribute: str,
                     reverse: bool = False) -> List[Tuple[T, S]]:
    """Allow sorting by an arbitrary attribute of the value.

    Jinja only provides sorting by key or entire value. Also Jinja does
    not allow comprehensions or lambdas, hence we have to use this.

    This obviously only works if the values allow access by key.

    :param attribute: name of the attribute
    """
    key = lambda item: item[1].get(attribute)
    return xsorted(value.items(), key=key, reverse=reverse)


def keydictsort_filter(value: Mapping[T, S], sortkey: Callable[[Any], Any],
                       reverse: bool = False) -> List[Tuple[T, S]]:
    """Sort a dicts items by their value."""
    return xsorted(value.items(), key=lambda e: sortkey(e[1]), reverse=reverse)


def map_dict_filter(d: Dict[str, str], processing: Callable[[Any], str]
                    ) -> ItemsView[str, str]:
    """
    Processes the values of some string using processing function

    :param processing: A function to be applied on the dict values
    :return: The dict with its values replaced with the processed values
    """
    return {k: processing(v) for k, v in d.items()}.items()


def enum_entries_filter(enum: enum.EnumMeta, processing: Callable[[Any], str] = None,
                        raw: bool = False,
                        prefix: str = "") -> List[Tuple[int, str]]:
    """
    Transform an Enum into a list of of (value, string) tuple entries. The
    string is piped trough the passed processing callback function to get the
    human readable and translated caption of the value.

    :param processing: A function to be applied on the value's string
        representation before adding it to the result tuple. Typically this is
        gettext()
    :param raw: If this is True, the enum entries are passed to processing as
        is, otherwise they are converted to str first.
    :param prefix: A prefix to prepend to the string output of every entry.
    :return: A list of tuples to be used in the input_checkboxes or
        input_select macros.
    """
    if processing is None:
        processing = lambda x: x
    if raw:
        pre = lambda x: x
    else:
        pre = str
    to_sort = ((entry.value, prefix + processing(pre(entry)))  # type: ignore
               for entry in enum)
    return xsorted(to_sort)


def dict_entries_filter(items: List[Tuple[Any, Mapping[T, S]]],
                        *args: T) -> List[Tuple[S, ...]]:
    """
    Transform a list of dict items with dict-type values into a list of
    tuples of specified fields of the value dict.

    Example::

        >>> items = [(1, {'id': 1, 'name': 'a', 'active': True}),
                     (2, {'id': 2, 'name': 'b', 'active': False})]
        >>> dict_entries_filter(items, 'name', 'active')
        [('a', True), ('b', False)]

    :param items: A list of 2-element tuples. The first element of each
      tuple is ignored, the second must be a dict
    :param args: Additional positional arguments describing which keys of
      the dicts should be inserted in the resulting tuple
    :return: A list of tuples (e.g. to be used in the input_checkboxes or
      input_select macros), built from the selected fields of the dicts
    """
    return [tuple(value[k] for k in args) for key, value in items]


def xdict_entries_filter(items: Sequence[Tuple[Any, CdEDBObject]], *args: str,
                         include: Container[str] = None
                         ) -> List[Tuple[str, ...]]:
    """
    Transform a list of dict items with dict-type values into a list of
    tuples of strings with specified format. Each entry of the resulting
    tuples is built by applying the item's value dict to a format string.

    Example::
        >>> items = [(1, {'id': 1, 'name': 'a', 'active': True}),
                     (2, {'id': 2, 'name': 'b', 'active': False})]
        >>> xdict_entries_filter(items, '{id}', '{name} -- {active}')
        [('1', 'a -- True'), ('2', 'b -- False')]

    :param items: A list of 2-element tuples. The first element of each
      tuple is ignored, the second must be a dict
    :param args: Additional positional arguments, which are format strings
      for the resulting tuples. They can use named format specifications to
      access the dicts' fields.
    :param include: An iteratable to search for items' keys. Only items with
      their key being in `include` are included in the results list
    :return: A list of tuples (e.g. to be used in the input_checkboxes or
      input_select macros), built from the selected fields of the dicts
    """
    return [tuple(k.format(**value) for k in args)
            for key, value in items
            if (include is None or key in include)]


#: Dictionary of custom filters we make available in the templates.
JINJA_FILTERS = {
    'date': date_filter,
    'money': money_filter,
    'decimal': decimal_filter,
    'cdedbid': cdedbid_filter,
    'iban': iban_filter,
    'hidden_iban': hidden_iban_filter,
    'escape': escape_filter,
    'e': escape_filter,
    'stringIn': stringIn_filter,
    'genus': genus_filter,
    'linebreaks': linebreaks_filter,
    'map_dict': map_dict_filter,
    'md': md_filter,
    'enum': enum_filter,
    'sort': sort_filter,
    'dictsort': dictsort_filter,
    'xdictsort': xdictsort_filter,
    'keydictsort': keydictsort_filter,
    's': safe_filter,
    'set': set_filter,
    'tex_escape': tex_escape_filter,
    'te': tex_escape_filter,
    'enum_entries': enum_entries_filter,
    'dict_entries': dict_entries_filter,
    'xdict_entries': xdict_entries_filter,
}
