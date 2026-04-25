#!/usr/bin/env python3
"""
Database Schema Extractor for 5NF Normalization Audit
Connects to MySQL and extracts complete schema metadata
"""

import mysql.connector
import json
from datetime import datetime

DB_CONFIG = {
    "host": "localhost",
    "port": 3307,
    "user": "root",
    "password": "EGX_Root_9rT!5Vy3#K2Nq7",
    "database": "egx_portfolio"
}

def connect_to_db(database=None):
    """Establish database connection"""
    config = DB_CONFIG.copy()
    if database:
        config["database"] = database
    else:
        config.pop("database", None)
    return mysql.connector.connect(**config)

def get_databases(conn):
    """Get list of all databases excluding system ones"""
    cursor = conn.cursor()
    cursor.execute("""
        SELECT schema_name FROM information_schema.schemata 
        WHERE schema_name NOT IN ('information_schema', 'mysql', 'performance_schema', 'sys')
    """)
    return [row[0] for row in cursor.fetchall()]

def get_tables(conn, database):
    """Get all tables for a database"""
    cursor = conn.cursor()
    cursor.execute("""
        SELECT table_name, table_type, engine, table_collation
        FROM information_schema.tables 
        WHERE table_schema = %s
    """, (database,))
    return [
        {
            "table_name": row[0],
            "table_type": row[1],
            "engine": row[2],
            "collation": row[3]
        }
        for row in cursor.fetchall()
    ]

def get_columns(conn, database, table_name):
    """Get all columns for a table with full metadata"""
    cursor = conn.cursor(dictionary=True)
    cursor.execute("""
        SELECT 
            column_name,
            ordinal_position,
            column_default,
            is_nullable,
            data_type,
            character_maximum_length,
            numeric_precision,
            numeric_scale,
            datetime_precision,
            column_type,
            column_key,
            extra,
            column_comment
        FROM information_schema.columns 
        WHERE table_schema = %s AND table_name = %s
        ORDER BY ordinal_position
    """, (database, table_name))
    return cursor.fetchall()

def get_primary_keys(conn, database, table_name):
    """Get primary key columns"""
    cursor = conn.cursor()
    cursor.execute("""
        SELECT column_name, ordinal_position
        FROM information_schema.key_column_usage
        WHERE table_schema = %s 
        AND table_name = %s 
        AND constraint_name = 'PRIMARY'
        ORDER BY ordinal_position
    """, (database, table_name))
    return [row[0] for row in cursor.fetchall()]

def get_foreign_keys(conn, database, table_name):
    """Get foreign key relationships"""
    cursor = conn.cursor(dictionary=True)
    cursor.execute("""
        SELECT 
            kcu.column_name,
            kcu.referenced_table_name,
            kcu.referenced_column_name,
            kcu.constraint_name,
            rc.delete_rule,
            rc.update_rule
        FROM information_schema.key_column_usage kcu
        JOIN information_schema.referential_constraints rc 
            ON kcu.constraint_name = rc.constraint_name
            AND kcu.table_schema = rc.constraint_schema
        WHERE kcu.table_schema = %s 
        AND kcu.table_name = %s 
        AND kcu.referenced_table_name IS NOT NULL
    """, (database, table_name))
    return cursor.fetchall()

def get_indexes(conn, database, table_name):
    """Get all indexes for a table"""
    cursor = conn.cursor(dictionary=True)
    cursor.execute("""
        SELECT 
            index_name,
            column_name,
            seq_in_index,
            non_unique,
            index_type
        FROM information_schema.statistics
        WHERE table_schema = %s AND table_name = %s
        ORDER BY index_name, seq_in_index
    """, (database, table_name))
    return cursor.fetchall()

def get_table_constraints(conn, database, table_name):
    """Get CHECK constraints and other constraints"""
    cursor = conn.cursor(dictionary=True)
    cursor.execute("""
        SELECT 
            constraint_name,
            constraint_type,
            enforced
        FROM information_schema.table_constraints
        WHERE table_schema = %s AND table_name = %s
    """, (database, table_name))
    return cursor.fetchall()

