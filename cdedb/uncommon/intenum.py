"""Enum compatibility shim.

Segregated into its own file to break cyclic imports.
"""

import enum
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


class CdEEnumNonFlagMeta(CdEEnumMeta):
    pass


class CdEIntEnum(CdEEnumNonFlagMeta, enum.IntEnum):
    pass


class CdEEnum(CdEEnumNonFlagMeta, enum.Enum):
    pass


class FlagSet[T: CdEEnumNonFlagMeta](frozenset[T]):
    def has(self, flag: T | Self) -> bool:
        """
        "Convenience" method with similar syntax to 'has_any' and 'has_all'.
        """
        if isinstance(flag, self.__class__):
            return self.has_all(*flag)
        return flag in self

    def has_any(self, *flags: T | Self) -> bool:
        """Convenience method.

        'some_flags.has_any(Flag.a, Flag.b, Flag.c)'
        is equivalent to
        '{Flag.a, Flag.b, Flag.c} & some_flags'.

        However
        'some_flags.has_any(Flag.a, {Flag.b, Flag.c})'
        does not have a direct equivalent.
        """
        ret = any(self.has(flag) for flag in flags)
        return ret

    def has_all(self, *flags: T | Self) -> bool:
        """Convenience method.

        'some_flags.has_all(Flag.a, Flag.b, Flag.c)'
        is equivalent to
        'some_flags.has_all(Flag.a, {Flag.b, Flag.c})'
        and
        '{Flag.a, Flag.b, Flag.c} in some_flags'.

        Note that this means it behaves slightly different than 'has_any'.
        """
        return all(self.has(flag) for flag in flags)

    def __and__(self, value: Set[object] | T, /) -> Self:
        if not isinstance(value, Iterable):
            value = {value}
        return self.__class__(super().__and__(set(value)))

    def __rand__(self, value: Set[object] | T, /) -> Self:
        return self & value

    def __sub__(self, value: Set[object], /) -> Self:
        return self.__class__(super().__sub__(set(value)))

    def __or__(self, value: Set[T] | T, /) -> Self:  # type: ignore[override]
        if not isinstance(value, Iterable):
            value = {value}
        return self.__class__(super().__or__(set(value)))

    def __ror__(self, value: Set[T] | T, /) -> Self:
        return self | value

    def __repr__(self) -> str:
        enum_cls = typing.get_args(self.__orig_bases__[0])[0]  # type: ignore[attr-defined]
        if not self:
            return f"{enum_cls.__name__}.None"
        present_members: list[str] = [
            member.name  # type: ignore[attr-defined]
            for member in cast(Iterable[T], enum_cls)
            if member in self
        ]
        return f"{enum_cls.__name__}.{'|'.join(present_members)}"


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

    def has(self, flag: Self) -> bool:
        """
        "Convenience" method with similar syntax to 'has_any' and 'has_all'.
        """
        return flag in self

    def has_any(self, *flags: Self) -> bool:
        """Convenience method.

        'some_flags.has_any(Flag.a, Flag.b, Flag.c)'
        is equivalent to
        'Flag.a|Flag.b|Flag.c & some_flags'.

        However
        'some_flags.has_any(Flag.a, Flag.b|Flag.c)'
        does not have a direct equivalent.
        """
        return any(flag in self for flag in flags)

    def has_all(self, *flags: Self) -> bool:
        """Convenience method.

        'some_flags.has_all(Flag.a, Flag.b, Flag.c)'
        is equivalent to
        'some_flags.has_all(Flag.a, Flag.b|Flag.c)'
        and
        'Flag.a|Flag.b|Flag.c in some_flags'.

        Note that this means it behaves slightly different than 'has_any'.
        """
        return all(flag in self for flag in flags)
