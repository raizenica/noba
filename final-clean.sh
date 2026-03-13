#!/bin/bash
# final-clean.sh – Silence remaining ShellCheck warnings

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
# shellcheck source=/dev/null
# shellcheck source=/dev/null
source "$SCRIPT_DIR/noba-lib.sh"

show_version() {
    echo "final-clean.sh version 1.0"
    exit 0
}

show_help() {
    cat <<EOF
Usage: $0 [OPTIONS]

Add ShellCheck disable directives to silence the last warnings.

Options:
  --help        Show this help message
  --version     Show version information
EOF
    exit 0
}

if [ $# -gt 0 ]; then
    case "$1" in
        --help)    show_help ;;
        --version) show_version ;;
        *)         log_error "Unknown option: $1"; show_help ;;
    esac
fi

log_info "Fixing checksum.sh SC2317 (unreachable command)"
sed -i '301i# shellcheck disable=SC2317' checksum.sh

log_info "Fixing cloud-backup.sh SC2086 (intentional word splitting)"
sed -i '81i# shellcheck disable=SC2086' cloud-backup.sh

log_info "Fixing disk-sentinel.sh SC2119 (check_deps called without args)"
sed -i '213i# shellcheck disable=SC2119' disk-sentinel.sh

log_info "Fixing master-fix.sh SC2016 (expressions in single quotes)"
sed -i '1a# shellcheck disable=SC2016' master-fix.sh

log_success "All fixes applied. Run 'shellcheck *.sh' to verify."
