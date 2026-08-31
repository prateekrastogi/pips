// pips — local Jenkins declarative pipeline (ADR-0007: native Jenkins, no GitHub Actions).
// Stages mirror the `make ci` ladder 1:1 and run INSIDE the project's own research image,
// so a green build certifies exactly the image arb-vm will run (§2.2). Merge to main only
// on green; the deploy rail ships main.

pipeline {
  agent any

  options {
    timestamps()
    disableConcurrentBuilds()
    buildDiscarder(logRotator(numToKeepStr: '50'))
    timeout(time: 45, unit: 'MINUTES')
  }

  environment {
    PIPS_SHA   = "${env.GIT_COMMIT ?: 'dev'}"
    IMAGE      = "pips/research:${env.GIT_COMMIT ?: 'dev'}"
    DOCKER_BUILDKIT = '1'
  }

  stages {
    stage('Build image') {
      steps {
        sh 'docker build -f docker/research.Dockerfile --target research -t "$IMAGE" .'
      }
    }

    // Every stage below runs in the image built above. `-u 0` keeps the mounted
    // workspace writable for caches; nothing is written outside the workspace.
    stage('lint')         { steps { sh 'docker run --rm -v "$PWD:/app" -w /app "$IMAGE" make lint' } }
    stage('typecheck')    { steps { sh 'docker run --rm -v "$PWD:/app" -w /app "$IMAGE" make typecheck' } }
    stage('tdd-check')    { steps { sh 'docker run --rm -v "$PWD:/app" -w /app "$IMAGE" make tdd-check BASE=origin/main' } }
    stage('py tests')     { steps { sh 'docker run --rm -v "$PWD:/app" -w /app "$IMAGE" make test' } }
    stage('rust tests')   { steps { sh 'docker run --rm -v "$PWD:/app" -w /app "$IMAGE" make rust-test' } }
    stage('determinism')  { steps { sh 'docker run --rm -v "$PWD:/app" -w /app "$IMAGE" make determinism' } }
    stage('ledger-check') { steps { sh 'docker run --rm -v "$PWD:/app" -w /app "$IMAGE" make ledger-check' } }

    stage('Tag image') {
      when { branch 'main' }
      steps {
        sh 'docker tag "$IMAGE" "pips/research:main"'
        echo "arb-vm deploy rail picks this SHA up on its next poll (G-DEPLOY-01)"
      }
    }
  }

  post {
    failure { echo 'CI red — do NOT merge. Never weaken a test or gate to go green (rule 10).' }
    always  { sh 'docker image prune -f --filter "until=168h" || true' }
  }
}
