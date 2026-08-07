#!/usr/bin/env python3
"""
Database Migration Runner for DFP AI Intelligence Layer

Usage:
    python scripts/db/migrate.py up         # Apply all pending migrations
    python scripts/db/migrate.py down       # Rollback last migration
    python scripts/db/migrate.py status     # Show migration status
    python scripts/db/migrate.py reset      # Rollback all migrations (DANGEROUS)

    # Specific migration
    python scripts/db/migrate.py up --version 001
    python scripts/db/migrate.py down --version 001
"""

import argparse
import sys
from pathlib import Path

import psycopg2
from psycopg2.extensions import connection, cursor

# Add project root to path
PROJECT_ROOT = Path(__file__).parent.parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

# Load .env from frontend/backend/ so DB credentials don't have to be set
# manually.  Variables already present in the environment take precedence
# (dotenv's override=False default), so CI / explicit exports still work.
try:
    from dotenv import load_dotenv

    _env_file = PROJECT_ROOT / "frontend" / "backend" / ".env"
    if _env_file.exists():
        load_dotenv(_env_file)
except ImportError:
    pass  # python-dotenv not installed — rely on environment variables only

# PostgreSQL connection settings
from modules.utils.db import get_db_params  # noqa: E402

DB_CONFIG = get_db_params()

MIGRATIONS_DIR = Path(__file__).parent / "migrations"


