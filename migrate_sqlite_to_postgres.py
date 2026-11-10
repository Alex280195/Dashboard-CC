"""Copy the local SQLite dashboard database into an empty PostgreSQL database."""
import argparse
import os
import sqlite3

import db

TABLES = ('users', 'config', 'indikator', 'kontributor', 'poin_tier', 'pengaturan', 'log')
SEQUENCED_TABLES = ('config', 'indikator', 'kontributor', 'poin_tier', 'log')


def migrate(source_path, replace=False):
    if db.is_sqlite():
        raise RuntimeError('Set DATABASE_URL to the destination PostgreSQL database before migrating.')
    if not os.path.isfile(source_path):
        raise FileNotFoundError(f'SQLite source database not found: {source_path}')

    db.init(seed=False, create_admin=False)
    source = sqlite3.connect(source_path)
    source.row_factory = sqlite3.Row
    try:
        with db.conn() as target:
            target_counts = {
                table: target.execute(f'SELECT COUNT(*) FROM {table}').fetchone()[0]
                for table in TABLES
            }
            if any(target_counts.values()) and not replace:
                raise RuntimeError('Destination database is not empty. Use --replace only if its data can be overwritten.')
            if replace:
                for table in reversed(TABLES):
                    target.execute(f'DELETE FROM {table}')

            imported = {}
            for table in TABLES:
                cursor = source.execute(f'SELECT * FROM {table}')
                columns = [column[0] for column in cursor.description]
                placeholders = ','.join('?' for _ in columns)
                sql = f'INSERT INTO {table}({",".join(columns)}) VALUES({placeholders})'
                rows = cursor.fetchall()
                for row in rows:
                    target.execute(sql, tuple(row))
                imported[table] = len(rows)

            for table in SEQUENCED_TABLES:
                target.execute(
                    f"SELECT setval(pg_get_serial_sequence(?, 'id'), "
                    f"COALESCE(MAX(id), 1), MAX(id) IS NOT NULL) FROM {table}",
                    (table,),
                )
    finally:
        source.close()
    return imported


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--source', default=db.DB_PATH, help='SQLite file to migrate (default: data/dashboard.db)')
    parser.add_argument('--replace', action='store_true',
                        help='overwrite existing PostgreSQL rows; use only after backing up the destination')
    parser.add_argument('--confirm-user-passwords-changed', action='store_true',
                        help='confirm local user accounts have strong passwords before copying password hashes')
    args = parser.parse_args()
    if not args.confirm_user_passwords_changed:
        parser.error('Change local user passwords to strong, unique values before migration, then pass '
                     '--confirm-user-passwords-changed.')
    counts = migrate(args.source, replace=args.replace)
    print('Migration completed: ' + ', '.join(f'{table}={count}' for table, count in counts.items()))


if __name__ == '__main__':
    main()
