#!/bin/bash
# noba-tui.sh – Terminal UI for all scripts

DIALOG=${DIALOG=dialog}
tempfile=$(mktemp)

$DIALOG --clear --title "Nobara Automation" \
        --menu "Choose a script to run:" 20 50 10 \
        "Backup"      "Run backup-to-nas.sh" \
        "Verify"      "Run backup-verifier.sh" \
        "Checksum"    "Run checksum.sh" \
        "Disk"        "Run disk-sentinel.sh" \
        "Images2PDF"  "Run images-to-pdf.sh" \
        "Organize"    "Run organize-downloads.sh" \
        "Undo"        "Run undo-organizer.sh" \
        "MOTD"        "Show motd-generator.sh" \
        "Dashboard"   "Show noba-dashboard.sh" \
        "ConfigCheck" "Run config-check.sh" \
        "CronSetup"   "Run noba-cron-setup.sh" \
        "Quit"        "" 2> "$tempfile"

choice=$(<"$tempfile")
rm -f "$tempfile"

case $choice in
    Backup)      ~/.local/bin/backup-to-nas.sh ;;
    Verify)      ~/.local/bin/backup-verifier.sh ;;
    Checksum)    ~/.local/bin/checksum.sh ;;
    Disk)        ~/.local/bin/disk-sentinel.sh ;;
    Images2PDF)  ~/.local/bin/images-to-pdf.sh ;;
    Organize)    ~/.local/bin/organize-downloads.sh ;;
    Undo)        ~/.local/bin/undo-organizer.sh ;;
    MOTD)        ~/.local/bin/motd-generator.sh ;;
    Dashboard)   ~/.local/bin/noba-dashboard.sh ;;
    ConfigCheck) ~/.local/bin/config-check.sh ;;
    CronSetup)   ~/.local/bin/noba-cron-setup.sh ;;
    *)           exit ;;
esac
