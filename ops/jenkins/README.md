# ops/jenkins — the pips CI controller

CI is **native Jenkins, running locally** (ADR-0007). This directory *is* the controller:
`casc.yaml` defines it as code, so a rebuild on any machine reproduces it exactly. Nothing
about it is configured by clicking.

## Why pips runs its own controller

Another project's controller already runs on this host, on `127.0.0.1:8080`. Reaching it
needs a credential we do not have, and credentials are human-only under the constitution.
Standing up a tenancy defined by committed config is cheaper than asking for one and more
honest than sharing a mutable controller between projects — a config change made for one
would silently change CI for the other. pips binds `127.0.0.1:8081` and touches nothing else.

## Use

```bash
make jenkins-up                      # build + start (loopback :8081, user `pips`)
make jenkins-build REF=m/0-scaffold  # trigger a build of a ref, wait for the verdict
make jenkins-logs                    # tail controller logs
make jenkins-down                    # stop, keeping the home volume
```

Override the placeholder login before first start:
`export PIPS_JENKINS_PASSWORD=... && make jenkins-up`. No real credential belongs in git.

## The three things that are load-bearing

1. **`casc.yaml` is bind-mounted from this directory and also baked at `/var/jenkins_conf/`,
   never into `/var/jenkins_home/`.** That path is a named volume: an image copy landing there
   is shadowed by the volume's first-run contents, so every later edit is silently ignored and
   the controller keeps booting the original config while the repo shows the corrected one.

2. **The checkout is NOT shallow.** `make tdd-check` `[G-TDD-01]` walks branch history against
   `origin/main` to prove the branch was written test-first. Under a depth-1 clone there is no
   history to walk, so the gate either goes vacuous or fails for the wrong reason. The
   neighbouring `keeper` project hit exactly this class of failure (its ledger §17.2253).

3. **The pipeline uses no bind mounts.** The controller is a container driving the *host*
   daemon through a mounted socket, so `-v "$PWD:/app"` in a pipeline step is resolved by the
   host against a path that exists only inside the controller. The workspace is sent as the
   docker **build context** instead, and every stage runs against the resulting image.

## What this controller deliberately does not have

- **No polling, timer, or push hook.** A build exists because `trigger.sh` asked for one on a
  named ref, so the build history reads as a record of deliberate merge decisions.
- **No SSH identity.** M3.5 binds an arb-vm key as a Jenkins credential when the deploy rail
  lands `[G-DEPLOY-01]`. Until then the controller holds no key and reaches nothing remote.
- **No access to the live path.** It builds and tests. It cannot set `PIPS_LIVE`, it never
  sees broker or Breeze credentials, and it deploys nothing (constitution rule 8).

## Provenance

The controller pattern — JCasC layout, the docker-CLI-not-daemon install, the runtime socket
gid resolution in `entrypoint.sh`, and the `/var/jenkins_conf` placement — is ported from
`../keeper/deploy/jenkins`, a working controller on this same host. Its comments record
failures already paid for once; re-deriving them here would have cost the same debugging
twice. Adapted for pips: own port and volume names, no foundry toolchain, no SSH mount, full
(not shallow) clone, and a parameterised ref.
