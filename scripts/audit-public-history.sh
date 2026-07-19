#!/usr/bin/env bash
set -euo pipefail

repo_root="$(git rev-parse --show-toplevel 2>/dev/null || true)"
if [[ -z "${repo_root}" ]]; then
  echo "Run this script from inside a Git repository." >&2
  exit 2
fi

cd "${repo_root}"

git_dir="$(git rev-parse --git-dir)"
if [[ "${git_dir}" != /* ]]; then
  git_dir="${repo_root}/${git_dir}"
fi

output_dir="${1:-${git_dir}/history-audit}"
mkdir -p "${output_dir}"
output_dir="$(cd "${output_dir}" && pwd)"
report="${output_dir}/history-audit-report.txt"
objects_file="${output_dir}/all-reachable-objects.txt"
paths_file="${output_dir}/all-historical-paths.txt"
image_file="${output_dir}/historical-images.txt"
large_file="${output_dir}/large-blobs.txt"
finding_file="${output_dir}/content-findings.txt"
tmp_dir="$(mktemp -d)"

cleanup() {
  rm -rf "${tmp_dir}"
}
trap cleanup EXIT

exec > >(tee "${report}") 2>&1

echo "Public Git history audit"
echo "========================"
echo "Repository: ${repo_root}"
echo "Generated:  $(date -u '+%Y-%m-%dT%H:%M:%SZ')"
echo

echo "Scope"
echo "-----"
echo "- all objects reachable from local branches, remote-tracking branches and tags"
echo "- historical path names, image assets, large blobs and selected secret markers"
echo "- current Git references and tags"
echo
echo "This is a review aid, not proof that no secret or third-party asset exists."
echo "Public GitHub release assets must also be downloaded and inspected separately."
echo

echo "References"
echo "----------"
git for-each-ref --format='%(refname) %(objectname)' refs/heads refs/remotes refs/tags | sort
echo

echo "Tags"
echo "----"
if git tag --list | grep -q .; then
  git tag --list --format='%(refname:short) %(objectname) %(creatordate:iso8601)' | sort
else
  echo "(none)"
fi
echo

git rev-list --objects --all > "${objects_file}"
cut -d' ' -f2- "${objects_file}" | sed '/^$/d' | sort -u > "${paths_file}"

echo "Historical path review"
echo "----------------------"
suspicious_path_regex='(^|/)(SANlightMesh[^/]*\.json|[^/]*\.(apk|aab|ipa|bin|hex|uf2|dfu|pem|key|p12|pfx|keystore|jks)|private/|\.state/|secrets?/|runtime/|var/lib/bluetooth/mesh/)'
if grep -Ein "${suspicious_path_regex}" "${paths_file}"; then
  echo
  echo "Review every path above. A filename match is not automatically a leak."
else
  echo "No path matched the high-risk filename patterns."
fi
echo

grep -Ei '\.(png|jpe?g|webp|gif|svg|bmp|tiff?)$' "${paths_file}" | sort -u > "${image_file}" || true
echo "Historical image inventory"
echo "--------------------------"
if [[ -s "${image_file}" ]]; then
  cat "${image_file}"
else
  echo "(none)"
fi
echo

: > "${large_file}"
: > "${finding_file}"

declare -A seen_blobs=()
blob_count=0
text_blob_count=0
skipped_large_count=0
finding_count=0

while IFS=' ' read -r oid path; do
  [[ -n "${oid}" ]] || continue
  if [[ -n "${seen_blobs[${oid}]:-}" ]]; then
    continue
  fi

  type="$(git cat-file -t "${oid}" 2>/dev/null || true)"
  [[ "${type}" == "blob" ]] || continue
  seen_blobs["${oid}"]=1
  blob_count=$((blob_count + 1))

  size="$(git cat-file -s "${oid}")"
  display_path="${path:-<path unavailable>}"

  if (( size >= 1048576 )); then
    printf '%12d  %s  %s\n' "${size}" "${oid}" "${display_path}" >> "${large_file}"
  fi

  # Content scanning is capped to keep the audit fast and avoid processing
  # archives, images or generated binaries as text.
  if (( size > 2097152 )); then
    skipped_large_count=$((skipped_large_count + 1))
    continue
  fi

  blob_tmp="${tmp_dir}/${oid}"
  git cat-file blob "${oid}" > "${blob_tmp}"

  if ! grep -Iq . "${blob_tmp}"; then
    continue
  fi
  text_blob_count=$((text_blob_count + 1))

  matches="$(
    {
      grep -Ein \
        -e '-----BEGIN (RSA |EC |OPENSSH |DSA )?PRIVATE KEY-----' \
        -e '(netkey|appkey|devicekey|identitytoken|mqtt[_ -]?password|password|passwd|secret|access[_ -]?token)[^[:alnum:]]{0,24}[:=][[:space:]]*["'\'']?[0-9A-Za-z/+_.=-]{16,}' \
        -e '"(netKey|appKey|deviceKey|identityToken)"[[:space:]]*:[[:space:]]*"[0-9A-Fa-f]{16,}"' \
        "${blob_tmp}" || true
    } | head -n 20
  )"

  if [[ -n "${matches}" ]]; then
    finding_count=$((finding_count + 1))
    {
      echo "Blob: ${oid}"
      echo "Path: ${display_path}"
      echo "${matches}"
      echo
    } >> "${finding_file}"
  fi
done < "${objects_file}"

sort -nr "${large_file}" -o "${large_file}"

echo "Large historical blobs (>= 1 MiB)"
echo "--------------------------------"
if [[ -s "${large_file}" ]]; then
  cat "${large_file}"
else
  echo "(none)"
fi
echo

echo "Content findings"
echo "----------------"
if [[ -s "${finding_file}" ]]; then
  cat "${finding_file}"
  echo "Every finding requires manual review. Documentation examples can be false positives."
else
  echo "No selected private-key or labelled-secret pattern was found in scanned text blobs."
fi
echo

echo "Summary"
echo "-------"
echo "Unique reachable blobs:       ${blob_count}"
echo "Text blobs scanned:           ${text_blob_count}"
echo "Blobs > 2 MiB not text-scanned: ${skipped_large_count}"
echo "Blobs with content findings:  ${finding_count}"
echo "Historical image list:        ${image_file}"
echo "Large-blob list:               ${large_file}"
echo "Content finding list:         ${finding_file}"
echo

echo "Next checks"
echo "-----------"
echo "1. Review every content finding against the actual file and commit."
echo "2. Review every historical image for screenshots, logos and copied product photos."
echo "3. Inspect GitHub release assets separately; they are not Git objects."
echo "4. Rotate any real exposed credential before rewriting or deleting history."
echo "5. Prefer a targeted history rewrite over squashing unrelated development history."
