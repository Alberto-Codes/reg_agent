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

        print("--- Counts by Issuing Agency ---")
        agency_counts = con.execute(
            "SELECT meta_data->>'issuing_agency' as agency, COUNT(*) as count "
            "FROM filerecord GROUP BY agency ORDER BY count DESC"
        ).fetchall()
        if agency_counts:
            for agency, count in agency_counts:
                print(f"{agency or '[NULL]'}: {count}")
        else:
            print("- No data found.")

        # --- Reopen connection before second query (for debugging) ---
        print("\nDEBUG: Re-establishing connection...")
        if "con" in locals() and con:
            con.close()
        con = duckdb.connect(database=db_path, read_only=True)
        # --- End Debug ---

        print("\n--- Counts by Subject Institution ---")
        institution_counts = con.execute(
            "SELECT meta_data->>'subject_institution' as institution, COUNT(*) as count "
            "FROM filerecord GROUP BY institution ORDER BY count DESC"
        ).fetchall()
        if institution_counts:
            for institution, count in institution_counts:
                print(f"{institution or '[NULL]'}: {count}")
        else:
            print("- No data found.")

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
            except:  # nosec
                pass
