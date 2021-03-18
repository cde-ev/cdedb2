# Makefile
# for portability reasons keept it a file for gmake

DISTDIR ?= distfiles
WORKDIR ?= work
IMAGEDIR ?= images
PORT ?= $(shell git --no-pager log -1 --format='%H')
# DEPLOYMENT_KEY_PATH has to be provided

FETCH ?= wget
AR ?= ar
TAR ?= bsdtar
AWK ?= awk
QEMU ?= kvm
QEMUIMG ?= qemu-img
BUNZIP ?= bunzip2
MKISOFS ?= genisoimage

QEMUOPTIONS ?= -m 1G -enable-kvm -net nic,model=virtio -net user,hostfwd=tcp:127.0.0.1:20022-:22,hostfwd=tcp:127.0.0.1:20443-:443,hostfwd=tcp:127.0.0.1:20080-:80

QEMUCACHING ?= writethrough

DEBVERSION = 10.8.0
NETINSTISO = debian-${DEBVERSION}-amd64-netinst.iso

DISTINFO_DATA?= ${AWK} -v alg=$$algo -v file=$${file} \
	'$$1 == alg && $$2 == "(" file ")" {print $$4}' distinfo

STAGE1DEPS = $(shell [ -e ${IMAGEDIR}/stage1.qcow2 ] || echo "install-stage1")
STAGE2DEPS = $(shell [ -e ${IMAGEDIR}/stage1.qcow2 ] || echo "install-stage2")
STAGE3DEPS = $(shell [ -e ${IMAGEDIR}/cdedb.qcow2 ] || echo "install")
FILES = $(shell find files -type f)


showconf:
	@echo "DISTDIR:    ${DISTDIR}"
	@echo "WORKDIR:    ${WORKDIR}"
	@echo "IMAGEDIR:   ${IMAGEDIR}"
	@echo
	@echo "So far we have the targets: "
	@echo
	@echo "stage     |  targets "
	@echo "--------------------------------------------------- "
	@echo "prepare:  |  fetch checksum "
	@echo "stage1:   |  build-stage1 install-stage1"
	@echo "stage2:   |  build-stage2 install-stage2"
	@echo "stage3:   |  build-stage3 install-stage3"
	@echo "stagevdi: |  build-stagevdi"
	@echo "use:      |  run"
	@echo "          |     "
	@echo "admin:    |  fullimage vdiimage clean mrproper"


