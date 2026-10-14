#!/usr/bin/env bash
set -euo pipefail

readonly CERT_DIR="/certs"
readonly KEYGEN="/app/bazel-bin/tools/key_generator_tools"
readonly CERTGEN="/app/bazel-bin/tools/certificate_tools"
readonly FINANCE_EVENT_KEY="${CERT_DIR}/finance-event.key"

mkdir -p "${CERT_DIR}"

if [[ ! -f "${FINANCE_EVENT_KEY}" ]]; then
  head -c 32 /dev/urandom > "${FINANCE_EVENT_KEY}"
  chmod 600 "${FINANCE_EVENT_KEY}"
fi

if [[ -f "${CERT_DIR}/cert_5.cert" ]]; then
  exit 0
fi

"${KEYGEN}" "${CERT_DIR}/admin"

ips=("172.28.0.11" "172.28.0.12" "172.28.0.13" "172.28.0.14" "172.28.0.10")
for index in 1 2 3 4 5; do
  "${KEYGEN}" "${CERT_DIR}/node${index}"
  node_type="replica"
  if [[ "${index}" -eq 5 ]]; then
    node_type="client"
  fi
  "${CERTGEN}" \
    "${CERT_DIR}" \
    "${CERT_DIR}/admin.key.pri" \
    "${CERT_DIR}/admin.key.pub" \
    "${CERT_DIR}/node${index}.key.pub" \
    "${index}" \
    "${ips[$((index - 1))]}" \
    "$((10000 + index))" \
    "${node_type}"
done

chmod 600 "${CERT_DIR}"/*.key.pri
chmod 644 "${CERT_DIR}"/*.key.pub "${CERT_DIR}"/*.cert
