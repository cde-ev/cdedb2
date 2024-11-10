"""Custom types for LDAP"""

from collections.abc import Sequence
from typing import Any, NewType, TypeAlias

import ldaptor.protocols.pureldap as pureldap

AttributeDescriptionList = NewType("AttributeDescriptionList", Sequence[Any])
FilterLike: TypeAlias = pureldap.LDAPFilter | pureldap.LDAPFilterSet
