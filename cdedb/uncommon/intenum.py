"""Enum compatibility shim.

Segregated into its own file to break cyclic imports.
"""

import enum
import types
import typing
from collections.abc import Iterable, Set
from typing import Self, cast


class CdEEnumMeta:
    def __str__(self) -> str:
        """Restore old (<python-3.11) behaviour for IntEnums.

        Previously `str(e)` would produce something like 'MyEnum.member' but
        now it produces something like '1'. Sadly this loses all the enum
        information, which we need in many cases.
        """
        return enum.Enum.__str__(self)

    __repr__ = __str__

    def __format__(self, format_spec: str) -> str:
        """Clean up ripple effects of the above change.

        __format__ shall still produce the integer representation as before.
        """
        if isinstance(self, int):
            return int.__format__(int(self), format_spec)
        return super().__format__(format_spec)


class CdEIntEnum(CdEEnumMeta, enum.IntEnum):
    pass


class CdEEnum(CdEEnumMeta, enum.Enum):
    pass


class FlagSet[T: (CdEEnum | CdEIntEnum)](frozenset[T]):
    def has(self, flag: T | Self) -> bool:
        """
        "Convenience" method with similar syntax to 'has_any' and 'has_all'.

        'some_flags.has(Flag.a)'
        is equivalent to
        'Flag.a in some_flags'.

        'some_flags.has({Flag.a, Flag.b})'
        is equivalent to
        '{Flag.a, Flag.b} <= some_flags'.
        """
        return flag in self

    def has_any(self, *flags: T | Self) -> bool:
        """Convenience method.

        'some_flags.has_any(Flag.a, Flag.b, Flag.c)'
        is equivalent to
        '{Flag.a, Flag.b, Flag.c} & some_flags'.

        However
        'some_flags.has_any(Flag.a, {Flag.b, Flag.c})'
        is equivalent to
        '{Flag.a} & some_flags or {Flag.b, Flag.c} <= some_flags'.
        """
        return any(self.has(flag) for flag in flags)

    def has_all(self, *flags: T | Self) -> bool:
        """Convenience method.

        'some_flags.has_all(Flag.a, Flag.b, Flag.c)'
        is equivalent to
        'some_flags.has_all(Flag.a, {Flag.b, Flag.c})'
        and
        '{Flag.a, Flag.b, Flag.c} <= some_flags'.

        Note that this means it behaves slightly different than 'has_any'.
        """
        return all(self.has(flag) for flag in flags)

    @classmethod
    def enum_cls(cls) -> type[T]:
        """Retrieve the generic argument of the class.

        >>> from cdedb.common.roles import RoleSet, RealmSet, AdminViewSet
        >>> RoleSet.enum_cls()
        <enum 'Roles'>
        >>> RealmSet.enum_cls()
        <enum 'Realms'>
        >>> AdminViewSet.enum_cls()
        <enum 'AdminViews'>

        This only works correctly for actual subclasses:

        >>> FlagSet[int].enum_cls()
        T
        """
        return typing.get_args(types.get_original_bases(cls)[0])[0]

    def __new__(cls, iterable: Iterable[T] = (), /) -> Self:
        ret = super().__new__(cls, iterable)
        if not all(isinstance(x, cls.enum_cls()) for x in iterable):
            raise TypeError
        return ret

    def __and__(self, value: Self | Set[T] | T, /) -> Self:  # type: ignore[override]
        """Allow intersecting with other instances or single enum members.

        Additionally restrict to intersecting with Self or Set[T], rather than any set.

        >>> from cdedb.common.roles import RoleSet, Roles
        >>> RoleSet({Roles.persona, Roles.anonymous}) & RoleSet({Roles.persona})
        RoleSet.persona
        >>> RoleSet({Roles.persona, Roles.anonymous}) & Roles.persona
        RoleSet.persona
        """
        if not isinstance(value, Iterable):
            # pyrefly: ignore [redundant-cast]
            value = self.__class__({cast(T, value)})
        if not isinstance(value, self.__class__):
            value = self.__class__(value)
        if not all(isinstance(x, self.enum_cls()) for x in value):
            raise TypeError
        return self.__class__(super().__and__(value))

    def __rand__(self, value: T, /) -> Self:
        """Allow the reverse intersection with enum members.

        >>> from cdedb.common.roles import RoleSet, Roles
        >>> Roles.persona & RoleSet({Roles.persona, Roles.anonymous})
        RoleSet.persona
        """
        return self.__and__(value)

    def __sub__(self, value: Self | Set[T] | T, /) -> Self:  # type: ignore[override]
        """Allow substracting other instances or single enum members.

        Additionally restrict to substracting Self or Set[T], rather than any set.

        >>> from cdedb.common.roles import RoleSet, Roles
        >>> RoleSet({Roles.persona, Roles.anonymous, Roles.cde}) - RoleSet({Roles.anonymous, Roles.cde})
        RoleSet.persona
        >>> RoleSet({Roles.persona, Roles.anonymous, Roles.cde}) - Roles.anonymous
        RoleSet.persona|cde
        """
        if not isinstance(value, Iterable):
            # pyrefly: ignore [redundant-cast]
            value = self.__class__({cast(T, value)})
        if not isinstance(value, self.__class__):
            value = self.__class__(value)
        if not all(isinstance(x, self.enum_cls()) for x in value):
            raise TypeError
        return self.__class__(super().__sub__(value))

    def __or__(self, value: Self | Set[T] | T, /) -> Self:  # type: ignore[override]
        """Allow union with instances or single enum members.

        Additionally restrict to unions with Self, rather than any set.

        >>> from cdedb.common.roles import RoleSet, Roles
        >>> RoleSet({Roles.persona, Roles.anonymous}) | RoleSet({Roles.anonymous, Roles.cde})
        RoleSet.anonymous|persona|cde
        >>> RoleSet({Roles.persona}) | Roles.cde
        RoleSet.persona|cde
        """
        if not isinstance(value, Iterable):
            # pyrefly: ignore [redundant-cast]
            value = self.__class__({cast(T, value)})
        if not isinstance(value, self.__class__):
            value = self.__class__(value)
        if not all(isinstance(x, self.enum_cls()) for x in value):
            raise TypeError
        return self.__class__(super().__or__(set(value)))

    def __ror__(self, value: T, /) -> Self:
        """Allow the reverse union with enum members.

        >>> from cdedb.common.roles import RoleSet, Roles
        >>> Roles.cde | RoleSet({Roles.persona})
        RoleSet.persona|cde
        """
        return self.__or__(value)

    def __contains__(self, o: T | Self | Set[T], /) -> bool:  # type: ignore[override]
        """Modify containment checks to work with instances of self.

        >>> from cdedb.common.roles import RoleSet, Roles
        >>> Roles.cde in RoleSet({Roles.persona})
        False
        >>> Roles.cde in RoleSet({Roles.persona, Roles.cde})
        True
        >>> RoleSet({Roles.cde}) in RoleSet({Roles.persona})
        False
        >>> RoleSet({Roles.cde}) in RoleSet({Roles.persona, Roles.cde})
        True
        >>> RoleSet({Roles.persona, Roles.cde}) in RoleSet({Roles.persona, Roles.cde})
        True
        >>>
        """
        if not isinstance(o, Iterable):
            if not isinstance(o, self.enum_cls()):
                raise TypeError
            return super().__contains__(o)
        if not isinstance(o, self.__class__):
            o = self.__class__(o)
        if not all(isinstance(x, self.enum_cls()) for x in o):
            raise TypeError
        return self.has_all(*o)

    def __invert__(self) -> Self:
        """Allow inverting self, by returning the complement based on the enum.

        >>> from cdedb.common.roles import RealmSet, Realms
        >>> ~RealmSet({Realms.cde, Realms.event})
        RealmSet.ml|assembly
        >>> ~Realms.all()
        RealmSet.None
        """
        return self.__class__(self.enum_cls()) - self  # type: ignore[arg-type]

    def __repr__(self) -> str:
        """Print the FlagSet similar to a combined EnumFlag.

        >>> from cdedb.common.roles import RoleSet, Roles
        >>> repr(Roles.cde)
        'Roles.cde'
        >>> repr(RoleSet({Roles.cde}))
        'RoleSet.cde'
        >>> repr(RoleSet())
        'RoleSet.None'
        >>> repr(RoleSet({Roles.persona, Roles.anonymous, Roles.cde}))
        'RoleSet.anonymous|persona|cde'
        """
        enum_cls = self.enum_cls()
        if not self:
            return f"{self.__class__.__name__}.None"
        # Gather the member names in enum iteration order.
        present_members: list[str] = [
            member.name for member in cast(Iterable[T], enum_cls) if member in self
        ]
        return f"{self.__class__.__name__}.{'|'.join(present_members)}"

    def as_strings(self) -> set[str]:
        """Return set of member names, mostly for backwards compatibility."""
        return {member.name for member in self}


class CdEFlag(CdEEnumMeta, enum.Flag):
    @classmethod
    def none(cls) -> Self:
        return cls(0)

    @classmethod
    def all(cls) -> Self:
        return ~cls.none()

    @classmethod
    def union(cls, flags: Iterable[Self]) -> Self:
        ret = cls.none()
        for f in flags:
            ret |= f
        return ret