def get_show_create_table(conn, table_name):
    """Get the CREATE TABLE statement"""
    cursor = conn.cursor()
    try:
        cursor.execute(f"SHOW CREATE TABLE `{table_name}`")
        result = cursor.fetchone()
        return result[1] if result else None
    except Exception as e:
        return f"ERROR: {str(e)}"

def get_row_count(conn, table_name):
    """Get approximate row count"""
    cursor = conn.cursor()
    try:
        cursor.execute(f"SELECT COUNT(*) FROM `{table_name}`")
        return cursor.fetchone()[0]
    except Exception as e:
        return f"ERROR: {str(e)}"

def get_table_stats(conn, database, table_name):
    """Get table statistics"""
    cursor = conn.cursor(dictionary=True)
    cursor.execute("""
        SELECT 
            table_rows,
            data_length,
            index_length,
            data_free,
            auto_increment,
            create_time,
            update_time
        FROM information_schema.tables
        WHERE table_schema = %s AND table_name = %s
    """, (database, table_name))
    result = cursor.fetchone()
    return result or {}

def extract_complete_schema():
    """Main function to extract complete schema"""
    print("="*80)
    print("DATABASE SCHEMA EXTRACTOR - 5NF Normalization Audit")
    print("="*80)
    print(f"Timestamp: {datetime.now().isoformat()}")
    print(f"Host: {DB_CONFIG['host']}:{DB_CONFIG['port']}")
    print("="*80)
    
    # First, connect without database to find available databases
    try:
        conn = connect_to_db()
        databases = get_databases(conn)
        print(f"\nFound {len(databases)} database(s): {databases}")
        conn.close()
    except Exception as e:
        print(f"Connection error: {e}")
        return
    
    full_schema = {}
    
    for db_name in databases:
        print(f"\n{'='*80}")
        print(f"DATABASE: {db_name}")
        print(f"{'='*80}")
        
        try:
            conn = connect_to_db(db_name)
            tables = get_tables(conn, db_name)
            print(f"Found {len(tables)} table(s)")
            
            db_schema = {
                "database_name": db_name,
                "tables": {}
            }
            
            for table in tables:
                table_name = table["table_name"]
                print(f"\n  Analyzing table: {table_name}")
                
                # Get all metadata
                columns = get_columns(conn, db_name, table_name)
                primary_keys = get_primary_keys(conn, db_name, table_name)
                foreign_keys = get_foreign_keys(conn, db_name, table_name)
                indexes = get_indexes(conn, db_name, table_name)
                constraints = get_table_constraints(conn, db_name, table_name)
                create_statement = get_show_create_table(conn, table_name)
                row_count = get_row_count(conn, table_name)
                stats = get_table_stats(conn, db_name, table_name)
                
                db_schema["tables"][table_name] = {
                    "metadata": table,
                    "columns": columns,
                    "primary_keys": primary_keys,
                    "foreign_keys": foreign_keys,
                    "indexes": indexes,
                    "constraints": constraints,
                    "create_statement": create_statement,
                    "row_count": row_count,
                    "stats": stats
                }
                
                print(f"    - Columns: {len(columns)}")
                print(f"    - PK: {primary_keys}")
                print(f"    - FKs: {len(foreign_keys)}")
                non_pk_indexes = [i for i in indexes if i.get('index_name') != 'PRIMARY']
                print(f"    - Indexes: {len(non_pk_indexes)}")
                print(f"    - Rows: {row_count}")
            
            full_schema[db_name] = db_schema
            conn.close()
            
        except Exception as e:
            print(f"Error processing database {db_name}: {e}")
            import traceback
            traceback.print_exc()
            continue
    
    # Save to JSON file for analysis
    output_file = "schema_audit_raw.json"
    try:
        class DateTimeEncoder(json.JSONEncoder):
            def default(self, obj):
                if isinstance(obj, datetime):
                    return obj.isoformat()
                return super().default(obj)
        
        with open(output_file, "w", encoding="utf-8") as f:
            json.dump(full_schema, f, indent=2, cls=DateTimeEncoder)
        
        print(f"\n{'='*80}")
        print(f"Schema extraction complete. Data saved to: {output_file}")
        print(f"{'='*80}")
    except Exception as e:
        print(f"Error saving JSON: {e}")
        import traceback
        traceback.print_exc()
    
    return full_schema

if __name__ == "__main__":
    extract_complete_schema()
