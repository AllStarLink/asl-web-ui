#!/bin/bash
#
# Build asl-web-ui .deb packages locally in the builder image.
# Builds only: unlike dockerbuild.sh, nothing is uploaded or published.
#
#   builder/localbuild.sh [-o trixie] [-a amd64] [-e podman|docker]
#
# Packages are written to ../_debs (next to this repository).

set -euo pipefail

OS=trixie
ARCH=amd64
ENGINE=${CONTAINER_ENGINE:-podman}

while [[ $# -gt 0 ]]; do
	case $1 in
		-o) OS="$2"; shift 2 ;;
		-a) ARCH="$2"; shift 2 ;;
		-e) ENGINE="$2"; shift 2 ;;
		*) echo "Usage: $0 [-o os] [-a arch] [-e podman|docker]" >&2; exit 1 ;;
	esac
done

case $ARCH in
	amd64) IMG_ARCH=amd64 ;;
	arm64) IMG_ARCH=arm64v8 ;;
	*) echo "Unsupported architecture: $ARCH" >&2; exit 1 ;;
esac

DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO="$(dirname "$DIR")"
REPO_DIR="$(basename "$REPO")"
OUT="$(dirname "$REPO")/_debs"
TAG="asl-web-ui-builder.${OS}.${IMG_ARCH}"

mkdir -p "$OUT"

"$ENGINE" build -f "$DIR/Dockerfile" -t "$TAG" \
	--build-arg ARCH="$IMG_ARCH" \
	--build-arg OS="$OS" \
	--build-arg USER_ID="$(id -u)" \
	--build-arg GROUP_ID="$(id -g)" \
	"$DIR"

# Rootless podman maps container root to the invoking user, so files written
# to the mounted tree stay owned by you.
"$ENGINE" run --rm \
	-e REPO_DIR="$REPO_DIR" -e OUT_DIR=/out \
	-v "$REPO:/build/$REPO_DIR" \
	-v "$OUT:/out" \
	"$TAG"

echo "Packages in $OUT:"
ls -l "$OUT"
