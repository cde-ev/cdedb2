#!/bin/bash

sed -i -e 's|https://db.cde-ev.de/db/bp/index.html?action=mailinglist&listname=|https://db.cde-ev.de/db/script/one/compat?listname=|g' /home/listadmin/bin/new-rklist
sed -i -e 's|https://db.cde-ev.de/db/bp/index.html?action=moderators&listname=|https://db.cde-ev.de/db/script/mod/compat?listname=|g' /home/listadmin/bin/new-rklist
sed -i -e 's|https://db.cde-ev.de/db/bp/index.html?action=mlconfig|https://db.cde-ev.de/db/script/all/compat|g' /home/listadmin/cdedb/related/mlconfig/call-mlconfig.sh
sed -i -e 's|https://db.cde-ev.de/db/bp/index.html?action=%s&|https://db.cde-ev.de/db/script/%s/compat?|g' /home/listadmin/cdedb/related/mlconfig/mlconfig.py
sed -i -e 's| % (self.list_address, rkdir, ltype)| % (self.list_address, rkdir, "one" if ltype == "mailinglist" else "mod")|g' /home/listadmin/cdedb/related/mlconfig/mlconfig.py

sed -i -e 's|https://db.cde-ev.de/db/bp/index.html?action=mailinglist&listname=|https://db.cde-ev.de/db/script/one/compat?listname=|g' /home/listadmin/rklists/*/get.sh
sed -i -e 's|https://db.cde-ev.de/db/bp/index.html?action=moderators&listname=|https://db.cde-ev.de/db/script/mod/compat?listname=|g' /home/listadmin/rklists/*/get.sh

sed -i -e 's|https://db.cde-ev.de/db/bp/index.html|https://db.cde-ev.de/db/script/bounce/compat|g' /home/listadmin/cdedb/related/bounceparser/definitions.py
sed -i -e 's|%s?action=bounce&username=%s&error=%s|%s?address=%s&error=%s|g' /home/listadmin/cdedb/related/bounceparser/bounceparser.py

# FIXME add authorization
