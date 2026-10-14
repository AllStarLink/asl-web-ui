prefix ?= /usr
pydir ?= $(prefix)/share/asl-web-ui/python
libexecdir ?= $(prefix)/libexec/asl-web-ui

PY_SRC = $(shell find asl_web_ui -name '*.py')
PY_INSTALLABLES = $(patsubst %, $(DESTDIR)$(pydir)/%, $(PY_SRC))
BINS = asl-web-ui-server
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
