"""Enum compatibility shim.

Segregated into its own file to break cyclic imports.
"""

import enum


class CdEEnumMeta:
    def __str__(self) -> str:
        """Restore old (<python-3.11) behaviour for IntEnums.

        Previously `str(e)` would produce something like 'MyEnum.member' but
        now it produces something like '1'. Sadly this loses all the enum
        information, which we need in many cases.
        """
        return enum.Enum.__str__(self)  # pyrefly: ignore[bad-argument-type]

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


class CdEIntFlag(CdEEnumMeta, enum.IntFlag):
    pass
