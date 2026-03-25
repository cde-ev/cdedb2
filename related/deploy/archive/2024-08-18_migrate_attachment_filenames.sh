# First, backup /var/lib/cdedb

read -p "Have you backed up /var/lib/cdedb? (y/N) "

if [ "$REPLY" != "y" ]; then
    echo "Please backup /var/lib/cdedb before running this script."
    exit 1
fi

sudo -u www-cde bin/migrate_attachment_filenames.py
