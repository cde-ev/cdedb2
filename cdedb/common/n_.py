"""Own file for n_, since we need it everywhere and produce import loops otherwise."""


def n_(x: str) -> str:
    """
    Alias of the identity for i18n.
    Identity function that shadows the gettext alias to trick pybabel into
    adding string to the translated strings.
    """
    return x
