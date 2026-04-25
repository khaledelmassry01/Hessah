#!/usr/bin/env python3
"""
Fix sector_reference table by dropping the legacy 'id' column.
The 5NF migration promoted 'code' to be the PK, but 'id' was left behind causing INSERT errors.
"""

import mysql.connector
from mysql.connector import Error

def main():
    try:
        conn = mysql.connector.connect(
            host='localhost',
            port=3307,
            database='egx_portfolio',
            user='root',
            password='root'
        )
        
        if conn.is_connected():
            print("✓ Connected to MySQL (egx_portfolio on port 3307)")
            cursor = conn.cursor()
            
            # Check current table structure
            print("\n1. Checking current sector_reference structure...")
            cursor.execute("DESCRIBE sector_reference")
            columns = cursor.fetchall()
            for col in columns:
                print(f"   - {col[0]}: {col[1]} (PK: {col[3]})")
            
            # Execute the fix
            print("\n2. Dropping existing primary key...")
            cursor.execute("ALTER TABLE sector_reference DROP PRIMARY KEY")
            print("   ✓ Primary key dropped")
            
            print("\n3. Dropping legacy 'id' column...")
            cursor.execute("ALTER TABLE sector_reference DROP COLUMN id")
            print("   ✓ 'id' column dropped")
            
            print("\n4. Adding 'code' as primary key...")
            cursor.execute("ALTER TABLE sector_reference ADD PRIMARY KEY (code)")
            print("   ✓ 'code' is now the primary key")
            
            conn.commit()
            
            # Verify the fix
            print("\n5. Verifying new structure...")
            cursor.execute("DESCRIBE sector_reference")
            columns = cursor.fetchall()
            for col in columns:
                pk_marker = " *** PK ***" if col[3] == 'PRI' else ""
                print(f"   - {col[0]}: {col[1]}{pk_marker}")
            
            cursor.close()
            print("\n✓ Fix completed successfully!")
            
    except Error as e:
        print(f"\n✗ Error: {e}")
        if conn and conn.is_connected():
            conn.rollback()
            print("  Changes rolled back")
        raise
    finally:
        if conn and conn.is_connected():
            conn.close()
            print("\n✓ Database connection closed")

if __name__ == "__main__":
    main()
