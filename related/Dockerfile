FROM debian:buster-20200607
# mabe use apache image

RUN apt-get update && apt-get install --yes --no-install-recommends \
    openssl \
    && mkdir /etc/ssl/apache2 \
    && openssl req \
    -x509 \
    -newkey rsa:4096 \
    -out /etc/ssl/apache2/server.pem \
    -keyout /etc/ssl/apache2/server.key \
    -days 365 \
    -nodes \
    -subj "/C=DE/O=CdE e.V./CN=cdedb.local/emailAddress=cdedb@lists.cde-ev.de" \
    && apt-get purge --yes --autoremove openssl \
    && rm -rf /var/lib/apt/lists/*

# or fonts-lmodern instead of cm-super
RUN echo 'slapd slapd/password1 password s1n2t3h4d5i6u7e8o9a0s1n2t3h4d5i6u7e8o9a0' | debconf-set-selections \
    && echo 'slapd slapd/password2 password s1n2t3h4d5i6u7e8o9a0s1n2t3h4d5i6u7e8o9a0' | debconf-set-selections \
    && apt-get update \
    && apt-get install --yes --no-install-recommends \
    make \
    gettext \
    apache2 \
    libapache2-mod-wsgi-py3 \
    slapd \
    ldap-utils \
    \
    texlive \
    texlive-latex-extra \
    texlive-lang-german \
    texlive-luatex \
    cm-super \
    \
    python3 \
    python3-psycopg2 \
    python3-dateutil \
    python3-babel \
    python3-icu \
    python3-jinja2 \
    python3-tz \
    python3-sphinx \
    python3-lxml \
    python3-pil \
    python3-webtest \
    python3-werkzeug \
    python3-ldap3 \
    python3-passlib \
    python3-bleach \
    python3-magic \
    python3-guzzle-sphinx-theme \
    python3-zxcvbn \
    python3-markdown \
    python3-mailmanclient \
    python3-requests \
    pylint3 \
    \
    && rm -rf /var/lib/apt/lists/*

RUN mkdir /var/lib/cdedb/ \
    && mkdir /var/lib/cdedb/foto/ \
    && mkdir /var/lib/cdedb/minor_form/ \
    && mkdir /var/lib/cdedb/ballot_result/ \
    && mkdir /var/lib/cdedb/assembly_attachment/ \
    && mkdir /var/lib/cdedb/mailman_templates/ \
    && chown --recursive www-data:www-data /var/lib/cdedb/ \
    && mkdir /log \
    && chown www-data:www-data /log \
    \
    && useradd --system cdedb

WORKDIR /cdedb2

COPY . ./.git ./

RUN a2enmod ssl wsgi headers \
    && a2dissite 000-default \
    && echo "" > /etc/apache2/ports.conf \
    && cp ./related/auto-build/files/stage3/cdedb-site.conf /etc/apache2/sites-available \
    && cp ./related/auto-build/files/stage3/index.html /var/www/html/ \
    && chown www-data:www-data /var/www/html/index.html \
    && a2ensite cdedb-site \
    \
    && cp ./related/auto-build/files/stage3/localconfig.py ./cdedb/ \
    && chown cdedb:cdedb ./cdedb/localconfig.py \
    && chmod 644 ./cdedb/localconfig.py \
    && cp ./related/auto-build/files/stage3/mailman-htpasswd /etc/cdedb-mailman-htpasswd \
    && chown www-data:www-data /etc/cdedb-mailman-htpasswd \
    && chmod 640 /etc/cdedb-mailman-htpasswd

RUN apt-get update \
    && apt-get install --yes --no-install-recommends git \
    && rm -rf /var/lib/apt/lists/*

# missing gettext files
