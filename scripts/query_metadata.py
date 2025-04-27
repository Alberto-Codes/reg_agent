import duckdb
import os
import json

# Path relative to the project root
db_path = os.path.join("db", "regulations.db")

if not os.path.exists(db_path):
    print(f"Database file not found at: {db_path}")
else:
    try:
        con = duckdb.connect(database=db_path, read_only=True)
        print(f"Successfully connected to {db_path}\n")

        print("Querying records (id, filename, status, meta_data)...")
        result = con.execute(
            "SELECT id, filename, status, meta_data FROM filerecord"
        ).fetchall()

        if result:
            for record_id, filename, status, meta_data_json in result:
                print("---")
                print(f"ID:       {record_id}")
                print(f"Filename: {filename}")
                print(f"Status:   {status}")
                # Parse and pretty-print the JSON metadata
                try:
                    meta_data = json.loads(meta_data_json) if meta_data_json else {}
                    print(f"Metadata: {json.dumps(meta_data, indent=2)}")
                except json.JSONDecodeError:
                    print(f"Metadata: Error decoding JSON -> {meta_data_json}")
                except TypeError:
                    print(f"Metadata: Not valid JSON -> {meta_data_json}")

        else:
            print("\n- No records found.")

        con.close()
        print("\nConnection closed.")

    except Exception as e:
        print(f"Error querying database: {e}") 