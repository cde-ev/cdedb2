"""
This module contains some helper classes required for the Flags in 'cdedb.common.roles'.
"""

import enum
from typing import TYPE_CHECKING, Any, Literal, Self

from cdedb.uncommon.intenum import CdEEnum, CdEFlag

if TYPE_CHECKING:
    from cdedb.common.roles import Roles


class _RolesMeta(enum.EnumType):
    """Custom metaclass for the 'Roles' EnumFlag to do some postprocessing."""

    def __new__(metacls, *args: Any, **kwargs: Any) -> "_RolesMeta":
        cls = super().__new__(metacls, *args, **kwargs)
        for member in cls:  # type: ignore[var-annotated]
            member.required_roles = cls(0)
            for role in member._required_roles:
                member.required_roles |= cls[role]
            del member._required_roles

        return cls


class _Roles(CdEFlag, metaclass=_RolesMeta):
    # TODO: This is actually str | None currently.
    marker: str
    required_roles: Self

    def __new__(cls, marker: str | None = None, *required_roles: str) -> Self:
        value = 2 ** len(cls.__members__)
        obj = object.__new__(cls)
        obj._value_ = value
        obj.marker = marker  # type: ignore[assignment]
        obj._required_roles = required_roles  # type: ignore[attr-defined]
        return obj

    def as_set(self) -> set[str]:
        return {str(role.name) for role in self}

    def markers(self) -> list[str]:
        return [role.marker for role in self]


class _RealmsMeta(enum.EnumType):
    """Custom metaclass for the 'Roles' EnumFlag to do some postprocessing."""

    def __new__(metacls, *args: Any, **kwargs: Any) -> "_RealmsMeta":
        cls = super().__new__(metacls, *args, **kwargs)
        for member in cls:  # type: ignore[var-annotated]
            implied_realms = member._implied_realms
            member._implied_realms = cls(0)
            for realm in implied_realms:
                member._implied_realms |= cls[realm]

        return cls


type RealmRole = Literal[Roles.cde, Roles.event, Roles.assembly, Roles.ml]


class _Realms(CdEFlag, metaclass=_RealmsMeta):
    role: RealmRole
    admin_role: "Roles"
    _implied_realms: Self

    def __new__(
        cls,
        value: int,
        realm_role: RealmRole,
        admin_role: "Roles",
        *implied_realms: str,
    ) -> Self:
        obj = object.__new__(cls)
        obj._value_ = value
        obj.role = realm_role
        obj.admin_role = admin_role
        obj._implied_realms = implied_realms  # type: ignore[assignment]
        return obj

    def as_set(self) -> set[str]:
        return {str(realm.name) for realm in self}

    @property
    def implied_realms(self) -> Self:
        return self.__class__.union(realm._implied_realms for realm in self)


class _AdminViews(CdEEnum):
    required_roles: tuple["Roles", ...]

    def __new__(cls, *required_roles: "Roles") -> Self:
        value = 2 ** len(cls.__members__)
        obj = object.__new__(cls)
        obj._value_ = value
        obj.required_roles = required_roles
        return obj
