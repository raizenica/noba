# Nobara Automation Suite

A collection of Bash scripts to automate common tasks on Nobara Linux (and other Fedora‑based systems).  
All scripts share a common library (`noba-lib.sh`) and a central YAML configuration file.

## ✨ Features

- **Backup to NAS** with retention, space check, and email reports.
- **Disk space monitoring** with automatic cleanup and alerts.
- **Download organizer** – automatically sort files in `~/Downloads` into folders.
- **Checksum generator/verifier** with multiple algorithms and manifests.
- **Image to PDF converter** (CLI and GUI).
- **System health report** (HTML + email).
- **CPU temperature alerts**.
- **Service watchdog** – monitor and restart failed services.
- **Cloud backup** via `rclone`.
- **Unified web dashboard** showing system status, backups, disk usage, network traffic, GPU temperature, Docker containers, and custom services.
- **Central CLI** (`noba`) for easy access to all scripts.
- **Systemd timers** for automation (daily backups, hourly organization, etc.).

## 📦 Installation

### Quick Install

```bash
git clone https://github.com/raizenica/noba.git ~/noba
cd ~/noba
chmod +x *.sh
./install.sh   # optional installer (see below)

Manual Steps

    Clone the repository into a directory in your PATH (e.g., ~/bin):
    bash

    git clone https://github.com/raizenica/noba.git ~/.local/bin
    cd ~/.local/bin
    chmod +x *.sh

    Install required dependencies (example for Fedora):
    bash

    sudo dnf install rsync msmtp ImageMagick yq jq dialog kdialog lm_sensors lsof docker

    (Optional) Create a configuration file – see Configuration.

Installer Script

An install.sh script is provided to automate copying scripts, setting up configuration, and enabling systemd user timers. Run it from the repository root:
bash

./install.sh

See Installer Details for more information.
⚙️ Configuration

The suite uses a single YAML configuration file located at ~/.config/noba/config.yaml.
A minimal example with all available options:
yaml

# Nobara unified configuration
email: "your@email.com"

backup:
  dest: "/mnt/vnnas/backups/raizen"
  sources:
    - "/home/raizen/Documents"
    - "/home/raizen/Pictures"
    - "/home/raizen/.config"
  retention_days: 7
  space_margin_percent: 10
  min_free_space_gb: 5

disk:
  threshold: 85
  targets:
    - "/"
    - "/home"
  cleanup_enabled: true
  ignore_fs: "^(proc|sysfs|tmpfs|devpts|securityfs|fusectl|debugfs|pstore|hugetlbfs|mqueue|configfs|devtmpfs|binfmt_misc)$"

downloads:
  dir: "/home/raizen/Downloads"
  min_age_minutes: 5
  dated_subfolders: true
  config: "~/.config/download-organizer/config.yaml"

checksum:
  default_algo: "sha256"

images2pdf:
  default_paper_size: "A4"
  default_orientation: "portrait"
  default_quality: 92

logs:
  dir: "/home/raizen/.local/share/noba"

log_rotation:
  days: 30

update:
  repo_dir: "/home/raizen/.local/bin"
  remote: "origin"
  branch: "main"

motd:
  quote_file: "~/.config/quotes.txt"
  show_updates: true
  show_backup: true

services:
  monitor:
    - sshd
    - docker
    - NetworkManager
  notify: true

cron:
  scripts:
    - backup-to-nas.sh
    - disk-sentinel.sh
    - organize-downloads.sh

cloud:
  remote: "mycloud:backups/raizen"
  rclone_opts: "-v --checksum --progress"

web:
  start_port: 8080
  max_port: 8090
  service_list:
    - backup-to-nas.service
    - organize-downloads.service
    - noba-web.service
    - syncthing.service

📜 Scripts Overview
Script	Description	YAML Keys
noba	Central CLI	–
backup-to-nas.sh	Backup to NAS with retention and email	backup.*
disk-sentinel.sh	Disk space monitor with cleanup	disk.*
organize-downloads.sh	Sort Downloads into folders	downloads.*
undo-organizer.sh	Revert last download organization	–
checksum.sh	Generate/verify checksums	checksum.*
images-to-pdf.sh	Convert images to PDF (CLI/GUI)	images2pdf.*
system-report.sh	HTML system report + email	logs.dir, email
motd-generator.sh	Message of the day with system status	motd.*
service-watch.sh	Monitor and restart systemd services	services.monitor
cloud-backup.sh	Sync backups to cloud (rclone)	cloud.*
temperature-alert.sh	Desktop alerts on CPU overheat	disk.threshold
log-rotator.sh	Compress old logs	log_rotation.days
noba-update.sh	Git pull latest scripts	update.*
noba-dashboard.sh	Terminal dashboard	–
noba-web.sh	Web dashboard (auto‑refresh)	web.*
noba-cron-setup.sh	Interactive cron job setup	cron.scripts
config-check.sh	Validate dependencies and config	–
test-all.sh	Run basic tests on all scripts	–
🚀 Usage Examples

Backup with dry‑run:
bash

backup-to-nas.sh --dry-run

Check disk space with custom threshold:
bash

disk-sentinel.sh --threshold 90

Organise downloads (simulate):
bash

organize-downloads.sh --dry-run

Generate system report:
bash

system-report.sh

Web dashboard:
bash

noba-web.sh

Then open http://localhost:8080.

Central CLI:
bash

noba run backup --dry-run
noba doctor
noba config --edit

🤖 Automation (systemd timers)

The suite includes systemd user timer files for common tasks. Enable them with:
bash

systemctl --user enable --now disk-sentinel.timer
systemctl --user enable --now system-report.timer
systemctl --user enable --now cloud-backup.timer
systemctl --user enable --now log-rotator.timer
systemctl --user enable --now service-watch.timer
systemctl --user enable --now temperature-alert.timer

Check status:
bash

systemctl --user list-timers

If you prefer cron, use noba-cron-setup.sh to interactively add jobs.
🌐 Web Dashboard

The web dashboard (noba-web.sh) provides a real‑time overview of your system:

    System health (uptime, load, memory, CPU temp)

    Backup status and logs

    Updates (DNF, Flatpak)

    Disk usage with colour‑coded bars

    Download organizer stats

    Disk sentinel alerts

    Network: default IP and interface traffic

    User services status (customisable)

    GPU temperature (NVIDIA/AMD)

    Docker containers (running)

It auto‑refreshes every minute and runs as a background process. To run it permanently at boot, enable the provided systemd user service:
bash

systemctl --user enable --now noba-web.service

The service will restart automatically if it crashes.
🛠️ Installer Details

The install.sh script performs the following actions:

    Copies all .sh scripts to ~/.local/bin (or a custom directory).

    Creates a default ~/.config/noba/config.yaml if it doesn't exist.

    Copies systemd user timer/service files to ~/.config/systemd/user/ (if present).

    Reloads systemd user daemon.

    Gives instructions for enabling timers.

Run it with -h for options.
📄 License

This project is licensed under the MIT License. See the LICENSE file for details.
text


---

## 📦 `install.sh` – Installer Script

Create `install.sh` with the following content. Make it executable (`chmod +x install.sh`).

```bash
#!/bin/bash
# install.sh – Install Nobara Automation Suite

