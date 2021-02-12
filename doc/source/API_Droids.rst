Droids
======

The accounts used for API access are called droids. These are separate from
the persona accounts which are bound to human beings. Instead each droid is
created for a specific task and possesses its own authentication token. The
token must be transmitted together with every request in the HTTP header
``X-CdEDB-API-Token``.

Currently we have the following droids:

- ``resolve``: Lookup of usernames (email addresses) and resolver into
  names. This is used by the CyberAka.

- ``quick_partial_export``: Data source for the template renderer in the
  offline VM. Only available in offline mode.
