prefix ?= /usr
pydir ?= $(prefix)/share/asl-web-ui/python
libexecdir ?= $(prefix)/libexec/asl-web-ui

PY_SRC = $(shell find asl_web_ui asl_web_ui_auth asl_web_ui_priv -name '*.py')
PY_INSTALLABLES = $(patsubst %, $(DESTDIR)$(pydir)/%, $(PY_SRC))
BINS = asl-web-ui-server asl-web-ui-auth asl-web-ui-priv asl-web-ui-net44-routes asl-web-ui-https-sync
BIN_INSTALLABLES = $(patsubst %, $(DESTDIR)$(libexecdir)/%, $(BINS))

.PHONY: install check

install: $(PY_INSTALLABLES) $(BIN_INSTALLABLES)
ifdef RELVER
	sed -i 's/@@HEAD-DEVELOP@@/$(RELVER)/' $(DESTDIR)$(pydir)/asl_web_ui/__init__.py
endif

$(DESTDIR)$(pydir)/%.py: %.py
	install -D -m 0644 $< $@

$(DESTDIR)$(libexecdir)/%: bin/%
	install -D -m 0755 $< $@

check:
	python3 -m pytest -q -p no:cacheprovider
