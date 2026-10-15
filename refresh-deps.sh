#!/bin/bash
git pull
echo "Upgrading uv ..."
mise upgrade
echo "Upgrading uv deps ..."
uv lock --upgrade
echo "Pre-commit autoupdate ..."
pre-commit autoupdate
