#!/bin/bash

EXENAME=$(basename $0)

if [[ "$EXENAME" == isolated-test.sh ]]; then
    ARGSPEC=(portprefix branch)
elif [[ "$EXENAME" == isolated-evolution.sh ]]; then
    ARGSPEC=(portprefix oldbranch newbranch)
else
    echo "Unknown command"
    exit
fi

if [[ $# -ne ${#ARGSPEC[@]} ]]; then
    echo "Usage: $(basename $0) ${ARGSPEC[@]}"
    echo "       portprefix should be a number between 10 and 64"
    echo "       git names can generally be any reference acceptable to git"
    exit
fi

CONTAINER="/tmp/cdedb-test-container-$1.qcow2"

if [[ -f "$CONTAINER" ]]; then
    echo "Already in use!"
    exit
fi

REPOPATH=$(pwd)/$(dirname $0)/..
BASEIMAGE=${BASEIMAGE:-${REPOPATH}/related/auto-build/images/anautobuild.qcow2}
# The base image has to be a recent autobuild. It should never be modified
# (i.e. never be used as direct source for a VM). Instead it's just the
# backing store for ephemeral images.

if [[ ! -f "$BASEIMAGE" ]]; then
    echo "Base image not found!"
    exit
fi

qemu-img create -f qcow2 -b "$BASEIMAGE" "$CONTAINER"

qemu-system-x86_64 -m 1G -enable-kvm -device virtio-rng-pci \
                   -net nic,model=virtio -nographic\
                   -net "user,hostfwd=tcp:127.0.0.1:${1}022-:22" \
                   -drive file="$CONTAINER",if=virtio,cache=unsafe &

sleep 30

ssh -p "${1}022" cdedb@localhost /cdedb2/bin/inside-"${EXENAME}" "$@"

sleep 30

rm -f "$CONTAINER"
