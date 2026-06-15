import os
import pathlib

import psycopg

URL = os.environ["DATABASE_URL"].replace("+psycopg", "")
here = pathlib.Path(__file__).parent
with psycopg.connect(URL) as conn:
    for f in sorted(here.glob("*.sql")):
        print(f"Applying {f.name}")
        conn.execute(f.read_text())
    conn.commit()
print("Seeds applied.")
