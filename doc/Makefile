prefix ?= /usr
mandir ?= $(prefix)/share/man

MAN8 = $(patsubst %.8.md, $(DESTDIR)$(mandir)/man8/%.8, $(wildcard *.8.md))

.PHONY: install
install: $(MAN8)

$(DESTDIR)$(mandir)/man8/%.8: %.8.md
	install -d $(dir $@)
	sed 's/@@HEAD-DEVELOP@@/$(or $(RELVER),devel)/' $< | pandoc -s -t man -o $@
