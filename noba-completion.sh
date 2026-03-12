#!/bin/bash
# noba-completion.sh – Bash completion for Nobara automation scripts

# shellcheck disable=SC2034  # words, cword, prev are used by completion machinery

_noba_completions() {
    local cur prev words cword
    _init_completion || return

    # Map script name to its options
    case "$prev" in
        backup-to-nas.sh)
            # shellcheck disable=SC2207
            COMPREPLY=($(compgen -W "--source --dest --email --dry-run --verbose --help --version" -- "$cur"))
            return
            ;;
        backup-verifier.sh)
            # shellcheck disable=SC2207
            COMPREPLY=($(compgen -W "-b --backup-dir -n --num-files -c --compare-original --checksum-cmd --temp-dir -v --verbose -q --quiet --dry-run --help --version" -- "$cur"))
            return
            ;;
        checksum.sh)
            # shellcheck disable=SC2207
            COMPREPLY=($(compgen -W "-a --algo -v --verify -r --recursive -m --manifest -p --progress -o --output -c --copy -q --quiet --gui --follow-symlinks --no-hidden --manifest-name --help --version" -- "$cur"))
            return
            ;;
        disk-sentinel.sh)
            # shellcheck disable=SC2207
            COMPREPLY=($(compgen -W "-t --threshold -n --dry-run -v --verbose --help --version" -- "$cur"))
            return
            ;;
        images-to-pdf.sh)
            # shellcheck disable=SC2207
            COMPREPLY=($(compgen -W "-o --output -s --paper-size -r --orientation -q --quality -m --metadata -p --progress -v --verbose --help --version" -- "$cur"))
            return
            ;;
        organize-downloads.sh)
            # shellcheck disable=SC2207
            COMPREPLY=($(compgen -W "-c --config -d --dry-run -v --verbose -q --quiet --dated --help --version" -- "$cur"))
            return
            ;;
        undo-organizer.sh)
            # shellcheck disable=SC2207
            COMPREPLY=($(compgen -W "-d --dry-run -f --force --help" -- "$cur"))
            return
            ;;
        run-hogwarts-trainer.sh)
            # shellcheck disable=SC2207
            COMPREPLY=($(compgen -W "-g --game-dir -t --trainer -p --proton-path -l --list-proton -q --quiet --help --version" -- "$cur"))
            return
            ;;
        motd-generator.sh)
            # shellcheck disable=SC2207
            COMPREPLY=($(compgen -W "--help --version" -- "$cur"))
            return
            ;;
        noba-dashboard.sh)
            # shellcheck disable=SC2207
            COMPREPLY=($(compgen -W "--help" -- "$cur"))
            return
            ;;
        backup-notify.sh)
            # shellcheck disable=SC2207
            COMPREPLY=($(compgen -W "--help" -- "$cur"))
            return
            ;;
        config-check.sh)
            # shellcheck disable=SC2207
            COMPREPLY=($(compgen -W "backup-to-nas.sh backup-verifier.sh checksum.sh disk-sentinel.sh images-to-pdf.sh organize-downloads.sh undo-organizer.sh run-hogwarts-trainer.sh motd-generator.sh noba-dashboard.sh backup-notify.sh config-check.sh noba-cron-setup.sh cloud-backup.sh system-report.sh log-rotator.sh temperature-alert.sh service-watch.sh noba-tui.sh noba-web.sh noba-update.sh noba-daily-digest.sh" -- "$cur"))
            return
            ;;
        noba-cron-setup.sh)
            # shellcheck disable=SC2207
            COMPREPLY=($(compgen -W "--help --list --remove" -- "$cur"))
            return
            ;;
    esac

    # If we're at the first argument, suggest script names
    if [[ $cword -eq 1 ]]; then
        # shellcheck disable=SC2207
        COMPREPLY=($(compgen -W "backup-to-nas.sh backup-verifier.sh checksum.sh disk-sentinel.sh images-to-pdf.sh organize-downloads.sh undo-organizer.sh run-hogwarts-trainer.sh motd-generator.sh noba-dashboard.sh backup-notify.sh config-check.sh noba-cron-setup.sh" -- "$cur"))
    fi
}

# Assign completion to all scripts
complete -F _noba_completions backup-to-nas.sh backup-verifier.sh checksum.sh disk-sentinel.sh images-to-pdf.sh organize-downloads.sh undo-organizer.sh run-hogwarts-trainer.sh motd-generator.sh noba-dashboard.sh backup-notify.sh config-check.sh noba-cron-setup.sh
