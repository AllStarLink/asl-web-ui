ARG ARCH=amd64
ARG OS=trixie

FROM docker.io/$ARCH/debian:$OS

ARG ARCH
ARG OS
ARG USER_ID=1000
ARG GROUP_ID=1000

RUN addgroup --gid $GROUP_ID user; exit 0
RUN adduser --disabled-password --gecos '' --uid $USER_ID --gid $GROUP_ID user; exit 0

# Package build tools and the package's Build-Depends
RUN DEBIAN_FRONTEND=noninteractive apt-get update && apt-get -y install \
	apt-utils build-essential devscripts fakeroot debhelper git lsb-release \
	libterm-readline-gnu-perl libterm-readline-perl-perl libdistro-info-perl \
	gh ca-certificates curl wget xz-utils lintian pandoc \
	python3 python3-aiohttp python3-aiohttp-session python3-pytest python3-pytest-aiohttp \
	--no-install-recommends

# Node.js, pinned and checksum-verified, used only to build the frontend.
# Checksums from https://nodejs.org/dist/v$NODE_VERSION/SHASUMS256.txt
ARG NODE_VERSION=24.21.0
ARG NODE_SHA256_X64=fd8e59d5a511510f6a298afb548f18c7d2b1be404d8b4a27d94fbe49f56cb2d6
ARG NODE_SHA256_ARM64=6ad1325edbdb5649c379b75a237147a666c95d4f9ae8d340fef2d1575d289ad2
RUN set -eu; \
	case "$(dpkg --print-architecture)" in \
		amd64) node_arch=x64; node_sha=$NODE_SHA256_X64 ;; \
		arm64) node_arch=arm64; node_sha=$NODE_SHA256_ARM64 ;; \
		*) echo "No pinned Node.js build for $(dpkg --print-architecture)" >&2; exit 1 ;; \
	esac; \
	curl -fsSLo /tmp/node.tar.xz \
		"https://nodejs.org/dist/v$NODE_VERSION/node-v$NODE_VERSION-linux-$node_arch.tar.xz"; \
	echo "$node_sha  /tmp/node.tar.xz" | sha256sum -c -; \
	mkdir -p /opt/node; \
	tar -xJf /tmp/node.tar.xz -C /opt/node --strip-components=1 --no-same-owner; \
	rm /tmp/node.tar.xz
ENV PATH=/opt/node/bin:$PATH

COPY ./entrypoint.sh /entrypoint.sh
RUN chmod +x /entrypoint.sh

ENTRYPOINT ["/entrypoint.sh"]
