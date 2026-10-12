#!/usr/bin/env bash
set -euo pipefail

readonly RESILIENTDB_COMMIT="4de5cb43686276ace4307f44839a1de920ab524a"
readonly SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
readonly REPOSITORY_ROOT="$(cd "${SCRIPT_DIR}/../.." && pwd)"
readonly PATCH_FILE="${REPOSITORY_ROOT}/patches/resilientdb/0001-milestone0-persistent-kv-and-contract.patch"
readonly DOCKERFILE="${REPOSITORY_ROOT}/infra/milestone0/Dockerfile.resilientdb"

if [[ $# -ne 1 ]]; then
  echo "usage: $0 /path/to/pinned/resilientdb-checkout" >&2
  exit 64
fi

readonly UPSTREAM_CHECKOUT="$1"
readonly DOCKER_BIN="${RESFINANCE_DOCKER_BIN:-docker}"
readonly DOCKER_BIN_DIRECTORY="$(cd "$(dirname "${DOCKER_BIN}")" && pwd)"
readonly DOCKER_ENDPOINT="${RESFINANCE_DOCKER_HOST:-}"
readonly FINAL_IMAGE="${RESFINANCE_IMAGE:-resfinance/resilientdb:${RESILIENTDB_COMMIT:0:7}-m0}"
readonly BASE_IMAGE="resfinance/resilientdb-base:${RESILIENTDB_COMMIT:0:7}"
readonly ACTUAL_COMMIT="$(git -C "${UPSTREAM_CHECKOUT}" rev-parse HEAD)"

if [[ "${ACTUAL_COMMIT}" != "${RESILIENTDB_COMMIT}" ]]; then
  echo "upstream commit mismatch: expected ${RESILIENTDB_COMMIT}, got ${ACTUAL_COMMIT}" >&2
  exit 1
fi

readonly PATCH_SHA256="$(shasum -a 256 "${PATCH_FILE}" | awk '{print $1}')"
readonly BUILD_ROOT="$(mktemp -d "${TMPDIR:-/tmp}/resfinance-resilientdb-build.XXXXXX")"

DOCKER_COMMAND=("${DOCKER_BIN}")
if [[ -x "${DOCKER_BIN_DIRECTORY}/docker-credential-desktop" ]]; then
  export PATH="${DOCKER_BIN_DIRECTORY}:${PATH}"
fi
if [[ -n "${DOCKER_ENDPOINT}" ]]; then
  DOCKER_COMMAND+=(--host "${DOCKER_ENDPOINT}")
fi

cleanup() {
  git -C "${UPSTREAM_CHECKOUT}" worktree remove --force "${BUILD_ROOT}" >/dev/null 2>&1 || true
}
trap cleanup EXIT

git -C "${UPSTREAM_CHECKOUT}" worktree add --detach "${BUILD_ROOT}" "${RESILIENTDB_COMMIT}"
git -C "${BUILD_ROOT}" apply --check "${PATCH_FILE}"
git -C "${BUILD_ROOT}" apply "${PATCH_FILE}"
git -C "${BUILD_ROOT}" diff --check

"${DOCKER_COMMAND[@]}" build \
  --platform linux/arm64 \
  --label "org.opencontainers.image.source=https://github.com/apache/incubator-resilientdb" \
  --label "org.opencontainers.image.revision=${RESILIENTDB_COMMIT}" \
  --tag "${BASE_IMAGE}" \
  --file "${BUILD_ROOT}/Docker/Dockerfile_mac" \
  "${BUILD_ROOT}"

"${DOCKER_COMMAND[@]}" build \
  --platform linux/arm64 \
  --build-arg "BASE_IMAGE=${BASE_IMAGE}" \
  --build-arg "RESILIENTDB_COMMIT=${RESILIENTDB_COMMIT}" \
  --build-arg "RESFINANCE_PATCH_SHA256=${PATCH_SHA256}" \
  --tag "${FINAL_IMAGE}" \
  --file "${DOCKERFILE}" \
  "${BUILD_ROOT}"

"${DOCKER_COMMAND[@]}" image inspect "${FINAL_IMAGE}" \
  --format '{{json .Config.Labels}} {{json .RepoDigests}} {{.Id}}'
