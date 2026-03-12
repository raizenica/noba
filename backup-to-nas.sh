#!/bin/bash
# Backup to NAS with HTML email

BACKUP_DIR="/mnt/vnnas/backups/raizen"
mkdir -p "$BACKUP_DIR"

# Start time
START_TIME=$(date +%s)

# Backup Documents, Pictures, and important configs
rsync -av --delete /home/raizen/Documents "$BACKUP_DIR/" > /tmp/backup.log 2>&1
rsync -av --delete /home/raizen/Pictures "$BACKUP_DIR/" >> /tmp/backup.log 2>&1
rsync -av --delete /home/raizen/.config "$BACKUP_DIR/config/" >> /tmp/backup.log 2>&1

# Calculate stats
END_TIME=$(date +%s)
DURATION=$((END_TIME - START_TIME))
FILES_COUNT=$(grep -c "sent" /tmp/backup.log)
SIZE=$(du -sh "$BACKUP_DIR" | cut -f1)

# Send HTML email
{
  echo "To: strikerke@gmail.com"
  echo "Subject: 💾 NAS Backup Complete - $(date +%Y-%m-%d)"
  echo "MIME-Version: 1.0"
  echo "Content-Type: text/html; charset=utf-8"
  echo ""
  echo '<!DOCTYPE html>'
  echo '<html><head><style>'
  echo 'body { font-family: Arial, sans-serif; line-height: 1.6; color: #333; }'
  echo '.container { max-width: 600px; margin: 20px auto; padding: 20px; border-radius: 10px; background: #f9f9f9; }'
  echo '.header { background: #2196F3; color: white; padding: 15px; border-radius: 10px 10px 0 0; margin: -20px -20px 20px -20px; }'
  echo '.stats { display: grid; grid-template-columns: 1fr 1fr; gap: 15px; margin: 20px 0; }'
  echo '.stat-card { background: white; padding: 15px; border-radius: 8px; box-shadow: 0 2px 4px rgba(0,0,0,0.1); }'
  echo '.stat-label { font-size: 12px; color: #666; text-transform: uppercase; }'
  echo '.stat-value { font-size: 24px; font-weight: bold; color: #2196F3; }'
  echo '.log { background: #1e1e1e; color: #00ff00; padding: 15px; border-radius: 8px; font-family: monospace; font-size: 12px; overflow-x: auto; }'
  echo '.footer { margin-top: 30px; padding-top: 20px; border-top: 1px solid #ddd; font-size: 12px; color: #666; }'
  echo '</style></head><body>'
  echo '<div class="container">'
  echo '<div class="header"><h2 style="margin:0;">💾 NAS Backup Report</h2></div>'
  echo '<p>Backup completed successfully at <strong>'"$(date '+%Y-%m-%d %H:%M:%S')"'</strong></p>'
  echo '<div class="stats">'
  echo '<div class="stat-card"><div class="stat-label">Duration</div><div class="stat-value">'"$DURATION"'s</div></div>'
  echo '<div class="stat-card"><div class="stat-label">Files Synced</div><div class="stat-value">'"$FILES_COUNT"'</div></div>'
  echo '<div class="stat-card"><div class="stat-label">Total Size</div><div class="stat-value">'"$SIZE"'</div></div>'
  echo '<div class="stat-card"><div class="stat-label">Destination</div><div class="stat-value">NAS</div></div>'
  echo '</div>'
  echo '<h3>📋 Sync Log:</h3>'
  echo '<div class="log">'"$(tail -20 /tmp/backup.log | sed 's/$/<br>/')"'</div>'
  echo '<div class="footer">'
  echo '✅ Backup automated • '"$(hostname)"' → vnnas'
  echo '</div>'
  echo '</div></body></html>'
} | msmtp strikerke@gmail.com

rm /tmp/backup.log
