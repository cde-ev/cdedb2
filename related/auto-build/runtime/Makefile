QEMU ?= qemu-system-x86_64
IMAGE ?= $(shell ./select-qcow.sh 2>/dev/null)

.PHONY: help
#: Show this help.
help:
	@awk '/^#:/{c=substr($$0,3);next}c&&/^[[:alpha:]][[:alnum:]_-]+:/'\
'{print substr($$1,1,index($$1,":")),c}1{c=0}' $(MAKEFILE_LIST) | column -s: -t
	@echo
	@echo "First download an image from https://ssl.cde-ev.de/cdedb2/images/"
	@echo "After starting the VM point a browser at https://localhost:10443/db/"

.PHONY: start
#: Start the VM. (Place image in this folder.)
start:
	@./select-qcow.sh >>/dev/null && $(QEMU) -smp 2 -m 2G -enable-kvm \
		-device virtio-rng-pci -net nic,model=virtio \
		-net user,hostfwd=tcp:127.0.0.1:10022-:22 \
		-net user,hostfwd=tcp:127.0.0.1:10080-:80 \
		-net user,hostfwd=tcp:127.0.0.1:10389-:389 \
		-net user,hostfwd=tcp:127.0.0.1:10443-:443 \
		-net user,hostfwd=tcp:127.0.0.1:5000-:5000 \
		-drive file=$(IMAGE),cache=unsafe,if=virtio

.PHONY: mount
#: Mount the repository from inside the VM to the directory `./share`.
mount:
	sshfs -p 10022 cdedb@localhost:/cdedb2 ./share

.PHONY: login
#: Connect via ssh into the running VM.
login:
	ssh -p 10022 cdedb@localhost
