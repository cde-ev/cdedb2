"""Custom types for LDAP"""

from collections.abc import Sequence
from typing import Any, NewType, TypeAlias

from ldaptor.protocols import pureldap

AttributeDescriptionList = NewType("AttributeDescriptionList", Sequence[Any])
FilterLike: TypeAlias = pureldap.LDAPFilter | pureldap.LDAPFilterSet
