"""Security related utility functions.

This is separated into its own file since we need to do some dance around
the secrets module, which is not available in Python 3.5.
"""

import string
try:
    from secrets import choice, token_hex
except ImportError:
    import random
    generator = random.SystemRandom()

    def choice(seq):
        return seq[generator.randrange(len(seq))]

    def token_hex(num=32):
        chars = '0123456789abcdef'
        return ''.join(choice(chars) for _ in range(num))

def secure_token_hex(*args, **kwargs):
    """Wrapper around secrets.token_hex."""
    return token_hex(*args, **kwargs)

def secure_random_ascii(length=12, chars=None):
    """Create a random string of printable ASCII characters.

    :type length: int
    :param length: number of characters in the returned string
    :type chars: str
    :param chars: string of characters to choose from
    :rtype: str
    """
    chars = chars or (string.ascii_letters + string.digits + string.punctuation)
    return ''.join(choice(chars) for _ in range(length))

