import sqlite3

conn = sqlite3.connect('marketplace.db')
cursor = conn.cursor()

# Esto nos da la estructura real de la tabla
cursor.execute("PRAGMA table_info(usuarios)")
columnas = cursor.fetchall()

print("Columnas encontradas en la tabla 'usuarios':")
for col in columnas:
    print(f"- {col[1]} ({col[2]})")

conn.close()