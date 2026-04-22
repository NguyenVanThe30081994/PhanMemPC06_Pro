#!/bin/bash
pkill -f "python3 app.py"
nohup python3 app.py > scratch/app.log 2>&1 &
echo "Server restarted"
