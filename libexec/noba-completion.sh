# Copyright (c) 2024-2026 Kevin Van Nieuwenhove. All rights reserved.
# NOBA Command Center — Licensed under Apache 2.0.
# noba-completion.sh – Fast Bash completion for Noba automation scripts
# Version: 2.2.1
# NOTE: Do NOT use set -e/-u here. This is sourced into the user's interactive shell.

_noba_completions() {
    local cur prev cmd scripts opts

    # Safely get current word, previous word, and base command
    cur="${COMP_WORDS[COMP_CWORD]}"
    prev="${COMP_WORDS[COMP_CWORD-1]}"
    cmd="${COMP_WORDS[0]}"

    # Full list of available scripts
    scripts="backup-notify.sh backup-to-nas.sh backup-verifier.sh checksum.sh cloud-backup.sh config-check.sh disk-sentinel.sh images-to-pdf.sh log-rotator.sh motd-generator.sh noba-cron-setup.sh noba-daily-digest.sh noba-dashboard.sh noba-tui.sh noba-update.sh noba-web.sh organize-downloads.sh service-watch.sh system-report.sh temperature-alert.sh undo-organizer.sh"

    # 1. Handle the "noba" wrapper CLI
    if [[ "$cmd" == "noba" ]]; then
        if [[ ${COMP_CWORD} -eq 1 ]]; then
            # Complete script names for the first argument
            # shellcheck disable=SC2207
            COMPREPLY=($(compgen -W "$scripts" -- "$cur"))
            return 0
        else
            # Shift the command context to the invoked script
            cmd="${COMP_WORDS[1]}"
        fi
    else
        # Strip path if executed via ./script.sh
        cmd="$(basename "$cmd")"
    fi

    # 2. Smart Directory & File Completion
    # If the previous word expects a path, trigger standard bash path completion
    case "$prev" in
        --source|--dest|-b|--backup-dir|-d|--download-dir|--dir)
            # Only complete directories
            # shellcheck disable=SC2207
            COMPREPLY=($(compgen -A directory -- "$cur"))
            return 0
            ;;
        -c|--config|-o|--output|--proton-path|--game-dir)
            # Complete files and directories
            # shellcheck disable=SC2207
            COMPREPLY=($(compgen -A file -- "$cur"))
            return 0
            ;;
    esac

    # 3. Argument Completion
    # Only show flag completions if the user has started typing a dash
    if [[ "$cur" == -* ]]; then
        opts=""
        case "$cmd" in
            backup-to-nas.sh)
                opts="--source --dest --email --dry-run --verbose --help --version"
                ;;
            backup-verifier.sh)
                opts="-b --backup-dir -n --num-files -c --compare-original --checksum-cmd --send-email -v --verbose -q --quiet -D --dry-run --help --version"
                ;;
            cloud-backup.sh)
                opts="-n --dry-run -r --remote -c --config --status --help --version"
                ;;
            disk-sentinel.sh)
                opts="-t --threshold -n --dry-run -v --verbose --help --version"
                ;;
            organize-downloads.sh)
                opts="--dry-run --help"
                ;;
            noba-daily-digest.sh)
                opts="-e --email -n --dry-run --help --version"
                ;;
            system-report.sh)
                opts="-o --output -d --dir -e --email -n --no-email --help --version"
                ;;
            checksum.sh)
                opts="-a --algo -v --verify -r --recursive -m --manifest -p --progress -o --output -c --copy -q --quiet --gui --follow-symlinks --no-hidden --manifest-name --help --version"
                ;;
            images-to-pdf.sh)
                opts="-o --output -s --paper-size -r --orientation -q --quality -m --metadata -p --progress -v --verbose --help --version"
                ;;
            undo-organizer.sh)
                opts="-d --dry-run -f --force --help"
                ;;
            noba-cron-setup.sh)
                opts="--help --list --remove"
                ;;
            *)
                # Generic fallback for scripts with minimal flags
                opts="--help --version"
                ;;
        esac

        # shellcheck disable=SC2207
        COMPREPLY=($(compgen -W "$opts" -- "$cur"))
        return 0
    fi
}

# -------------------------------------------------------------------
# Register the completion function
# -------------------------------------------------------------------
# Register for the master wrapper
complete -F _noba_completions noba

# Register dynamically for all individual scripts
complete -F _noba_completions backup-notify.sh backup-to-nas.sh backup-verifier.sh checksum.sh cloud-backup.sh config-check.sh disk-sentinel.sh images-to-pdf.sh log-rotator.sh motd-generator.sh noba-cron-setup.sh noba-daily-digest.sh noba-dashboard.sh noba-tui.sh noba-update.sh noba-web.sh organize-downloads.sh service-watch.sh system-report.sh temperature-alert.sh undo-organizer.sh
