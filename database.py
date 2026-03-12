import sqlite3

def init_db():
    conn = sqlite3.connect('marketplace.db')
    cursor = conn.cursor()
    
    # Activar el soporte para llaves foráneas en SQLite
    cursor.execute('PRAGMA foreign_keys = ON')

    # 1. TABLA MAESTRA: Categorías
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS maestro_categorias (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            nombre TEXT UNIQUE NOT NULL
        )
    ''')

    # 2. TABLA MAESTRA: Barrios/Sectores
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS maestro_barrios (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            nombre TEXT UNIQUE NOT NULL
        )
    ''')

    # 3. TABLA: Usuarios 
    # NOTA: He incluido 'barrio_id' aquí para que Clientes y Mypes lo tengan por igual
    # También incluimos 'estado' y 'fecha_registro' desde el inicio
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS usuarios (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            nombre TEXT NOT NULL,
            email TEXT UNIQUE NOT NULL,
            password TEXT NOT NULL,
            rol TEXT CHECK(rol IN ('mype', 'cliente', 'admin')) DEFAULT 'cliente',
            barrio_id INTEGER,
            estado TEXT DEFAULT 'activo',
            latitud REAL, 
            longitud REAL,
            fecha_registro TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            FOREIGN KEY (barrio_id) REFERENCES maestro_barrios(id)
        )
    ''')

    # 4. TABLA: Perfil MYPE
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS perfiles_mype (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            usuario_id INTEGER,
            nombre_comercial TEXT,
            descripcion TEXT,
            categoria_id INTEGER,
            FOREIGN KEY (usuario_id) REFERENCES usuarios(id),
            FOREIGN KEY (categoria_id) REFERENCES maestro_categorias(id)
        )
    ''')

    # 5. TABLA: Productos
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS productos (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            mype_id INTEGER,
            nombre TEXT NOT NULL,
            descripcion TEXT,
            precio REAL NOT NULL,
            foto_url TEXT,
            fecha_creacion TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            FOREIGN KEY (mype_id) REFERENCES perfiles_mype(id)
        )
    ''')

    # --- PRECARGA DE DATOS ---
    categorias = [('Alimentos',), ('Ropa y Calzado',), ('Servicios Técnicos',), ('Hogar',), ('Salud',)]
    cursor.executemany('INSERT OR IGNORE INTO maestro_categorias (nombre) VALUES (?)', categorias)

    barrios = [('Sector Norte',), ('Sector Sur',), ('Centro Histórico',), ('Zona Residencial',), ('Barrio Comercial',)]
    cursor.executemany('INSERT OR IGNORE INTO maestro_barrios (nombre) VALUES (?)', barrios)
    
    conn.commit()
    conn.close()
    print("✅ Base de datos 'marketplace.db' creada y poblada con éxito.")

if __name__ == "__main__":
    init_db()
