sysconfdir ?= /etc/asl-web-ui
apacheconf ?= /etc/apache2/conf-available

INSTALLABLES = \
	$(DESTDIR)$(sysconfdir)/asl-web-ui.ini \
	$(DESTDIR)$(sysconfdir)/nginx.conf \
	$(DESTDIR)$(apacheconf)/asl-web-ui.conf

.PHONY: install
install: $(INSTALLABLES)

$(DESTDIR)$(sysconfdir)/%: %
	install -D -m 0644 $< $@

$(DESTDIR)$(sysconfdir)/nginx.conf: nginx/asl-web-ui.conf
	install -D -m 0644 $< $@

$(DESTDIR)$(apacheconf)/%: apache/%
	install -D -m 0644 $< $@
