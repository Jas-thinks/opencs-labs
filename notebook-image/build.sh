#!/usr/bin/env bash
#
# Build and verify the pinned OpenCS analytics notebook image.
#
#   notebook-image/build.sh            build, then run the smoke tests
#   notebook-image/build.sh --no-test  build only
#
# Steps
#   1. docker build -t opencs/analytics:1.0.0 .   (from this directory)
#   2. docker run ... opencs/analytics:1.0.0 python -m pytest /smoke -q
#
# The smoke tests are mounted read-only at /smoke instead of being baked into
# the image, so this directory is the single source of truth for them and the
# image stays free of test code and course data. The datasets library is mounted
# the same way a notebook pod sees it -- read-only at /opt/opencs/datasets --
# which also verifies that the served tree is readable by uid/gid 1000.
#
# Exits non-zero if the build fails or any smoke test fails. Re-run a single
# check with: notebook-image/build.sh --no-test then
#   docker run --rm -v "$PWD/smoke-tests:/smoke:ro" opencs/analytics:1.0.0 \
#       python -m pytest /smoke -q -k torch
set -Eeuo pipefail

IMAGE="${OPENCE_IMAGE:-opencs/analytics:1.0.0}"
HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "${HERE}/.." && pwd)"
SERVING_DIR="${OPENCE_DATASET_SERVING_DIR:-${HERE}/../datasets/serving}"
SMOKE_DIR="${HERE}/smoke-tests"
RUN_TESTS=1

for arg in "$@"; do
    case "${arg}" in
        --no-test) RUN_TESTS=0 ;;
        -h|--help)
            sed -n '2,22p' "${BASH_SOURCE[0]}" | sed 's/^# \{0,1\}//'
            exit 0
            ;;
        *)
            echo "build.sh: unknown argument '${arg}'" >&2
            exit 2
            ;;
    esac
done

log() { printf '\n==> %s\n' "$*"; }
die() { printf 'build.sh: %s\n' "$*" >&2; exit 1; }

command -v docker >/dev/null 2>&1 || die "docker is required but was not found on PATH"

log "Building ${IMAGE} from ${REPO_ROOT}"
# The build context is the repository root: the Dockerfile's extension stage
# copies jupyterlab-extension/ so the prebuilt extension can be baked in.
docker build --pull --tag "${IMAGE}" -f "${HERE}/Dockerfile" "${REPO_ROOT}"

if [[ "${RUN_TESTS}" -eq 0 ]]; then
    log "Skipping smoke tests (--no-test)"
    exit 0
fi

[[ -d "${SMOKE_DIR}" ]] || die "smoke tests not found at ${SMOKE_DIR}"
[[ -f "${SMOKE_DIR}/test_environment.py" ]] || die "${SMOKE_DIR}/test_environment.py is missing"

# The datasets mount is informational: the image must come up without it, but
# test_environment.py asserts the mount point exists, so mount the real tree
# when it is available and let the tests catch a bad path.
MOUNTS=(-v "${SMOKE_DIR}:/smoke:ro")
if [[ -d "${SERVING_DIR}" ]]; then
    MOUNTS+=(-v "${SERVING_DIR}:/opt/opencs/datasets:ro")
    log "Running smoke tests (datasets: ${SERVING_DIR})"
else
    log "Running smoke tests (no dataset tree at ${SERVING_DIR}; the empty mount point is tested)"
fi

# --network none: the image must be self-contained. --read-only with a tmpfs
# for /tmp mirrors the grading sandbox more closely than an ordinary container
# would, and catches anything that tries to write outside its home directory.
docker run --rm \
    --network none \
    --read-only \
    --tmpfs /tmp:rw,noexec,nosuid,size=256m \
    -e MPLBACKEND=Agg \
    -e PYTHONDONTWRITEBYTECODE=1 \
    "${MOUNTS[@]}" \
    "${IMAGE}" \
    python -m pytest /smoke -q

log "Image ${IMAGE} built and verified"
