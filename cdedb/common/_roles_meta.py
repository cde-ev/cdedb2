"""
This module contains some helper classes required for the Flags in 'cdedb.common.roles'.
"""

import enum
from typing import TYPE_CHECKING, Any, Literal, Self

from cdedb.uncommon.intenum import CdEEnum

if TYPE_CHECKING:
    from cdedb.common.roles import RealmSet, Roles, RoleSet


class _RolesMeta(enum.EnumType):
    """Custom metaclass for the 'Roles' EnumFlag to do some postprocessing."""

    def __new__(metacls, *args: Any, **kwargs: Any) -> "_RolesMeta":
        cls = super().__new__(metacls, *args, **kwargs)

        # The following code runs directly after the 'Roles' enum class has been fully
        #  created.

        for member in cls:  # type: ignore[var-annotated]
            # For every member replace the initial value for the '_required_roles'
            #  (which is a tuple of strings) with a set of enum members.
            #  This cannot be a 'RoleSet' yet, because that hasn't been defined at
            #  this point.
            member._required_roles = {
                # pyrefly: ignore [bad-index]
                cls[role]
                for role in member._required_roles
            }

        return cls


class _Roles(CdEEnum, metaclass=_RolesMeta):
    # TODO: This is actually str | None currently.
    marker: str
    _required_roles: "RoleSet"

    def __new__(cls, marker: str | None = None, *required_roles: str) -> Self:
        # This method creates the enum members for the 'Roles' enum.
        # First set up standard enum member things.
        # We determine the value automatically instead of reading it from the
        #  definition to avoid having 'enum.auto()' or numerical values everywhere.
        # Since this is no longer an 'EnumFlag', the values don't actually need to be
        #  powers of 2.
        value = 2 ** len(cls.__members__)
        obj = object.__new__(cls)
        obj._value_ = value

        # Store the additional data.
        obj.marker = marker  # type: ignore[assignment]
        # This tuple of strings is turned into a set of members by the metaclass.
        obj._required_roles = required_roles  # type: ignore[assignment]
        return obj

    @property
    def required_roles(self) -> "RoleSet":
        # ruff: ignore[import-outside-top-level]
        from cdedb.common.roles import RoleSet

        return RoleSet(self._required_roles)

    # Allow sorting.
    def __lt__(self, other: Self) -> bool:
        return self.value < other.value


class _RealmsMeta(enum.EnumType):
    """Custom metaclass for the 'Realms' EnumFlag to do some postprocessing."""

    def __new__(metacls, *args: Any, **kwargs: Any) -> "_RealmsMeta":
        cls = super().__new__(metacls, *args, **kwargs)

        # The following code runs directly after the 'Realms' enum class has been fully
        #  created.

        for member in cls:  # type: ignore[var-annotated]
            # For every member replace the initial value for the '_implied_realms'
            #  (which is a tuple of strings) with a set of enum members.
            #  This cannot be a 'RealmSet' yet, because that hasn't been defined at
            #  this point.
            member._implied_realms = {
                # pyrefly: ignore [bad-index]
                cls[realm]
                for realm in member._implied_realms
            }

        return cls


type RealmRole = Literal[Roles.cde, Roles.event, Roles.assembly, Roles.ml]


class _Realms(CdEEnum, metaclass=_RealmsMeta):
    role: RealmRole
    admin_role: "Roles"
    _implied_realms: "RealmSet"

    def __new__(
        cls,
        value: int,
        realm_role: RealmRole,
        admin_role: "Roles",
        *implied_realms: str,
    ) -> Self:
        # This method creates the enum members.
        # First set up standard enum member things.
        obj = object.__new__(cls)
        obj._value_ = value

        # Store additional data.
        obj.role = realm_role
        obj.admin_role = admin_role
        # This tuple of strings is turned into a set of members by the metaclass.
        obj._implied_realms = implied_realms  # type: ignore[assignment]
        return obj

    @property
    def implied_realms(self) -> "RealmSet":
        # ruff: ignore[import-outside-top-level]
        from cdedb.common.roles import RealmSet

        return RealmSet(self._implied_realms)

    # Allow sorting.
    def __lt__(self, other: Self) -> bool:
        return self.value < other.value


class _AdminViews(CdEEnum):
    required_roles: tuple["RoleSet | Roles", ...]

    def __new__(cls, *required_roles: "RoleSet | Roles") -> Self:
        # This method creates the enum members for the 'Roles' enum.
        # First set up standard enum member things.
        # We determine the value automatically instead of reading it from the
        #  definition to avoid having 'enum.auto()' or numerical values everywhere.
        # Since this is no longer an 'EnumFlag', the values don't actually need to be
        #  powers of 2.
        value = 2 ** len(cls.__members__)
        obj = object.__new__(cls)
        obj._value_ = value
        obj.required_roles = required_roles
        return obj
