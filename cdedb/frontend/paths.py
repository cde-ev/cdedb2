#!/usr/bin/env python3

"""Routing table for the WSGI-application. This will get pretty big so put
it here where it is out of the way.
"""

import werkzeug.routing
rule = werkzeug.routing.Rule

#: Using a routing map allows to do lookups as well as the reverse process
#: of generating links to targets instead of hardcoding them.
CDEDB_PATHS = werkzeug.routing.Map((
    werkzeug.routing.EndpointPrefix('core/', (
        rule("/", methods=("GET", "HEAD"), endpoint="index"),
        rule("/error", methods=("GET", "HEAD"), endpoint="error"),
        rule("/login", methods=("POST",), endpoint="login"),
        rule("/logout", methods=("POST",), endpoint="logout"),
        rule("/mydata", methods=("GET", "HEAD"), endpoint="mydata"),
        rule("/changedata", methods=("GET", "HEAD"), endpoint="change_data"),
        rule("/changepassword", methods=("GET", "HEAD"),
             endpoint="change_password_form"),
        rule("/changepassword", methods=("POST",), endpoint="change_password"),
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
        rule("/dousernamechange", methods=("GET", "HEAD"),
             endpoint="do_username_change_form"),
        rule("/dousernamechange", methods=("POST",),
             endpoint="do_username_change"),
        )),
    werkzeug.routing.EndpointPrefix('cde/', (
        werkzeug.routing.Submount('/cde', (
            rule("/", methods=("GET", "HEAD"), endpoint="index"),
            rule("/mydata", methods=("GET", "HEAD"), endpoint="mydata"),
            rule("/changedata", methods=("GET", "HEAD"),
                 endpoint="change_data_form"),
            rule("/changedata", methods=("POST",), endpoint="change_data"),
            rule("/changeusername", methods=("GET", "HEAD"),
                 endpoint="change_username_form"),
            rule("/changeusername", methods=("POST",),
                 endpoint="send_username_change_link"),
            rule("/dousernamechange", methods=("GET", "HEAD"),
                 endpoint="do_username_change_form"),
            rule("/dousernamechange", methods=("POST",),
                 endpoint="do_username_change"),
            )),
        )),
    werkzeug.routing.EndpointPrefix('event/', (
        werkzeug.routing.Submount('/event', (
            rule("/", methods=("GET", "HEAD"), endpoint="index"),
            rule("/mydata", methods=("GET", "HEAD"), endpoint="mydata"),
            rule("/changedata", methods=("GET", "HEAD"),
                 endpoint="change_data_form"),
            rule("/changedata", methods=("POST",), endpoint="change_data"),
            rule("/changeusername", methods=("GET", "HEAD"),
                 endpoint="change_username_form"),
            rule("/changeusername", methods=("POST",),
                 endpoint="send_username_change_link"),
            rule("/dousernamechange", methods=("GET", "HEAD"),
                 endpoint="do_username_change_form"),
            rule("/dousernamechange", methods=("POST",),
                 endpoint="do_username_change"),
            )),
        ))
    ))
