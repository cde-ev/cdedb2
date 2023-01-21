#!/usr/bin/env python3

"""Global utility functions."""

import collections
import collections.abc
import datetime
from typing import (
    Any, Callable, Collection, Dict, Generator, Iterable, KeysView, List, Tuple,
    TypeVar, Union,
)

import icu

from cdedb.common.n_ import n_

# Global unified collator to be used when sorting.
# The locale provided here must exist as collation in SQL for this to
# work properly.
# 'de_DE.UTF-8@colNumeric=yes' is an equivalent choice for LOCAL, but is less
# compatible to use as a collation name in postgresql.
LOCALE = 'de-u-kn-true'
COLLATOR = icu.Collator.createInstance(icu.Locale(LOCALE))

# Pseudo objects like assembly, event, course, event part, etc.
CdEDBObject = Dict[str, Any]

T = TypeVar("T")


def xsorted(iterable: Iterable[T], *, key: Callable[[Any], Any] = lambda x: x,
            reverse: bool = False) -> List[T]:
    """Wrapper for sorted() to achieve a natural sort.

    This replaces all strings in possibly nested objects with a sortkey
    matching an collation from the Unicode Collation Algorithm, provided
    by the icu library.

    In particular, this makes sure strings containing diacritics are
    sorted correctly, e.g. with ß = ss, a = ä, s = S etc. Furthermore, numbers
    (ints and decimals) are sorted correctly, even in midst of strings.
    However, negative numbers in strings are sorted by absolute value, before
    positive numbers, as minus and hyphens can not be distinguished.

    For users, the interface of this function should be identical
    to sorted().
    """

    def collate(sortkey: Any) -> Any:
        if isinstance(sortkey, str):
            return COLLATOR.getSortKey(sortkey)
        if isinstance(sortkey, collections.abc.Iterable):
            # Make sure strings in nested Iterables are sorted
            # correctly as well.
            return tuple(map(collate, sortkey))
        return sortkey

    return sorted(iterable, key=lambda x: collate(key(x)),  # pylint: disable=bad-builtin
                  reverse=reverse)


def make_persona_forename(persona: CdEDBObject,
                          only_given_names: bool = False,
                          only_display_name: bool = False,
                          given_and_display_names: bool = False) -> str:
    """Construct the forename of a persona according to the display name specification.

    The name specification can be found at the documentation page about
    "User Experience Conventions".
    """
    if only_display_name + only_given_names + given_and_display_names > 1:
        raise RuntimeError(n_("Invalid use of keyword parameters."))
    display_name: str = persona.get('display_name', "")
    given_names: str = persona['given_names']
    if only_given_names:
        return given_names
    elif only_display_name:
        return display_name
    elif given_and_display_names:
        if not display_name or display_name == given_names:
            return given_names
        else:
            return f"{given_names} ({display_name})"
    elif display_name and display_name in given_names:
        return display_name
    return given_names


Sortkey = Tuple[Union[str, int, datetime.datetime], ...]
KeyFunction = Callable[[CdEDBObject], Sortkey]


def _make_persona_sorter(only_given_names: bool = False,
                        only_display_name: bool = False,
                        given_and_display_names: bool = False,
                        family_name_first: bool = True) -> KeyFunction:
    """Create a function to sort names accordingly to the display name specification

    The returned key function accepts a persona dict and returns a sorting key,
    accordingly to the specification made at creation. The name specification can
    be found at the documentation page about "User Experience Conventions".

    For the sake of simplicity, we ignore titles for sorting and always use
    forename and surname as sort keys.

    :param family_name_first: Whether the forename or the surname take precedence
        as sorting key.
    """

    def sorter(persona: CdEDBObject) -> Sortkey:
        forename = make_persona_forename(
            persona, only_given_names=only_given_names,
            only_display_name=only_display_name,
            given_and_display_names=given_and_display_names)

        forename = forename.lower()
        family_name = persona["family_name"].lower()
        if family_name_first:
            return (family_name, forename, persona["id"])
        else:
            return (forename, family_name, persona["id"])

    return sorter


