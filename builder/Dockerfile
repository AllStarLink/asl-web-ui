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
	python3 python3-aiohttp python3-aiohttp-session python3-pytest python3-pytest-aiohttp python3-hypothesis \
	--no-install-recommends

# Node.js, used only to build the frontend: pinned and checksum-verified by
# install-node.sh, which developers run too.
COPY ./install-node.sh /usr/local/sbin/install-node.sh
RUN /usr/local/sbin/install-node.sh /opt/node
ENV PATH=/opt/node/bin:$PATH

COPY ./entrypoint.sh /entrypoint.sh
RUN chmod +x /entrypoint.sh

ENTRYPOINT ["/entrypoint.sh"]
