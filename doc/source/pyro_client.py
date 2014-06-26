#!/usr/bin/env python3

import Pyro4

ns = Pyro4.locateNS()
uri = ns.lookup("pyro_example")
server = Pyro4.Proxy(uri)
print(server.echo("Gaius Julius Caesar"))