set -euo pipefail

INSTALL_DIR="${INSTALL_DIR:-$HOME/.local/bin}"
CONFIG_DIR="${CONFIG_DIR:-$HOME/.config/noba}"
SYSTEMD_USER_DIR="${SYSTEMD_USER_DIR:-$HOME/.config/systemd/user}"
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
DRY_RUN=false

show_help() {
    cat <<EOF
Usage: $0 [OPTIONS]

Install Nobara Automation Suite.

Options:
  -d, --dir DIR       Installation directory (default: $INSTALL_DIR)
  -c, --config DIR    Configuration directory (default: $CONFIG_DIR)
  -s, --systemd DIR   Systemd user unit directory (default: $SYSTEMD_USER_DIR)
  -n, --dry-run       Show what would be done without copying
  --help              Show this help
EOF
    exit 0
}

while [[ $# -gt 0 ]]; do
    case $1 in
        -d|--dir)       INSTALL_DIR="$2"; shift 2 ;;
        -c|--config)    CONFIG_DIR="$2"; shift 2 ;;
        -s|--systemd)   SYSTEMD_USER_DIR="$2"; shift 2 ;;
        -n|--dry-run)   DRY_RUN=true; shift ;;
        --help)         show_help ;;
        *)              echo "Unknown option: $1" >&2; exit 1 ;;
    esac
