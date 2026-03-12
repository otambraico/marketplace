import sqlite3
from werkzeug.security import generate_password_hash

def crear_admin():
    conn = sqlite3.connect('marketplace.db')
    cursor = conn.cursor()

    # Datos del administrador
    nombre = "Administrador"
    email = "admin@barriomarket.com"
    password = "admin123"  # ¡Cámbiala después!
    password_encriptada = generate_password_hash(password)
    rol = "admin"
    barrio_id = "1"

    try:
        cursor.execute('''
            INSERT INTO usuarios (nombre, email, password, rol, barrio_id, estado) 
            VALUES (?, ?, ?, ?, ?, 'activo')
        ''', (nombre, email, password_encriptada, rol, barrio_id))
        
        conn.commit()
        print("✅ Usuario admin creado con éxito.")
        print(f"Email: {email}")
        print(f"Password: {password}")
    except sqlite3.IntegrityError:
        print("❌ Error: El email ya está registrado.")
    finally:
        conn.close()

if __name__ == "__main__":
    crear_admin()