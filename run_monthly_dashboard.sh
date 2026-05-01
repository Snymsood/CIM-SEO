#!/bin/bash

# Monthly Dashboard Complete Runner
# Runs all data collection scripts + generates complete dashboard
# Usage: ./run_monthly_dashboard.sh

set -e  # Exit on error

echo "╔══════════════════════════════════════════════════════════════════════════════╗"
echo "║                    MONTHLY SEO DASHBOARD - COMPLETE RUN                      ║"
echo "║                                                                              ║"
echo "║  This script will:                                                           ║"
echo "║  1. Collect PageSpeed Insights data                                         ║"
echo "║  2. Collect AI snippet verification data                                    ║"
echo "║  3. Collect content audit data                                              ║"
echo "║  4. Generate complete monthly dashboard                                     ║"
echo "║                                                                              ║"
echo "║  Estimated time: 30-45 minutes                                              ║"
echo "╚══════════════════════════════════════════════════════════════════════════════╝"
echo ""

# Check if Python is available
if ! command -v python &> /dev/null; then
    echo "❌ Error: Python not found. Please install Python 3.8+"
    exit 1
fi

# Check if required files exist
if [ ! -f "gsc-key.json" ]; then
    echo "❌ Error: gsc-key.json not found"
    echo "   Please add your Google Service Account key to the project root"
    exit 1
fi

if [ ! -f ".env" ]; then
    echo "⚠️  Warning: .env file not found"
    echo "   Some features may not work without environment variables"
    echo ""
fi

# Function to run a script with error handling
run_script() {
    local script=$1
    local description=$2
    local optional=$3
    
    echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
    echo "▶ $description"
    echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
    echo ""
    
    if python "$script"; then
        echo ""
        echo "✅ $description - COMPLETE"
        echo ""
        return 0
    else
        if [ "$optional" = "true" ]; then
            echo ""
            echo "⚠️  $description - FAILED (optional, continuing...)"
            echo ""
            return 0
        else
            echo ""
            echo "❌ $description - FAILED"
            echo ""
            exit 1
        fi
    fi
}

# Start timestamp
start_time=$(date +%s)

echo "🚀 Starting complete dashboard generation..."
echo ""

# Phase 1: PageSpeed Insights Data
run_script "site_speed_monitoring.py" "PHASE 1/4: Collecting PageSpeed Insights data" "true"

# Phase 2: AI Snippet Verification Data
run_script "ai_snippet_verification.py" "PHASE 2/4: Collecting AI snippet verification data" "true"

# Phase 3: Content Audit Data
run_script "content_audit_schedule_report.py" "PHASE 3/4: Collecting content audit data" "true"

# Phase 4: Generate Monthly Dashboard
run_script "monthly_master_report.py" "PHASE 4/4: Generating monthly dashboard" "false"

# End timestamp
end_time=$(date +%s)
duration=$((end_time - start_time))
minutes=$((duration / 60))
seconds=$((duration % 60))

echo "╔══════════════════════════════════════════════════════════════════════════════╗"
echo "║                         DASHBOARD GENERATION COMPLETE                        ║"
echo "║                                                                              ║"
echo "║  Output: monthly_dashboard.html                                             ║"
echo "║  Charts: charts/*.png (23 files)                                            ║"
echo "║  Data:   monthly_data/*.csv (10+ files)                                     ║"
echo "║                                                                              ║"
echo "║  Total time: ${minutes}m ${seconds}s                                                            ║"
echo "╚══════════════════════════════════════════════════════════════════════════════╝"
echo ""
echo "📊 To view the dashboard:"
echo "   open monthly_dashboard.html"
echo ""
echo "📁 Output files:"
echo "   - monthly_dashboard.html (~2-3 MB)"
echo "   - charts/ (23 PNG files)"
echo "   - monthly_data/ (10+ CSV files)"
echo ""

# Check if dashboard was created
if [ -f "monthly_dashboard.html" ]; then
    file_size=$(du -h monthly_dashboard.html | cut -f1)
    echo "✅ Dashboard file created: $file_size"
    
    # Offer to open the dashboard
    echo ""
    read -p "Would you like to open the dashboard now? (y/n) " -n 1 -r
    echo ""
    if [[ $REPLY =~ ^[Yy]$ ]]; then
        if command -v open &> /dev/null; then
            open monthly_dashboard.html
        elif command -v xdg-open &> /dev/null; then
            xdg-open monthly_dashboard.html
        else
            echo "Please open monthly_dashboard.html manually"
        fi
    fi
else
    echo "⚠️  Warning: monthly_dashboard.html not found"
    echo "   Check the output above for errors"
fi

echo ""
echo "🎉 Done!"
