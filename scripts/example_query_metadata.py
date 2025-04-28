import os
import traceback

import duckdb

# Path relative to the project root
db_path = os.path.join("db", "regulations.db")

if not os.path.exists(db_path):
    print(f"Database file not found at: {db_path}")
else:
    try:
        con = duckdb.connect(database=db_path, read_only=True)
        print(f"Successfully connected to {db_path}\n")

        print("--- Distinct Document Types ---")
        doc_types = con.execute(
            "SELECT DISTINCT meta_data->>'document_type' as doc_type "
            "FROM filerecord ORDER BY doc_type"
        ).fetchall()

        if doc_types:
            for (doc_type,) in doc_types:  # Unpack the tuple
                print(f"- {doc_type or '[NULL]'}")
        else:
            print("- No document types found.")

        con.close()
        print("\nConnection closed.")

    except Exception as e:
        print("\n--- ERROR --- ")
        print(f"Error querying database: {e}")
        print("Traceback:")
        traceback.print_exc()
        if "con" in locals() and con:
            try:
                con.close()
                print("Connection closed after error.")
            except Exception:  # Catch Exception explicitly
                pass
