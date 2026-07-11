"""Custom types for LDAP"""

from collections.abc import Sequence
from typing import Any, NewType

from ldaptor.protocols import pureldap

AttributeDescriptionList = NewType("AttributeDescriptionList", Sequence[Any])
type FilterLike = pureldap.LDAPFilter | pureldap.LDAPFilterSet
