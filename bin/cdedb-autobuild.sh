#!/bin/bash

COMPLETE="NO"
if [[ $(basename $0) = "cdedb-autobuild-stage123.sh" ]]; then
    COMPLETE="YES"
fi;

REPODIR=/home/cdedb/cdedb2/
AUTOBUILDDIR=/home/cdedb/cdedb2/related/auto-build/
WWWDIR=/var/www/austausch/html/cdedb2/images/

QEMUOPTIONS="-nographic -m 1G -net nic,model=virtio -net user"

# get the most current state of the repository
cd $REPODIR
git pull
PORT=$(git --no-pager log -1 --format='%H')
export PORT QEMUOPTIONS

# does an up-to-date image exist?
if [[ -e $WWWDIR/cdedb-$PORT.qcow2 && $COMPLETE = "NO" ]]; then
    echo "port already exists... exiting"
    exit 0
else
    rm -f $WWWDIR/cdedb-$PORT.qcow2
fi;

# build images
cd $AUTOBUILDDIR

echo "free space report no. 1"
df

if [[ $COMPLETE = "YES" ]]; then
    echo "stage1"
    rm -f work/.done_*
    make install-stage1 || exit 101

    echo "stage2"
    make install-stage2 || exit 101
fi;

echo "stage3"
make install-stage3 || exit 101

echo "free space report no. 2"
df

echo "early cleanup, removing work/stage3.qcow2"
rm -f $AUTOBUILDDIR/work/stage3.qcow2
echo "[zap]"

echo "make fullimage"
make fullimage || exit 102
if [[ ! -e $AUTOBUILDDIR/images/cdedb-$PORT.qcow2 ]]; then
   echo "bailing out, as image does not exist ... exiting"
   exit 103
fi;

echo "make vdiimage"
make vdiimage || exit 103
if [ ! -e $AUTOBUILDDIR/images/cdedb-$PORT.vdi ]; then
   echo "bailing out, as viimage does not exist ... exiting"
   exit 105
fi;
gzip $AUTOBUILDDIR/images/cdedb-$PORT.vdi

echo "free space report no. 3"
df

# cleanup, move to WWW
echo "moving images"
rm -f $WWWDIR/cdedb-*.qcow2
rm -f $WWWDIR/cdedb-*.vdi.gz
mv $AUTOBUILDDIR/images/cdedb-$PORT.qcow2 $WWWDIR/
mv $AUTOBUILDDIR/images/cdedb-$PORT.vdi.gz $WWWDIR/
echo "images moved, removing intermediary images"
rm -f $AUTOBUILDDIR/work/*.qcow2
sudo fstrim -a -v
echo "done cleaning"
exit 1
