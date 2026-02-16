#!/bin/bash

SCRIPT_DIR="$( cd "$( dirname "${BASH_SOURCE[0]}" )" &> /dev/null && pwd )"
cd "$SCRIPT_DIR/.."

python -m venv .venv
source ./.venv/Scripts/activate
python -m pip install --upgrade pip

# Install dependencies
if [ -f "config/requirements.lock.txt" ]; then
    echo "Installing from saved requirements.lock.txt"
    python -m pip install -r config/requirements.lock.txt
elif [ -f "config/requirements.txt" ]; then
    echo "Installing from default requirements.txt"
    python -m pip install -r config/requirements.txt
else
    echo "No requirements file found, only setup with pip and ipynb packages."
    python -m pip install ipykernel jupyterlab
fi
python -m ipykernel install --user --name $(basename "$SCRIPT_DIR")