done

echo "Installing Nobara Automation Suite to $INSTALL_DIR"
echo "Configuration directory: $CONFIG_DIR"
echo "Systemd user units: $SYSTEMD_USER_DIR"

if [ "$DRY_RUN" = true ]; then
    echo "DRY RUN – no files will be copied."
fi

# Create directories
if [ "$DRY_RUN" = false ]; then
    mkdir -p "$INSTALL_DIR" "$CONFIG_DIR" "$SYSTEMD_USER_DIR"
fi

# Copy scripts
echo "Copying scripts..."
for script in "$SCRIPT_DIR"/*.sh; do
    name=$(basename "$script")
    if [ "$DRY_RUN" = true ]; then
        echo "  Would copy $name to $INSTALL_DIR/"
    else
        cp "$script" "$INSTALL_DIR/"
        chmod +x "$INSTALL_DIR/$name"
        echo "  Copied $name"
    fi
done

# Create default config if missing
if [ ! -f "$CONFIG_DIR/config.yaml" ] && [ "$DRY_RUN" = false ]; then
    cat > "$CONFIG_DIR/config.yaml" <<EOF
# Nobara unified configuration
email: "your@email.com"

backup:
  dest: "/mnt/vnnas/backups/raizen"
  sources:
    - "/home/raizen/Documents"
    - "/home/raizen/Pictures"

disk:
  threshold: 85
  targets:
    - "/"
    - "/home"
  cleanup_enabled: true

logs:
  dir: "/home/raizen/.local/share/noba"
EOF
    echo "Created default config at $CONFIG_DIR/config.yaml"
elif [ "$DRY_RUN" = false ]; then
    echo "Config file already exists, skipping."
fi

# Copy systemd user units if they exist
if [ -d "$SCRIPT_DIR/systemd" ]; then
    echo "Copying systemd user units..."
    for unit in "$SCRIPT_DIR"/systemd/*.{timer,service}; do
        if [ -f "$unit" ]; then
            name=$(basename "$unit")
            if [ "$DRY_RUN" = true ]; then
                echo "  Would copy $name to $SYSTEMD_USER_DIR/"
            else
                cp "$unit" "$SYSTEMD_USER_DIR/"
                echo "  Copied $name"
            fi
        fi
    done
else
    echo "No systemd units directory found; skipping."
fi

if [ "$DRY_RUN" = false ]; then
    echo "Reloading systemd user daemon..."
    systemctl --user daemon-reload
fi

echo
echo "Installation complete."
if [ "$DRY_RUN" = false ]; then
    echo "You can now enable timers, e.g.:"
    echo "  systemctl --user enable --now disk-sentinel.timer"
    echo "Edit configuration: $CONFIG_DIR/config.yaml"
fi

📂 Create a systemd/ directory

Place all your timer and service files (the ones we created earlier) in a systemd/ subdirectory. The installer will copy them to the user systemd directory. For example:
text

systemd/
  disk-sentinel.timer
  disk-sentinel.service
  system-report.timer
  system-report.service
  cloud-backup.timer
  cloud-backup.service
  log-rotator.timer
  log-rotator.service
  service-watch.timer
  service-watch.service
  temperature-alert.timer
  temperature-alert.service
  noba-web.service

If you already have them in ~/.config/systemd/user/, you can copy them into the systemd/ folder for distribution.
✅ Final Steps

    Add the new README.md and install.sh to your repository.

    Create the systemd/ folder and move all .timer and .service files into it.

    Commit and push.
