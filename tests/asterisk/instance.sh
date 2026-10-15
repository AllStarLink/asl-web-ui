#!/bin/bash
#
# A private, unprivileged Asterisk + app_rpt instance for development and
# tests, built from the installed ASL packages. It never touches the system
# Asterisk or /etc/asterisk.
#
#   tests/asterisk/instance.sh start DIR [RPT_CONF]   create DIR and start
#   tests/asterisk/instance.sh stop DIR
#   tests/asterisk/instance.sh cli DIR "command"      asterisk -rx
#
# DIR holds etc/, log/, lib/, db/ and spool/. The control socket lives under
# /run/user/$UID because Unix socket paths are limited to 108 characters.
# Use DIR/etc/asterisk.conf with "asl-web-ui-server --dev --asterisk-conf".

set -euo pipefail

HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
RECIPE="$HERE/../../docs/research/asterisk-test-instance"
ASTERISK=/usr/sbin/asterisk

cmd=${1:-}
dir=${2:-}
[[ -n "$cmd" && -n "$dir" ]] || { sed -n '6,13p' "$0"; exit 1; }
dir="$(realpath -m "$dir")"
rundir="/run/user/$(id -u)/asl-web-ui-asterisk-$(echo -n "$dir" | md5sum | cut -c1-8)"
conf="$dir/etc/asterisk.conf"

cli() { "$ASTERISK" -C "$conf" -rx "$1"; }

case $cmd in
start)
	mkdir -p "$dir"/{etc,log,lib,db,spool} "$rundir"
	for f in modules.conf logger.conf iax.conf extensions.conf; do
		cp "$RECIPE/$f" "$dir/etc/$f"
	done
	cp "${3:-$RECIPE/rpt.conf}" "$dir/etc/rpt.conf"
	sed -e "s|@TESTDIR@|$dir|g" -e "s|^astrundir => .*|astrundir => $rundir|" \
		"$RECIPE/asterisk.conf" > "$conf"
	: > "$dir/log/messages.log"
	setsid "$ASTERISK" -C "$conf" -f -n > "$dir/log/stdout.txt" 2>&1 < /dev/null &
	for _ in $(seq 1 100); do
		if [[ -S "$rundir/asterisk.ctl" ]] && cli "core waitfullybooted" > /dev/null 2>&1; then
			echo "Asterisk test instance running: $conf"
			exit 0
		fi
		read -r -t 0.2 < /dev/zero || true
	done
	echo "Asterisk did not start; see $dir/log/messages.log" >&2
	exit 1
	;;
stop)
	cli "core stop now" > /dev/null 2>&1 || true
	;;
cli)
	cli "${3:?command}"
	;;
*)
	sed -n '6,13p' "$0"
	exit 1
	;;
esac