# noinspection PyRedundantParentheses
class EntitySorter:
    """Provide a singular point for common sortkeys.

    This class does not need to be instantiated. It's method can be passed to
    `sorted` or `keydictsort_filter`.
    """

    make_persona_sorter = staticmethod(_make_persona_sorter)

    # TODO decide whether we sort by first or last name
    persona = staticmethod(_make_persona_sorter(family_name_first=True))

    @staticmethod
    def email(persona: CdEDBObject) -> Sortkey:
        return (str(persona['username']),)

    @staticmethod
    def address(persona: CdEDBObject) -> Sortkey:
        # TODO sort by translated country instead of country code?
        country = persona.get('country', "") or ""
        postal_code = persona.get('postal_code', "") or ""
        location = persona.get('location', "") or ""
        address = persona.get('address', "") or ""
        return (country, postal_code, location, address)

    @staticmethod
    def event(event: CdEDBObject) -> Sortkey:
        return (event['begin'], event['end'], event['title'], event['id'])

    @staticmethod
    def course(course: CdEDBObject) -> Sortkey:
        return (course['nr'], course['shortname'], course['id'])

    @staticmethod
    def lodgement(lodgement: CdEDBObject) -> Sortkey:
        return (lodgement['title'], lodgement['id'])

    @staticmethod
    def lodgement_by_group(lodgement: CdEDBObject) -> Sortkey:
        return (lodgement['group_title'] is None, lodgement['group_title'],
                lodgement['group_id'], lodgement['title'], lodgement['id'])

    @staticmethod
    def lodgement_group(lodgement_group: CdEDBObject) -> Sortkey:
        return (lodgement_group['title'], lodgement_group['id'])

    @staticmethod
    def event_part(event_part: CdEDBObject) -> Sortkey:
        return (event_part['part_begin'], event_part['part_end'],
                event_part['shortname'], event_part['id'])

    @staticmethod
    def event_part_group(part_group: CdEDBObject) -> Sortkey:
        return (part_group['title'], part_group['id'])

    @staticmethod
    def event_fee(event_fee: CdEDBObject) -> Sortkey:
        return (event_fee['title'], event_fee['id'])

    @staticmethod
    def course_track(course_track: CdEDBObject) -> Sortkey:
        return (course_track['sortkey'], course_track['id'])

    @staticmethod
    def course_track_group(track_group: CdEDBObject) -> Sortkey:
        return (track_group['sortkey'], track_group['constraint_type'],
                track_group['title'], track_group['shortname'], track_group['id'])

    @staticmethod
    def course_choice_object(cco: CdEDBObject) -> Sortkey:
        return (cco['sortkey'], cco.get('constraint_type', 0), cco['title'], cco['id'])

    @staticmethod
    def event_field(event_field: CdEDBObject) -> Sortkey:
        return (event_field['sortkey'], event_field['field_name'], event_field['id'])

    @staticmethod
    def candidates(candidates: CdEDBObject) -> Sortkey:
        return (candidates['shortname'], candidates['id'])

    @staticmethod
    def assembly(assembly: CdEDBObject) -> Sortkey:
        return (assembly['signup_end'], assembly['id'])

    @staticmethod
    def ballot(ballot: CdEDBObject) -> Sortkey:
        return (ballot['title'], ballot['id'])

    @staticmethod
    def attachment(attachment: CdEDBObject) -> Sortkey:
        """This is used for dicts containing one version of different attachments."""
        return (attachment["title"], attachment["attachment_id"])

    @staticmethod
    def attachment_version(version: CdEDBObject) -> Sortkey:
        return (version['attachment_id'], version['version_nr'])

    @staticmethod
    def past_event(past_event: CdEDBObject) -> Sortkey:
        return (past_event['tempus'], past_event['id'])

    @staticmethod
    def past_course(past_course: CdEDBObject) -> Sortkey:
        return (past_course['nr'], past_course['title'], past_course['id'])

    @staticmethod
    def institution(institution: CdEDBObject) -> Sortkey:
        return (institution['shortname'], institution['id'])

    @staticmethod
    def transaction(transaction: CdEDBObject) -> Sortkey:
        return (transaction['issued_at'], transaction['id'])

    @staticmethod
    def genesis_case(genesis_case: CdEDBObject) -> Sortkey:
        return (genesis_case['ctime'], genesis_case['id'])

    @staticmethod
    def changelog(changelog_entry: CdEDBObject) -> Sortkey:
        return (changelog_entry['ctime'], changelog_entry['id'])

    @staticmethod
    def mailinglist(mailinglist: CdEDBObject) -> Sortkey:
        return (mailinglist['title'], mailinglist['id'])


def mixed_existence_sorter(iterable: Union[Collection[int], KeysView[int]]
                           ) -> Generator[int, None, None]:
    """Iterate over a set of indices in the relevant way.

    That is first over the non-negative indices in ascending order and
    then over the negative indices in descending order.

    This is the desired order if the UI offers the possibility to
    create multiple new entities enumerated by negative IDs.
    """
    for i in xsorted(iterable):
        if i >= 0:
            yield i
    for i in reversed(xsorted(iterable)):
        if i < 0:
            yield i
