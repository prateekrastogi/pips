// pips — CI pipeline (ADR-0007: native Jenkins, local, no GitHub Actions).
//
// Stages mirror the `make ci` ladder 1:1 and run INSIDE the project's own research image, so
// a green build certifies exactly the image arb-vm will run (§2.2). Merge to main only on
// green; the deploy rail ships main.
//
// NO BIND MOUNTS, deliberately. The controller is itself a container driving the HOST docker
// daemon through a mounted socket, so `-v "$PWD:/app"` would be resolved by the host against
// a path that only exists inside the controller — it mounts the wrong thing, or nothing, and
// the failure looks like a missing-file bug in the code under test. Instead the workspace is
// sent as the BUILD CONTEXT: `docker build` streams it over the socket, so the image contains
// the exact checkout and every stage runs against it with no path translation at all.
//
// The checkout must be FULL, not shallow — see ops/jenkins/casc.yaml. `make tdd-check`
// [G-TDD-01] walks branch history against origin/main, and a depth-1 clone has no history.

pipeline {
  agent any

  options {
    timestamps()
    disableConcurrentBuilds()
    buildDiscarder(logRotator(numToKeepStr: '50'))
    timeout(time: 45, unit: 'MINUTES')
  }

  environment {
    SHA   = "${env.GIT_COMMIT ?: 'dev'}"
    IMAGE = "pips/research:${env.GIT_COMMIT ?: 'dev'}"
  }

  stages {
    stage('Build image') {
      steps {
        // --target research: the same stage the developer and arb-vm build. One image,
        // one ladder, three places (§2.2).
        sh 'docker build -f docker/research.Dockerfile --target research -t "$IMAGE" .'
      }
    }

    stage('lint')         { steps { sh 'docker run --rm "$IMAGE" make lint' } }
    stage('typecheck')    { steps { sh 'docker run --rm "$IMAGE" make typecheck' } }

    stage('tdd-check') {
      // Constitution rule 16 / §7.1. This is a REPOSITORY check, not a code check: it needs
      // git history, which is why .git rides into the research image and why the checkout is
      // not shallow. If it ever prints SKIPPED here, the gate has gone vacuous — treat that
      // as red, not as a pass.
      steps { sh 'docker run --rm "$IMAGE" make tdd-check BASE=origin/main' }
    }

    stage('py tests')     { steps { sh 'docker run --rm "$IMAGE" make test' } }
    stage('rust tests')   { steps { sh 'docker run --rm "$IMAGE" make rust-test' } }
    stage('determinism')  { steps { sh 'docker run --rm "$IMAGE" make determinism' } }
    stage('ledger-check') { steps { sh 'docker run --rm "$IMAGE" make ledger-check' } }

    stage('Tag image') {
      when { expression { env.PIPS_REF == 'main' || env.BRANCH_NAME == 'main' } }
      steps {
        sh 'docker tag "$IMAGE" pips/research:main'
        echo "arb-vm deploy rail picks this SHA up on its next poll [G-DEPLOY-01]"
      }
    }
  }

  post {
    failure {
      echo 'CI red — do NOT merge. Never weaken a test, golden, gate or ledger row to go green (rule 10).'
    }
    always {
      sh 'docker image prune -f --filter "until=168h" || true'
    }
  }
}
