#!/bin/sh
#
# Install the Node.js release that builds asl-web-ui's browser code.
#
# The builder image runs this script, and developers run it to get exactly
# the same Node.js and npm as the package builds. The version and the
# SHA-256 checksums of the release archives are pinned here, in one place;
# the archive is refused if its checksum does not match.
#
#   sudo builder/install-node.sh [PREFIX]      (default PREFIX: /opt/node)
#
# To upgrade, change NODE_VERSION and both checksums (from
# https://nodejs.org/dist/vVERSION/SHASUMS256.txt, after checking that
# file's signature as described at https://github.com/nodejs/node#verifying-binaries),
# then rebuild the builder image and rerun this script on your machine.

set -eu

NODE_VERSION=24.21.0
NODE_SHA256_X64=fd8e59d5a511510f6a298afb548f18c7d2b1be404d8b4a27d94fbe49f56cb2d6
NODE_SHA256_ARM64=6ad1325edbdb5649c379b75a237147a666c95d4f9ae8d340fef2d1575d289ad2

PREFIX=${1:-/opt/node}

case "$(dpkg --print-architecture)" in
	amd64) node_arch=x64; node_sha=$NODE_SHA256_X64 ;;
	arm64) node_arch=arm64; node_sha=$NODE_SHA256_ARM64 ;;
	*) echo "No pinned Node.js build for $(dpkg --print-architecture)" >&2; exit 1 ;;
esac

tmp=$(mktemp -d)
trap 'rm -rf "$tmp"' EXIT
archive="$tmp/node-v$NODE_VERSION-linux-$node_arch.tar.xz"

curl -fsSLo "$archive" "https://nodejs.org/dist/v$NODE_VERSION/node-v$NODE_VERSION-linux-$node_arch.tar.xz"
echo "$node_sha  $archive" | sha256sum -c -

# Replace an earlier Node.js installation in PREFIX completely; never empty
# a directory that holds anything else (such as /usr/local).
if [ -e "$PREFIX" ]; then
	if [ ! -x "$PREFIX/bin/node" ] || [ ! -f "$PREFIX/include/node/node_version.h" ]; then
		echo "$PREFIX exists and is not a Node.js installation; choose an empty or new directory." >&2
		exit 1
	fi
	rm -rf "$PREFIX"
fi
mkdir -p "$PREFIX"
tar -xJf "$archive" -C "$PREFIX" --strip-components=1 --no-same-owner

echo "Installed: node $("$PREFIX/bin/node" --version), npm $(PATH="$PREFIX/bin:$PATH" "$PREFIX/bin/npm" --version) in $PREFIX"
