#!/bin/bash

echo "Generating initial page"
cat > "$1/doc/source/Handbuch_Email_Templates.rst" <<EOF
Email Templates
===============

This auto-generated page contains all email templates used in the
database.

.. This file should NOT be edited manually as any modifications will be lost.

EOF

echo "Cleaning email copy cache"
rm -rf "$1/doc/source/emails"
mkdir "$1/doc/source/emails"

for realm in core cde event assembly ml
do
    echo "Processing realm $realm"
    cat >> "$1/doc/source/Handbuch_Email_Templates.rst" <<EOF
.. _email-templates-for-realm-$realm:

Realm $realm
---------------

EOF
    mkdir "$1/doc/source/emails/$realm"
    for mail in $(find "$1/cdedb/frontend/templates/mail/$realm" -type f,l)
    do
        ln -si "../../../../$mail" "$1/doc/source/emails/$realm/$(basename $mail)"
        cat >> "$1/doc/source/Handbuch_Email_Templates.rst" <<EOF
.. _email-templates-for-realm-$realm-template-$(basename $mail):

Template $(basename $mail)
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

.. literalinclude:: emails/$realm/$(basename $mail)
    :language: jinja

EOF
    done
done
