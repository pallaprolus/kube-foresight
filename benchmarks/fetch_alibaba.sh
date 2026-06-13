#!/usr/bin/env bash
#
# Fetch the three Alibaba cluster-trace-v2018 files the backtest harness needs:
#   machine_meta.csv, container_meta.csv, container_usage.csv
# The other three trace files (machine_usage, batch_task, batch_instance) are
# not used and are skipped, saving ~21 GB.
#
# By default the 28 GB container_usage archive is *sampled* — streamed, decom-
# pressed, and truncated to the first N rows (no full extract to disk). Pass
# --full to download and extract the entire usage series instead.
#
# Usage:
#   benchmarks/fetch_alibaba.sh [TARGET_DIR] [USAGE_ROW_LIMIT]
#   benchmarks/fetch_alibaba.sh --full [TARGET_DIR]
#
# Examples:
#   benchmarks/fetch_alibaba.sh                      # ./alibaba-2018, 40M rows
#   benchmarks/fetch_alibaba.sh ~/traces 80000000    # custom dir + row cap
#   benchmarks/fetch_alibaba.sh --full ~/traces      # everything
#
# Official source (a short survey is the "blessed" route, but these OSS URLs are
# exactly what Alibaba's fetchData.sh uses):
#   https://github.com/alibaba/clusterdata/tree/master/cluster-trace-v2018
set -euo pipefail

BASE="https://aliopentrace.oss-cn-beijing.aliyuncs.com/v2018Traces"

FULL=0
if [[ "${1:-}" == "--full" ]]; then
  FULL=1
  shift
fi
DIR="${1:-alibaba-2018}"
LIMIT="${2:-40000000}"

mkdir -p "$DIR"

# Stream a URL to stdout using whichever fetcher is available.
stream() {
  if command -v curl >/dev/null 2>&1; then
    curl -fsSL "$1"
  elif command -v wget >/dev/null 2>&1; then
    wget -qO- "$1"
  else
    echo "ERROR: need curl or wget on PATH" >&2
    exit 1
  fi
}

# Each archive holds a single CSV; -xzOf - extracts it to stdout (portable
# across GNU tar and macOS bsdtar).
echo "→ machine_meta.csv (92 KB archive)"
stream "$BASE/machine_meta.tar.gz" | tar -xzOf - > "$DIR/machine_meta.csv"

echo "→ container_meta.csv (2.4 MB archive)"
stream "$BASE/container_meta.tar.gz" | tar -xzOf - > "$DIR/container_meta.csv"

if [[ "$FULL" == "1" ]]; then
  echo "→ container_usage.csv (FULL — ~28 GB compressed, ~100 GB+ extracted)"
  stream "$BASE/container_usage.tar.gz" | tar -xzOf - > "$DIR/container_usage.csv"
else
  echo "→ container_usage.csv (sampled — first $LIMIT rows)"
  # `head` closes the pipe early, which makes curl/tar exit non-zero (SIGPIPE).
  # That is expected here, so suspend pipefail and validate via the row count.
  set +o pipefail
  stream "$BASE/container_usage.tar.gz" | tar -xzOf - | head -n "$LIMIT" \
    > "$DIR/container_usage.csv"
  set -o pipefail
fi

rows=$(wc -l < "$DIR/container_usage.csv" | tr -d ' ')
if [[ "$rows" -le 0 ]]; then
  echo "ERROR: $DIR/container_usage.csv is empty — check the URL / network" >&2
  exit 1
fi

echo
echo "Done — files in $DIR:"
ls -la "$DIR"/machine_meta.csv "$DIR"/container_meta.csv "$DIR"/container_usage.csv
echo "container_usage.csv: $rows rows"
echo
echo "Run the backtest:"
echo "  python -m benchmarks.backtest --source alibaba --trace-dir $DIR --max-app-groups 300"
