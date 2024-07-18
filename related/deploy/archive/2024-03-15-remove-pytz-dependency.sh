#!/usr/bin/env sh

# Was previously pulled in implicitly through python3-tz
# but is required for zoneinfo to work.
apt install tzdata

python3 -m pip uninstall types-pytz

cat <<EOF
You may also uninstall pytz if nothing else depends on it.
It is likely installed through apt as python3-tz and through pip as pytz.
However, other application might depend on it.

For apt you can try to remove it using 'apt remove python3-tz'.
If this lists other packages for removal deny it with 'n'.
You may still list it as automatically-installed
such that it gets automatically removed if the other packages
are also removed in the future.
This can be done using 'apt-mark auto python3-tz'.

For pip there is no easy way to figure this out.
You could install pip-chill or pipdeptree
and check if pytz is listed in them
or only appears as a package other packages depend on.
In case the latter is true you may remove the package
using 'pip uninstall pytz'.
EOF
