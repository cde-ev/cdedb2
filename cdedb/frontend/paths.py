#!/usr/bin/env python3

"""Routing table for the WSGI-application. This will get pretty big so put
it here where it is out of the way.
"""

import werkzeug.routing
rule = werkzeug.routing.Rule

class FilenameConverter(werkzeug.routing.BaseConverter):
    """Handles filename inputs in URL path."""
    regex = '[a-zA-Z0-9][-a-zA-Z0-9._]*'

#: Using a routing map allows to do lookups as well as the reverse process
#: of generating links to targets instead of hardcoding them.
CDEDB_PATHS = werkzeug.routing.Map((
    werkzeug.routing.EndpointPrefix('core/', (
        rule("/", methods=("GET", "HEAD"), endpoint="index"),
        rule("/error", methods=("GET", "HEAD"), endpoint="error"),
        rule("/login", methods=("POST",), endpoint="login"),
        rule("/logout", methods=("POST",), endpoint="logout"),
        rule("/mydata", methods=("GET", "HEAD"), endpoint="mydata"),
        rule("/changepassword", methods=("GET", "HEAD"),
             endpoint="change_password_form"),
        rule("/changepassword", methods=("POST",),
             endpoint="change_password"),
        rule("/resetpassword", methods=("GET", "HEAD"),
             endpoint="reset_password_form"),
        rule("/resetpasswordmail", methods=("GET", "HEAD"),
             endpoint="send_password_reset_link"),
        rule("/dopasswordreset", methods=("GET", "HEAD"),
             endpoint="do_password_reset_form"),
        rule("/dopasswordreset", methods=("POST",),
             endpoint="do_password_reset"),
        rule("/changeusername", methods=("GET", "HEAD"),
             endpoint="change_username_form"),
        rule("/changeusernamemail", methods=("GET", "HEAD"),
             endpoint="send_username_change_link"),
        rule("/dousernamechange/<int:persona_id>", methods=("GET", "HEAD"),
             endpoint="do_username_change_form"),
        rule("/showuser/<int:persona_id>", methods=("GET", "HEAD"),
             endpoint="show_user"),
        rule("/changeuser/<int:persona_id>", methods=("GET", "HEAD"),
             endpoint="change_user"),
        )),
    werkzeug.routing.EndpointPrefix('cde/', (
        werkzeug.routing.Submount('/cde', (
            rule("/", methods=("GET", "HEAD"), endpoint="index"),
            # this is here because of the changelog functionality
            rule("/dousernamechange/<int:persona_id>", methods=("POST",),
                endpoint="do_username_change"),
            rule("/showuser/<int:persona_id>", methods=("GET", "HEAD"),
                 endpoint="show_user"),
            rule("/changeuser/<int:persona_id>", methods=("GET", "HEAD"),
                 endpoint="change_user_form"),
            rule("/changeuser/<int:persona_id>", methods=("POST",),
                 endpoint="change_user"),
            rule("/listpendingchanges", methods=("GET", "HEAD"),
                 endpoint="list_pending_changes"),
            rule("/inspectchange/<int:persona_id>", methods=("GET", "HEAD"),
                 endpoint="inspect_change"),
            rule("/resolvechange/<int:persona_id>", methods=("POST",),
                 endpoint="resolve_change"),
            rule("/foto/<filename:foto>", methods=("GET", "HEAD"),
                 endpoint="get_foto"),
            rule("/setfoto/<int:persona_id>", methods=("GET", "HEAD"),
                 endpoint="set_foto_form"),
            rule("/setfoto/<int:persona_id>", methods=("POST",),
                 endpoint="set_foto"),
            )),
        )),
    werkzeug.routing.EndpointPrefix('event/', (
        werkzeug.routing.Submount('/event', (
            rule("/", methods=("GET", "HEAD"), endpoint="index"),
            rule("/showuser/<int:persona_id>", methods=("GET", "HEAD"),
                 endpoint="show_user"),
            rule("/changeuser/<int:persona_id>", methods=("GET", "HEAD"),
                 endpoint="change_user_form"),
            rule("/changeuser/<int:persona_id>", methods=("POST",),
                 endpoint="change_user"),
            )),
        ))
    ), converters={'filename' : FilenameConverter})
