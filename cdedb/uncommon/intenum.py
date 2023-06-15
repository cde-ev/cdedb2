"""Enum compatibility shim.

Segregated into its own file to break cyclic imports.
"""


import enum


class CdEIntEnum(enum.IntEnum):
    def __str__(self: "CdEIntEnum") -> str:
        """Restore old (<python-3.11) behaviour for IntEnums.

        Previously `str(e)` would produce something like 'MyEnum.member' but
        now it produces something like '1'. Sadly this loses all the enum
        information, which we need in many cases.
        """
        return repr(self).removeprefix('<').split(':')[0]

    def __format__(self: "CdEIntEnum", format_spec: str) -> str:
        """Clean up ripple effects of the above change.

        __format__ shall still produce the integer representation as before.
        """
        return int.__format__(int(self), format_spec)
