#!/bin/bash
# update_nba_data.sh
# Script to automate NBA data updates

set -e  # Exit on error

# Configuration
DATA_DIR="/path/to/your/data/directory"
STATIC_FILE="/path/to/your/nba_static_data.py"
FLASK_APP="/path/to/your/your_flask_app.py"
LOG_FILE="/path/to/your/logs/nba_update.log"

# Function to log messages
log_message() {
    echo "$(date '+%Y-%m-%d %H:%M:%S') - $1" >> "$LOG_FILE"
}

log_message "Starting NBA data update"

# Step 1: Download latest CSV (customize this based on your data source)
# Example: wget -q -O "$DATA_DIR/nba_stats_latest.csv" "https://your-datasource.com/nba-stats.csv"
log_message "Downloading latest CSV..."

# For testing, you can use a local file
if [ ! -f "$DATA_DIR/nba_stats_latest.csv" ]; then
    log_message "⚠️ No CSV file found, skipping download step"
    # exit 0  # Uncomment if download is required
fi

# Step 2: Run the update script
log_message "Updating static data file..."
python3 "$DATA_DIR/update_nba_static.py" "$DATA_DIR/nba_stats_latest.csv" --output "$STATIC_FILE"

if [ $? -eq 0 ]; then
    log_message "✅ Static data updated successfully"
    
    # Step 3: Restart Flask app (choose one method)
    
    # Option A: If running with systemd
    # sudo systemctl restart your-flask-app
    
    # Option B: If running with gunicorn/ supervisor
    # supervisorctl restart your-flask-app
    
    # Option C: Touch a file that triggers reload (if using --reload)
    touch "$FLASK_APP"
    
    log_message "✅ Flask app restarted/reloaded"
    
    # Step 4: Test the endpoint
    log_message "Testing endpoint..."
    python3 "$DATA_DIR/test_nba_endpoint.py" >> "$LOG_FILE" 2>&1
    
    if [ $? -eq 0 ]; then
        log_message "✅ Endpoint test passed"
    else:
        log_message "❌ Endpoint test failed"
fi

log_message "Update process completed"
