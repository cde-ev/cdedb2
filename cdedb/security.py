"""Security related utility functions.

This is separated into its own file since we need to do some dance around
the secrets module, which is not available in Python 3.5.
"""

import string

from secrets import choice, token_hex


def secure_token_hex(nbytes: int = None) -> str:
    """Wrapper around secrets.token_hex."""
    return token_hex(nbytes)


def secure_random_ascii(length: int = 12, chars: str = None) -> str:
    """Create a random string of printable ASCII characters.

    :param length: number of characters in the returned string
    :param chars: string of characters to choose from
    """
    chars = chars or (string.ascii_letters + string.digits + string.punctuation)
    return ''.join(choice(chars) for _ in range(length))
