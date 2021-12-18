BEGIN;
    DELETE FROM ldap.duas;
    INSERT INTO ldap.duas (cn, password_hash) VALUES
        ('admin',       'ADMIN_DUA_PASSWORD'),
        ('apache',      'APACHE_DUA_PASSWORD'),
        ('cloud',       'CLOUD_DUA_PASSWORD'),
        ('cyberaka',    'CYBERAKA_DUA_PASSWORD'),
        ('dokuwiki',    'DOKUWIKI_DUA_PASSWORD');
COMMIT;
