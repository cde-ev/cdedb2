"""Provide an LDAP interface of the CdEDB using ldaptor.

This provides read-only access to users, including
- attributes (name, mail address, realms, admin bits)
- mailinglists they are subscribed to
- mailinglists they moderate
- events they organize
- assemblies the lead

For more information, look at the corresponding doc page.

Ldaptor is an async python library implementing the LDAP protocol. Ldaptor itself is
build on twisted, an async python framework. Twisted use a callback function approach to
handle async requests and stores them in so-called `Deferred` objects.
However, this is very tedious and hardly readable. Luckily, twisted offers a direct way
to use pythons asyncio directives (`async def` and `Future` objects) by converting them
to Deferred objects. Therefore, most of the code is written with asyncio directives,
which are converted to twisted's Deferred at the last moment.
"""
