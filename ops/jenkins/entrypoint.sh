#!/usr/bin/env bash
# Give the jenkins user access to the MOUNTED host docker socket, then start the controller.
#
# WHY THIS IS RESOLVED AT RUNTIME. The socket's group id is a property of the HOST, not of
# this image: it differs between Docker Desktop, Colima and Linux. Baking a gid in works on
# the machine it was written on and fails closed everywhere else, with the least readable
# symptom available — every build failing at `docker: permission denied` long after the image
# looked fine.
set -euo pipefail

# The controller clones the pipeline from a READ-ONLY mount of the host repository. Git's
# ownership guard must be narrowed to that one path for the `jenkins` user, rather than
# disabled system-wide. `--replace-all` keeps exactly one entry on a reused home volume.
gosu jenkins git config --global --replace-all safe.directory /host-repo/.git

SOCK=/var/run/docker.sock
if [ -S "$SOCK" ]; then
  SOCK_GID=$(stat -c '%g' "$SOCK")
  if ! getent group "$SOCK_GID" >/dev/null 2>&1; then
    groupadd -g "$SOCK_GID" hostdocker
  fi
  SOCK_GROUP=$(getent group "$SOCK_GID" | cut -d: -f1)
  usermod -aG "$SOCK_GROUP" jenkins
  echo "pips-entrypoint: jenkins added to group $SOCK_GROUP (gid $SOCK_GID) for the host socket" >&2
else
  # NOT fatal, and loudly not fatal. A controller that boots without the socket still serves
  # its UI and reports why every build fails — far easier to diagnose than a container that
  # exits at startup.
  echo "pips-entrypoint: WARNING $SOCK is absent — builds needing Docker WILL fail; the UI still starts" >&2
fi

exec gosu jenkins /usr/local/bin/jenkins.sh "$@"
