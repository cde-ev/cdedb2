#!/usr/bin/env python3

import Pyro4

class Server:
    def echo(self, name):
        print("Hello {}".format(name))
        return {c for c in name}

daemon = Pyro4.Daemon()
uri = daemon.register(Server())
ns = Pyro4.locateNS()
ns.register("pyro_example", uri)
print("Registered {}.".format(uri))
daemon.requestLoop()
