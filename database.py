import sqlite3

def init_db():
    conn = sqlite3.connect('marketplace.db')
    cursor = conn.cursor()
    
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

    # 3. TABLA: Usuarios (sin cambios)
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS usuarios (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            nombre TEXT NOT NULL,
            email TEXT UNIQUE NOT NULL,
            password TEXT NOT NULL,
            rol TEXT CHECK(rol IN ('mype', 'cliente', 'admin')) DEFAULT 'cliente',
            latitud REAL, longitud REAL
        )
    ''')

    # 4. TABLA: Perfil MYPE (Ahora usa llaves foráneas a los maestros)
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS perfiles_mype (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            usuario_id INTEGER,
            nombre_comercial TEXT,
            descripcion TEXT,
            categoria_id INTEGER,
            barrio_id INTEGER,
            FOREIGN KEY (usuario_id) REFERENCES usuarios(id),
            FOREIGN KEY (categoria_id) REFERENCES maestro_categorias(id),
            FOREIGN KEY (barrio_id) REFERENCES maestro_barrios(id)
        )
    ''')

    # --- PRECARGA DE DATOS ESTÁNDAR ---
    categorias = [
        ('Alimentos',),
        ('Ropa y Calzado',),
        ('Servicios Técnicos',),
        ('Hogar',),
        ('Salud',)
        ]
    cursor.executemany('INSERT OR IGNORE INTO maestro_categorias (nombre) VALUES (?)', categorias)

    barrios = [
        ('Sector Norte',),
        ('Sector Sur',),
        ('Centro Histórico',),
        ('Zona Residencial',),
        ('Barrio Comercial',)
        ]
    cursor.executemany('INSERT OR IGNORE INTO maestro_barrios (nombre) VALUES (?)', barrios)

    # Agrega esto a tu función init_db() en database.py
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
    
    conn.commit()
    conn.close()

init_db()