class MigrationRunner:
    """Manages database schema migrations"""

    def __init__(self):
        self.conn: connection | None = None
        self.cursor: cursor | None = None

    def connect(self):
        """Establish database connection"""
        try:
            self.conn = psycopg2.connect(**DB_CONFIG)
            self.cursor = self.conn.cursor()
            print(f"Connected to PostgreSQL: {DB_CONFIG['dbname']}@{DB_CONFIG['host']}:{DB_CONFIG['port']}")
        except psycopg2.Error as e:
            print(f"Failed to connect to PostgreSQL: {e}")
            sys.exit(1)

    def disconnect(self):
        """Close database connection"""
        if self.cursor:
            self.cursor.close()
        if self.conn:
            self.conn.close()

    def create_migrations_table(self):
        """Create migrations tracking table if it doesn't exist"""
        if not self.conn or not self.cursor:
            raise RuntimeError("Database connection not established. Call connect() first.")

        try:
            self.cursor.execute("""
                CREATE TABLE IF NOT EXISTS schema_migrations (
                    version VARCHAR(10) PRIMARY KEY,
                    name VARCHAR(255) NOT NULL,
                    applied_at TIMESTAMP DEFAULT NOW(),
                    rollback_script VARCHAR(255)
                );
            """)
            self.conn.commit()
            print("Migrations tracking table ready")
        except psycopg2.Error as e:
            print(f"Failed to create migrations table: {e}")
            self.conn.rollback()
            sys.exit(1)

    def get_applied_migrations(self) -> list[str]:
        """Get list of applied migration versions"""
        if not self.conn or not self.cursor:
            raise RuntimeError("Database connection not established. Call connect() first.")

        try:
            self.cursor.execute("SELECT version FROM schema_migrations ORDER BY version;")
            return [row[0] for row in self.cursor.fetchall()]
        except psycopg2.Error as e:
            print(f"Could not fetch applied migrations: {e}")
            return []

    def get_available_migrations(self) -> list[tuple[str, Path]]:
        """Get list of available migration files"""
        migrations = []

        if not MIGRATIONS_DIR.exists():
            print(f"Migrations directory not found: {MIGRATIONS_DIR}")
            return migrations

        for file in sorted(MIGRATIONS_DIR.glob("*.sql")):
            if "rollback" not in file.name:
                # Extract version from filename (e.g., "001_create_enriched_anomalies.sql" → "001")
                version = file.name.split("_")[0]
                migrations.append((version, file))

        return migrations

    def apply_migration(self, version: str, migration_file: Path) -> bool:
        """Apply a specific migration"""
        if not self.conn or not self.cursor:
            raise RuntimeError("Database connection not established. Call connect() first.")

        print(f"\nApplying migration {version}: {migration_file.name}")

        try:
            # Read migration SQL
            with open(migration_file) as f:
                sql_content = f.read()

            # Execute migration
            self.cursor.execute(sql_content)

            # Record migration
            migration_name = migration_file.stem
            rollback_file = f"{version}_rollback.sql"

            self.cursor.execute(
                "INSERT INTO schema_migrations (version, name, rollback_script) VALUES (%s, %s, %s);",
                (version, migration_name, rollback_file),
            )

            self.conn.commit()
            print(f"Migration {version} applied successfully")
            return True

        except psycopg2.Error as e:
            print(f"Migration {version} failed: {e}")
            self.conn.rollback()
            return False

    def rollback_migration(self, version: str) -> bool:
        """Rollback a specific migration"""
        if not self.conn or not self.cursor:
            raise RuntimeError("Database connection not established. Call connect() first.")

        print(f"\nRolling back migration {version}")

        try:
            # Get rollback script name
            self.cursor.execute("SELECT rollback_script FROM schema_migrations WHERE version = %s;", (version,))
            result = self.cursor.fetchone()

            if not result:
                print(f"Migration {version} not found in applied migrations")
                return False

            rollback_file = MIGRATIONS_DIR / result[0]

            if not rollback_file.exists():
                print(f"Rollback script not found: {rollback_file}")
                return False

            # Read rollback SQL
            with open(rollback_file) as f:
                sql_content = f.read()

            # Execute rollback
            self.cursor.execute(sql_content)

            # Remove migration record
            self.cursor.execute("DELETE FROM schema_migrations WHERE version = %s;", (version,))

            self.conn.commit()
            print(f"Migration {version} rolled back successfully")
            return True

        except psycopg2.Error as e:
            print(f"Rollback {version} failed: {e}")
            self.conn.rollback()
            return False

    def migrate_up(self, target_version: str | None = None):
        """Apply all pending migrations or up to a specific version"""
        applied = self.get_applied_migrations()
        available = self.get_available_migrations()

        pending = [(version, path) for version, path in available if version not in applied]

        if target_version:
            pending = [(version, path) for version, path in pending if version <= target_version]

        if not pending:
            print("\nNo pending migrations")
            return

        print(f"\nFound {len(pending)} pending migration(s)")

        for version, migration_file in pending:
            if not self.apply_migration(version, migration_file):
                print("\nMigration aborted due to errors")
                sys.exit(1)

        print("\nAll migrations applied successfully")

    def migrate_down(self, target_version: str | None = None):
        """Rollback last migration or a specific version"""
        applied = self.get_applied_migrations()

        if not applied:
            print("\nNo migrations to rollback")
            return

        if target_version:
            if target_version not in applied:
                print(f"\nMigration {target_version} is not applied")
                return
            to_rollback = [target_version]
        else:
            # Rollback only the last one
            to_rollback = [applied[-1]]

        for version in reversed(to_rollback):
            if not self.rollback_migration(version):
                print("\nRollback aborted due to errors")
                sys.exit(1)

        print("\nRollback completed successfully")

    def show_status(self):
        """Show migration status"""
        applied = self.get_applied_migrations()
        available = self.get_available_migrations()

        print("\n" + "=" * 70)
        print("DATABASE MIGRATION STATUS")
        print("=" * 70)

        print(f"\nDatabase: {DB_CONFIG['dbname']}@{DB_CONFIG['host']}:{DB_CONFIG['port']}")
        print(f"Migrations directory: {MIGRATIONS_DIR}")

        print(f"\nApplied migrations: {len(applied)}")
        if applied:
            for version in applied:
                print(f"   • {version}")
        else:
            print("   (none)")

        pending = [version for version, _ in available if version not in applied]

        print(f"\nPending migrations: {len(pending)}")
        if pending:
            for version in pending:
                print(f"   • {version}")
        else:
            print("   (none)")

        print("\n" + "=" * 70)

    def reset(self):
        """Rollback all migrations (DANGEROUS)"""
        print("\nWARNING: This will rollback ALL migrations!")
        confirm = input("Type 'RESET' to confirm: ")

        if confirm != "RESET":
            print("Reset cancelled")
            return

        applied = self.get_applied_migrations()

        if not applied:
            print("\nNo migrations to rollback")
            return

        print(f"\nRolling back {len(applied)} migration(s)...")

        for version in reversed(applied):
            if not self.rollback_migration(version):
                print("\nReset aborted due to errors")
                sys.exit(1)

        print("\nAll migrations rolled back successfully")


def main():
    parser = argparse.ArgumentParser(description="Database migration runner for DFP AI Intelligence Layer")
    parser.add_argument("command", choices=["up", "down", "status", "reset"], help="Migration command")
    parser.add_argument("--version", help="Target migration version (e.g., 001)")

    args = parser.parse_args()

    runner = MigrationRunner()

    try:
        runner.connect()
        runner.create_migrations_table()

        if args.command == "up":
            runner.migrate_up(args.version)
        elif args.command == "down":
            runner.migrate_down(args.version)
        elif args.command == "status":
            runner.show_status()
        elif args.command == "reset":
            runner.reset()

    except KeyboardInterrupt:
        print("\n\nMigration interrupted by user")
        sys.exit(1)
    finally:
        runner.disconnect()


if __name__ == "__main__":
    main()
