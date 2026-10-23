#
# Build variables
#
# The checkout directory (asl-web-ui in CI, whatever it is locally).
SRCNAME = $(notdir $(CURDIR))
PKGNAME = asl-web-ui
RELVER = 0.7
DEBVER = 1
RELPLAT ?= deb$(shell lsb_release -rs 2> /dev/null)

BUILDABLES = backend conf doc frontend

ifdef ${DESTDIR}
DESTDIR=${DESTDIR}
endif

.PHONY: default install frontend check deb debchange debprep debclean podman-deb

default:
	@echo This does nothing, use 'make install' or 'make deb'

install:
	@echo DESTDIR=$(DESTDIR)
	$(foreach dir, $(BUILDABLES), $(MAKE) -C $(dir) install RELVER=$(RELVER);)

# Build the browser bundle (needs Node.js; the builder image provides it).
frontend:
	$(MAKE) -C frontend frontend RELVER=$(RELVER)

check:
	$(MAKE) -C backend check
	$(MAKE) -C frontend check

# debian/changelog is restored afterwards, whether or not the build succeeds.
deb:	debclean frontend debprep
	cp debian/changelog debian/changelog.save
	debchange --distribution stable --package $(PKGNAME) \
		--newversion $(EPOCHVER)$(RELVER)-$(DEBVER).$(RELPLAT) \
		"Autobuild of $(EPOCHVER)$(RELVER)-$(DEBVER) for $(RELPLAT)"
	dpkg-buildpackage -b --no-sign; rc=$$?; mv debian/changelog.save debian/changelog; exit $$rc

debchange:
	debchange --newversion $(RELVER)-$(DEBVER)
	debchange --release

debprep: debclean
	(cd .. && \
		rm -f $(PKGNAME)-$(RELVER) && \
		rm -f $(PKGNAME)-$(RELVER).tar.gz && \
		rm -f $(PKGNAME)_$(RELVER).orig.tar.gz && \
		ln -s $(SRCNAME) $(PKGNAME)-$(RELVER) && \
		tar --exclude=".git" --exclude="node_modules" -h -zcf $(PKGNAME)-$(RELVER).tar.gz $(PKGNAME)-$(RELVER) && \
		ln -s $(PKGNAME)-$(RELVER).tar.gz $(PKGNAME)_$(RELVER).orig.tar.gz )

debclean:
	rm -f ../$(PKGNAME)_$(RELVER)*
	rm -f ../$(PKGNAME)-$(RELVER)*
	rm -rf debian/$(PKGNAME)
	rm -f debian/files
	rm -rf debian/.debhelper/
	rm -f debian/debhelper-build-stamp
	rm -f debian/*.substvars
	rm -f debian/*.debhelper

# Build the package locally in the builder image with Podman (no publishing).
podman-deb:
	./builder/localbuild.sh
