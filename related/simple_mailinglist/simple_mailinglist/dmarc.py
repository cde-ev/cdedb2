"""
Simple DMARC-lookup, using external 'host'-command.

:Version:   0.1

:Requires:  Python >= 2.7 / 3.2

:Author:    Roland Koebler <rk@simple-is-better.org>
:Copyright: Roland Koebler
:License:   MIT/X11-like, see module-__license__

:VCS:       $Id$
"""
from __future__ import unicode_literals

import subprocess

#TODO: add cache

def dmarc(domain):
    """Check DMARC-policy of a (sub)domain.

    Simple wrapper using the 'host' command for the lookup.
    (host -t TXT _dmarc.DOMAIN)

    :Parameters:
        - domain: domain/subdomain to check
    :Returns:
        -1: query failed (e.g. network error)
        0:  no DMARC-record
        1:  'none'
        2:  'quarantine'
        3:  'reject'
        4:  unknown/invalid DMARC policy
    :Raises:
        OSError if the 'host'-command is not installed
    """
    check_sp = False

    while domain.count(".") >= 1:
        # check domain
        p = subprocess.Popen(["host", "-t", "TXT", "_dmarc.%s" % domain], stdout=subprocess.PIPE, stderr=subprocess.PIPE, close_fds=True)
        (result, _) = p.communicate()
        ret = p.wait()
        #print(domain, result)
        if ret == 0:
            if b'"v=DMARC1;' in result:
                result = result[result.index(b'"v=DMARC1;')+10:]
                result = [e.strip() for e in result.split(b";")]
                if check_sp:
                    if b"sp=none" in result:
                        return 1
                    if b"sp=quarantine" in result:
                        return 2
                    if b"sp=reject" in result:
                        return 3
                if b"p=none" in result:
                    return 1
                if b"p=quarantine" in result:
                    return 2
                if b"p=reject" in result:
                    return 3
                return 4
        elif result.endswith(b"(NXDOMAIN)\n"):
            pass
        else:
            return -1
        # next: try parent domain
        domain = domain[domain.index(".")+1:]
        check_sp = True

    return 0
