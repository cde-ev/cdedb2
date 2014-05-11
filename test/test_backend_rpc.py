#!/usr/bin/env python3

import unittest

## We honour the warning, that cdedb.backend.rpc should not be imported
## (otherwise logging for pyro may break). It is a small part and well used
## by all backends, so it gets a lot of implicit coverage.

class TestRPC(unittest.TestCase):
    pass