fetch: ${WORKDIR}/.done_fetch
${WORKDIR}/.done_fetch:
	[ -d ${WORKDIR} ] || (mkdir -p ${WORKDIR} && chmod 755 ${WORKDIR})
	[ -d ${DISTDIR} ] || (mkdir -p ${DISTDIR} && chmod 755 ${DISTDIR})
	[ -f ${DISTDIR}/${NETINSTISO} ] || (cd ${DISTDIR} && ${FETCH} https://cdimage.debian.org/cdimage/release/${DEBVERSION}/amd64/iso-cd/${NETINSTISO})
	touch $@

checksum:${WORKDIR}/.done_checksum
${WORKDIR}/.done_checksum: ${WORKDIR}/.done_fetch
	chmod u+x bin/*/*
	PATH=$$PATH:./bin/`uname`; \
	for algo in md5 sha256; \
		do MKSUM=`$$algo < ${DISTDIR}/${NETINSTISO}`; \
		CKSUM=`file=${NETINSTISO}; ${DISTINFO_DATA}`; \
		echo ${NETINSTISO} "has real  " $$algo "sum" $$MKSUM; \
		echo ${NETINSTISO} "has stored" $$algo "sum" $$CKSUM; \
		if [ "$$MKSUM" != "$$CKSUM" ]; \
			then echo "Checksum mismatch!"; \
			exit 1; \
		fi \
	done
	mkdir -p ${WORKDIR}
	touch $@

extract:${WORKDIR}/.done_extract
${WORKDIR}/.done_extract:${WORKDIR}/.done_checksum ${FILES}
	rm -rf ${WORKDIR}/bootstrap
	mkdir -p ${WORKDIR}/bootstrap
	chmod u+x bin/*/*
	-PATH=$$PATH:./bin/`uname`; ${TAR} -xf ${DISTDIR}/${NETINSTISO} -C ${WORKDIR}/bootstrap
	chmod -R u+w ${WORKDIR}/bootstrap
	isoinfo -R -x /isolinux/isolinux.bin -i ${DISTDIR}/${NETINSTISO} > ${WORKDIR}/bootstrap/isolinux/isolinux.bin
	touch $@

patch:${WORKDIR}/.done_patch
${WORKDIR}/.done_patch:${WORKDIR}/.done_extract
	for patch in `ls files/patch* | sort`; \
		do echo "Applying patch" $$patch; \
		patch -p0 -d ${WORKDIR}/bootstrap < $$patch; \
	done
	cp files/preseed.cfg ${WORKDIR}/bootstrap/install.amd/
	cd ${WORKDIR}/bootstrap/install.amd && gunzip initrd.gz
	cd ${WORKDIR}/bootstrap/install.amd && echo preseed.cfg | cpio -ov --format=newc -A -F initrd
	rm -f ${WORKDIR}/bootstrap/install.amd/preseed.cfg
	cd ${WORKDIR}/bootstrap/install.amd && gzip initrd
	touch $@

cdimage:${WORKDIR}/.done_cdimage
${WORKDIR}/.done_cdimage:${WORKDIR}/.done_patch
	chmod u+w bin/*/*
	PATH=$$PATH:./bin/`uname`; \
	${MKISOFS} -o ${WORKDIR}/bootstrap.iso -r -J -no-emul-boot -boot-load-size 4 -boot-info-table \
	-b isolinux/isolinux.bin -c isolinux/boot.cat ${WORKDIR}/bootstrap
	touch $@

build-stage1:${WORKDIR}/.done_stage1
${WORKDIR}/.done_stage1:${WORKDIR}/.done_cdimage
	rm -f ${WORKDIR}/stage1.qcow2
	${QEMUIMG} create -f qcow2 ${WORKDIR}/stage1.qcow2 10G
	${QEMU} ${QEMUOPTIONS} -no-reboot -drive file=${WORKDIR}/stage1.qcow2,cache=${QEMUCACHING},if=virtio -drive file=${WORKDIR}/bootstrap.iso,media=cdrom,index=2 -boot order=d
	touch $@

${IMAGEDIR}/stage1.qcow2: ${STAGE1DEPS}
install-stage1: ${WORKDIR}/.done_install-stage1
${WORKDIR}/.done_install-stage1:${WORKDIR}/.done_stage1
	[ -d ${IMAGEDIR} ] || (mkdir -p ${IMAGEDIR} && chmod 755 ${IMAGEDIR})
	${QEMUIMG} convert -c -f qcow2 -O qcow2 ${WORKDIR}/stage1.qcow2 ${IMAGEDIR}/stage1.qcow2
	touch $@

stage2cd:${WORKDIR}/.done_stage2cd
${WORKDIR}/.done_stage2cd:${WORKDIR}/.done_checksum files/stage2-install
	rm -rf ${WORKDIR}/stage2cd
	mkdir ${WORKDIR}/stage2cd
	cp files/stage2-install ${WORKDIR}/stage2cd/cdedb-install
	chmod 755 ${WORKDIR}/stage2cd/cdedb-install
	cp files/call-cdedbinstall ${WORKDIR}/stage2cd/init
	cp files/stage2/* ${WORKDIR}/stage2cd/
	cp ../../doc/source/motd.txt ${WORKDIR}/stage2cd/
ifndef DEPLOYMENT_KEY_PATH
	$(error Must provide deployment key (i.e. ssh key for user with access to Gitea))
endif
	cp "${DEPLOYMENT_KEY_PATH}" ${WORKDIR}/stage2cd/ssh_user_rsa_key
	cp "${DEPLOYMENT_KEY_PATH}.pub" ${WORKDIR}/stage2cd/ssh_user_rsa_key.pub
	chmod 755 ${WORKDIR}/stage2cd/init
	chmod u+x bin/*/*
	PATH=$$PATH:./bin/`uname`; \
	${MKISOFS} -R -o ${WORKDIR}/stage2cd.iso ${WORKDIR}/stage2cd
	touch $@

build-stage2:${WORKDIR}/.done_stage2
${WORKDIR}/.done_stage2:${WORKDIR}/.done_stage2cd ${IMAGEDIR}/stage1.qcow2 | ${WORKDIR}
	rm -f ${WORKDIR}/stage2.qcow2
	${QEMUIMG} create -b `readlink -f ${IMAGEDIR}/stage1.qcow2` -f qcow2 ${WORKDIR}/stage2.qcow2
	(cd ${WORKDIR} && ${QEMU} ${QEMUOPTIONS} -no-reboot -boot order=c -drive file=stage2.qcow2,if=virtio,cache=${QEMUCACHING} -drive file=stage2cd.iso,media=cdrom,index=2)
	touch $@

${IMAGEDIR}/stage2.qcow2: ${STAGE2IMAGEDEPS}
install-stage2: ${WORKDIR}/.done_install-stage2
${WORKDIR}/.done_install-stage2:${WORKDIR}/.done_stage2
	[ -d ${IMAGEDIR} ] || (mkdir -p ${IMAGEDIR} && chmod 755 ${IMAGEDIR})
	${QEMUIMG} convert -c -f qcow2 -O qcow2 ${WORKDIR}/stage2.qcow2 ${IMAGEDIR}/stage2.qcow2
	touch $@

stage3cd:${WORKDIR}/.done_stage3cd
${WORKDIR}/.done_stage3cd:${WORKDIR}/.done_checksum files/stage3-install ${FILES} \
		| ${WORKDIR}
	rm -rf ${WORKDIR}/stage3cd
	mkdir ${WORKDIR}/stage3cd
	cp files/stage3-install ${WORKDIR}/stage3cd/cdedb-install
	chmod 755 ${WORKDIR}/stage3cd/cdedb-install
	cp files/call-cdedbinstall ${WORKDIR}/stage3cd/init
	${MKISOFS} -R -o ${WORKDIR}/stage3cd.iso ${WORKDIR}/stage3cd
	touch $@

build-stage3:${WORKDIR}/.done_stage3-${PORT}
${WORKDIR}/.done_stage3-${PORT}:${WORKDIR}/.done_stage3cd ${IMAGEDIR}/stage2.qcow2 | ${WORKDIR}
	rm -f ${WORKDIR}/stage3.qcow2
	${QEMUIMG} create -b `readlink -f ${IMAGEDIR}/stage2.qcow2` -f qcow2 ${WORKDIR}/stage3.qcow2
	(cd ${WORKDIR} && ${QEMU} ${QEMUOPTIONS} -no-reboot -boot order=c -drive file=stage3.qcow2,if=virtio,cache=${QEMUCACHING} -drive file=stage3cd.iso,media=cdrom,index=2)
	touch $@

${IMAGEDIR}/stage3.qcow2: ${STAGE3IMAGEDEPS}
install-stage3: ${WORKDIR}/.done_install-stage3-${PORT}
${WORKDIR}/.done_install-stage3-${PORT}:${WORKDIR}/.done_stage3-${PORT}
	[ -d ${IMAGEDIR} ] || (mkdir -p ${IMAGEDIR} && chmod 755 ${IMAGEDIR})
	${QEMUIMG} convert -c -f qcow2 -O qcow2 ${WORKDIR}/stage3.qcow2 ${IMAGEDIR}/stage3.qcow2
	rm -f ${WORKDIR}/cdedb-run-${PORT}.qcow2
	${QEMUIMG} create -b `readlink -f ${IMAGEDIR}/stage3.qcow2` -f qcow2 ${WORKDIR}/cdedb-run-${PORT}.qcow2
	rm -f ${WORKDIR}/cdedb-run-this.qcow2
	ln -s `readlink -f ${WORKDIR}/cdedb-run-${PORT}.qcow2` ${WORKDIR}/cdedb-run-this.qcow2
	touch ${WORKDIR}/.done_install-stage3
	touch $@

fullimage: ${WORKDIR}/.done_fullimage-${PORT}
${WORKDIR}/.done_fullimage-${PORT}:${WORKDIR}/.done_install-stage3-${PORT}
	${QEMUIMG} convert -c -f qcow2 -O qcow2 ${WORKDIR}/cdedb-run-${PORT}.qcow2 ${IMAGEDIR}/cdedb-${PORT}.qcow2
	touch $@

stagevdicd:${WORKDIR}/.done_stagevdicd
${WORKDIR}/.done_stagevdicd:${WORKDIR}/.done_checksum files/stage3-install ${FILES} \
		| ${WORKDIR}
	rm -rf ${WORKDIR}/stagevdicd
	mkdir ${WORKDIR}/stagevdicd
	cp files/stage3-install ${WORKDIR}/stagevdicd/cdedb-install
	chmod 755 ${WORKDIR}/stagevdicd/cdedb-install
	cp files/call-cdedbinstall ${WORKDIR}/stagevdicd/init
	touch ${WORKDIR}/stagevdicd/vdi
	${MKISOFS} -R -o ${WORKDIR}/stagevdicd.iso ${WORKDIR}/stagevdicd
	touch $@

build-stagevdi:${WORKDIR}/.done_stagevdi-${PORT}
${WORKDIR}/.done_stagevdi-${PORT}:${WORKDIR}/.done_stagevdicd ${IMAGEDIR}/stage2.qcow2 | ${WORKDIR}
	rm -f ${WORKDIR}/stagevdi.qcow2
	${QEMUIMG} create -b `readlink -f ${IMAGEDIR}/stage2.qcow2` -f qcow2 ${WORKDIR}/stagevdi.qcow2
	(cd ${WORKDIR} && ${QEMU} ${QEMUOPTIONS} -no-reboot -boot order=c -drive file=stagevdi.qcow2,if=virtio,cache=${QEMUCACHING} -drive file=stagevdicd.iso,media=cdrom,index=2)
	touch $@

vdiimage: ${WORKDIR}/.done_vdiimage-${PORT}
${WORKDIR}/.done_vdiimage-${PORT}:${WORKDIR}/.done_stagevdi-${PORT}
	${QEMUIMG} convert -f qcow2 -O vdi ${WORKDIR}/stagevdi.qcow2 ${IMAGEDIR}/cdedb-${PORT}.vdi
	touch $@

run: ${WORKDIR}/.done_install-stage3
	echo "To access the web server: https://127.0.0.1:20443/"
	echo "To connect via ssh: ssh -p 20022 cdedb@localhost"
	echo " - the password is 'akademie' -"
	${QEMU} ${QEMUOPTIONS} -drive file=${WORKDIR}/cdedb-run-this.qcow2,if=virtio,cache=${QEMUCACHING}

makesum: ${WORKDIR}/.done_fetch
	rm -f distinfo && touch distinfo;
	PATH=$$PATH:./bin/`uname`; \
	for algo in md5 sha256; \
		do MKSUM=`$$algo < ${DISTDIR}/${NETINSTISO}`; \
		echo "$$algo (${NETINSTISO}) = $$MKSUM" >> distinfo; \
	done

clean:
	touch ${WORKDIR}
	chmod -R u+w ${WORKDIR}
	rm -rf ${WORKDIR}

cleansrc:
	rm -f *~ files/*~

mrproper:clean
	rm -rf ${IMAGEDIR}

.PHONY:showconf checksum extract cdimage cdedbcd cdedb install run patch \
	build-stage1 install-stage1 build-stage2 install-stage2 fullimage \
	build-stage3 install-stage3 fetch clean mrproper image makesum
