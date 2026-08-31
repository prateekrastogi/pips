# Jenkins controller for pips CI (ADR-0007: native Jenkins, local, no GitHub Actions).
#
# pips runs its OWN controller rather than borrowing the one already on this machine. That
# instance belongs to another project and its API needs a credential we do not have and
# should not ask for; standing up a tenancy defined entirely by committed config is both
# cheaper and more honest than sharing someone else's mutable controller. Nothing here is
# configured by clicking — casc.yaml is the controller.
#
# Pattern (and most of the hard-won comments) ported from ../keeper/deploy/jenkins, which is
# a working controller on this same host. Cited rather than reinvented.
#
# PINNED, not `lts`. A floating tag silently changes the controller under a green history.
# 2.541.3 is the pin proven to resolve this plugin set on this machine.
FROM jenkins/jenkins:2.541.3-lts-jdk17

USER root

# The Docker CLI only — NOT a daemon. Builds run as sibling containers on the host socket
# mounted by compose; an engine in here would nest a second daemon and duplicate every layer.
#
# NOT `apt-get install docker.io`: on arm64 Debian that package ships the DAEMON and no CLI,
# so `dpkg -l` reports it installed while `command -v docker` says NOTFOUND — which reads
# like a PATH problem and is not one. The official static tarball gives the CLI alone.
RUN apt-get update \
 && apt-get install -y --no-install-recommends git openssh-client jq gosu curl ca-certificates make \
 && rm -rf /var/lib/apt/lists/*

ARG DOCKER_CLI_VERSION=29.7.2
RUN set -eux; \
    arch="$(uname -m)"; \
    curl -fsSL "https://download.docker.com/linux/static/stable/${arch}/docker-${DOCKER_CLI_VERSION}.tgz" -o /tmp/d.tgz; \
    tar -xzf /tmp/d.tgz -C /tmp docker/docker; \
    install -m 0755 /tmp/docker/docker /usr/local/bin/docker; \
    rm -rf /tmp/d.tgz /tmp/docker; \
    docker --version

COPY entrypoint.sh /usr/local/bin/pips-entrypoint.sh
RUN chmod +x /usr/local/bin/pips-entrypoint.sh

COPY plugins.txt /usr/share/jenkins/ref/plugins.txt
RUN jenkins-plugin-cli --plugin-file /usr/share/jenkins/ref/plugins.txt --latest false

# COMMITTED JCasC BAKED IN, OUTSIDE the named home volume. /var/jenkins_home is a volume, so
# an image copy landing there is shadowed by the volume's first-run contents and every later
# edit is silently ignored — the controller keeps booting the ORIGINAL config while the repo
# shows the corrected one. /var/jenkins_conf is not a volume, so it survives.
COPY casc.yaml /var/jenkins_conf/casc.yaml

ENTRYPOINT ["/usr/local/bin/pips-entrypoint.sh"]
