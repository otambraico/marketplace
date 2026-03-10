import sqlite3

def consultar_usuarios():
    # 1. Conexión a la base de datos
    conexion = sqlite3.connect("marketplace.db")
    cursor = conexion.cursor()

    try:
        # 2. Ejecutar la consulta SELECT
        # Seleccionamos las columnas específicas que queremos ver
        cursor.execute("SELECT id, nombre, email, password, rol FROM usuarios")
        
        # 3. Obtener todos los resultados (fetchall devuelve una lista de tuplas)
        productos = cursor.fetchall()

        print(f"{'ID':<5} | {'NOMBRE':<15} | {'EMAIL':<20} | {'PASSWORD':<25} | {'ROl':<30}")
        print("-" * 80)

        for pro in productos:
            # user[0] es ID, user[1] es Nombre, etc.
            print(f"{pro[0]:<5} | {pro[1]:<15} | {pro[2]:<20} | {pro[3][:20]} | {pro[4]:<30}...") 
            # Nota: Usamos [:20] para no llenar la pantalla con el hash completo

    except sqlite3.Error as e:
        print(f"Error al consultar: {e}")
    
    finally:
        # 4. Cerrar conexión
        conexion.close()

if __name__ == "__main__":
    consultar_usuarios()