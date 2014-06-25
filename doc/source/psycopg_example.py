#!/usr/bin/env python3

import psycopg2
import psycopg2.extras
import psycopg2.extensions
psycopg2.extensions.register_type(psycopg2.extensions.UNICODE)
psycopg2.extensions.register_type(psycopg2.extensions.UNICODEARRAY)

dbname = 'cdb'
dbuser = 'cdb'
password = '987654321098765432109876543210'
port = 5432

conn = psycopg2.connect("dbname={} user={} password={} port={}".format(dbname, dbuser, password, port), cursor_factory=psycopg2.extras.RealDictCursor)
conn.set_client_encoding("UTF8")

query = "SELECT p.display_name, m.given_names FROM core.personas AS p JOIN cde.member_data AS m ON p.id = m.persona_id WHERE p.id = %s"
params = (1,)

with conn as con:
    with con.cursor() as cur:
        cur.execute(query, params)
        data = cur.fetchall()
        print(data)
