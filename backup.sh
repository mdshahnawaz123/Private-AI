#!/bin/bash
# Expo Design AI — Backup Script (Phase 9)
# Backs up: source files, database, knowledge, configuration, model registry, audit log
# Original source documents are recoverable independently of vector indexes.

BACKUP_DIR="${1:-./backups}"
TIMESTAMP=$(date +%Y%m%d_%H%M%S)
BACKUP_PATH="$BACKUP_DIR/expo_backup_$TIMESTAMP"

echo "=== Expo Design AI Backup ==="
echo "Backup path: $BACKUP_PATH"
echo "Timestamp: $TIMESTAMP"

mkdir -p "$BACKUP_PATH"

# 1. Source files (immutable originals)
echo "Backing up source files..."
cp -r data/docs "$BACKUP_PATH/"

# 2. Database
echo "Backing up database..."
cp data/expo.db "$BACKUP_PATH/"

# 3. FAISS indexes (rebuildable, but backed up for speed)
echo "Backing up vector indexes..."
cp -r data/faiss_index "$BACKUP_PATH/"

# 4. Configuration
echo "Backing up configuration..."
cp .env "$BACKUP_PATH/" 2>/dev/null || echo "No .env file"
cp alembic.ini "$BACKUP_PATH/"

# 5. Logs
echo "Backing up logs..."
cp -r data/logs "$BACKUP_PATH/"

# 6. Secret key
echo "Backing up secret key..."
cp data/secret.key "$BACKUP_PATH/" 2>/dev/null || echo "No secret key file"

# 7. Create manifest
cat > "$BACKUP_PATH/manifest.json" << EOF
{
  "timestamp": "$TIMESTAMP",
  "version": "1.0",
  "contents": {
    "source_files": "data/docs/",
    "database": "data/expo.db",
    "vector_indexes": "data/faiss_index/",
    "configuration": ".env, alembic.ini",
    "logs": "data/logs/",
    "secret_key": "data/secret.key"
  },
  "notes": "Source files are immutable and recoverable independently. Vector indexes can be rebuilt from source."
}
EOF

# 8. Compress
echo "Compressing backup..."
tar -czf "$BACKUP_PATH.tar.gz" -C "$BACKUP_DIR" "expo_backup_$TIMESTAMP"
rm -rf "$BACKUP_PATH"

echo "=== Backup complete ==="
echo "File: $BACKUP_PATH.tar.gz"
echo "Size: $(du -h "$BACKUP_PATH.tar.gz" | cut -f1)"
echo ""
echo "To restore:"
echo "  tar -xzf $BACKUP_PATH.tar.gz -C ./"
