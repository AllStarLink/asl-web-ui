prefix ?= /usr
wwwdir ?= $(prefix)/share/asl-web-ui/www

# npm resolves only packages published before this date (the two-week rule
# for new versions). Update it deliberately when upgrading dependencies.
NPM_BEFORE ?= 2026-09-30

.PHONY: all frontend lock check install clean

all frontend: dist/index.html

# Our own stamp: npm rewrites node_modules/.package-lock.json even with
# --package-lock-only, so that file cannot tell whether packages are installed.
node_modules/.asl-installed: package.json package-lock.json
	npm ci --ignore-scripts --no-audit --no-fund
	touch $@

dist/index.html: node_modules/.asl-installed build.mjs $(shell find public src -type f)
	npx tsc -p .
	node build.mjs

# Regenerate package-lock.json after editing package.json.
lock:
	npm install --package-lock-only --ignore-scripts --no-audit --no-fund --before=$(NPM_BEFORE)

check: node_modules/.asl-installed
	npx tsc -p .

# Installs the already-built bundle; it does not build (no Node.js needed).
install:
	test -f dist/index.html || { echo "frontend/dist missing: run 'make frontend' first" >&2; exit 1; }
	install -d $(DESTDIR)$(wwwdir)
	cp -r dist/. $(DESTDIR)$(wwwdir)/
	find $(DESTDIR)$(wwwdir) -type d -exec chmod 0755 {} +
	find $(DESTDIR)$(wwwdir) -type f -exec chmod 0644 {} +

clean:
	rm -rf dist node_modules
