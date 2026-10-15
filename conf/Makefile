sysconfdir ?= /etc/asl-web-ui
apacheconf ?= /etc/apache2/conf-available
unitdir ?= /usr/lib/systemd/system
polkitdir ?= /usr/share/polkit-1/rules.d

UNITS = $(wildcard systemd/*.service systemd/*.socket)

INSTALLABLES = \
	$(DESTDIR)$(sysconfdir)/asl-web-ui.ini \
	$(DESTDIR)$(sysconfdir)/nginx.conf \
	$(DESTDIR)$(apacheconf)/asl-web-ui.conf \
	$(DESTDIR)/etc/pam.d/asl-web-ui \
	$(DESTDIR)$(polkitdir)/50-asl-web-ui.rules \
	$(patsubst systemd/%, $(DESTDIR)$(unitdir)/%, $(UNITS))

.PHONY: install
install: $(INSTALLABLES)

$(DESTDIR)$(sysconfdir)/%: %
	install -D -m 0644 $< $@

$(DESTDIR)$(sysconfdir)/nginx.conf: nginx/asl-web-ui.conf
	install -D -m 0644 $< $@

$(DESTDIR)$(unitdir)/%: systemd/%
	install -D -m 0644 $< $@

$(DESTDIR)/etc/pam.d/%: pam/%
	install -D -m 0644 $< $@

$(DESTDIR)$(apacheconf)/%: apache/%
	install -D -m 0644 $< $@

$(DESTDIR)$(polkitdir)/%: polkit/%
	install -D -m 0644 $< $@
