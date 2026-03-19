import psycopg2
from psycopg2.extras import RealDictCursor
import os

# Render o Supabase te darán esta URL (empieza con postgres://)
DATABASE_URL = os.environ.get('DATABASE_URL')

def get_db_connection():
    # Establece conexión con el servidor remoto
    conn = psycopg2.connect(DATABASE_URL, cursor_factory=RealDictCursor)
    return conn

def init_db():
    conn = get_db_connection()
    cursor = conn.cursor()

    # Crear tablas con SERIAL [cite: 14]
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS maestro_barrios (
            id SERIAL PRIMARY KEY,
            nombre TEXT UNIQUE NOT NULL
        )
    ''')

    # 2. TABLA MAESTRA: Barrios/Sectores
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS maestro_barrios (
            id SERIAL PRIMARY KEY,
            nombre TEXT UNIQUE NOT NULL
        )
    ''')

    # 3. TABLA: Usuarios
    # Cambiamos REAL por DOUBLE PRECISION para mayor precisión en mapas
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS usuarios (
            id SERIAL PRIMARY KEY,
            nombre TEXT NOT NULL,
            email TEXT UNIQUE NOT NULL,
            password TEXT NOT NULL,
            rol TEXT CHECK(rol IN ('mype', 'cliente', 'admin')) DEFAULT 'cliente',
            barrio_id INTEGER REFERENCES maestro_barrios(id),
            estado TEXT DEFAULT 'activo',
            latitud DOUBLE PRECISION, 
            longitud DOUBLE PRECISION,
            fecha_registro TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
    ''')

    # 4. TABLA: Perfil MYPE
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS perfiles_mype (
            id SERIAL PRIMARY KEY,
            usuario_id INTEGER REFERENCES usuarios(id),
            nombre_comercial TEXT,
            descripcion TEXT,
            categoria_id INTEGER REFERENCES maestro_categorias(id)
        )
    ''')

    # 5. TABLA: Productos
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS productos (
            id SERIAL PRIMARY KEY,
            mype_id INTEGER REFERENCES perfiles_mype(id),
            nombre TEXT NOT NULL,
            descripcion TEXT,
            precio DOUBLE PRECISION NOT NULL,
            foto_url TEXT,
            fecha_creacion TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
    ''')

    # 6. TABLA: Mensajes (Chat)
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS mensajes (
            id SERIAL PRIMARY KEY,
            emisor_id INTEGER REFERENCES usuarios(id),
            receptor_id INTEGER REFERENCES usuarios(id),
            contenido TEXT NOT NULL,
            fecha TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
    ''')

    conn.commit()
    cursor.close()
    conn.close() # CERRAMOS para asegurar que Postgres guarde los cambios

    # --- FASE 2: POBLACIÓN DE DATOS ---
    # Abrimos una conexión NUEVA para que ya "vea" las tablas creadas
    conn = get_db_connection() #[cite: 16]
    cursor = conn.cursor()
    
    categorias = [('Alimentos',), ('Ropa y Calzado',), ('Servicios Técnicos',), ('Hogar',), ('Salud',)]
    cursor.executemany('''
        INSERT INTO maestro_categorias (nombre) VALUES (%s) 
        ON CONFLICT (nombre) DO NOTHING
    ''', categorias)

    # Precarga de datos con ON CONFLICT para PostgreSQL
    barrios = [('Sector Norte',), ('Sector Sur',), ('Centro Histórico',)]
    cursor.executemany('''
        INSERT INTO maestro_barrios (nombre) VALUES (%s) 
        ON CONFLICT (nombre) DO NOTHING
    ''', barrios)
    
    conn.commit()
    cursor.close()
    conn.close()
    print("✅ PostgreSQL inicializado y poblado con éxito.")

if __name__ == "__main__":
    init_db()