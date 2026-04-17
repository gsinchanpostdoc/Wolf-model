#!/bin/bash
# Launch the Wolf Territory Map app
# Make executable with: chmod +x run.sh
cd "$(dirname "$0")"
streamlit run app/wolf_map.py
