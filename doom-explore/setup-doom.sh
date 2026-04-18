#!/bin/bash
set -e

DOOM_DIR="doom-src"

if [ -d "$DOOM_DIR" ]; then
  echo "Directory '$DOOM_DIR' already exists. Remove it first if you want a fresh clone."
  exit 1
fi

echo "Cloning DOOM source..."
git clone --depth=1 https://github.com/id-software/doom "$DOOM_DIR"
rm -rf "$DOOM_DIR/.git"
echo "Removed .git from cloned repo."

if ! grep -qxF "$DOOM_DIR" .gitignore 2>/dev/null; then
  echo "$DOOM_DIR" >> .gitignore
  echo "Added '$DOOM_DIR' to .gitignore."
fi

echo "Done. DOOM source is in ./$DOOM_DIR"
