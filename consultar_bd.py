import sqlite3

def consultar_bd():
    # 1. Conexión a la base de datos
    conexion = sqlite3.connect("marketplace.db")
    cursor = conexion.cursor()

    try:
        # 2. Ejecutar la consulta SELECT
        # Seleccionamos las columnas específicas que queremos ver
        cursor.execute("SELECT usuario_id, nombre_comercial, barrio_id, categoria_id FROM perfiles_mype")
        
        # 3. Obtener todos los resultados (fetchall devuelve una lista de tuplas)
        perfiles_mype = cursor.fetchall()

        print(f"{'ID':<5} | {'NOMBRE':<15} | {'BARRIO':<20} | {'CATEGORIA':<25}")
        print("-" * 80)

        for pro in perfiles_mype:
            # user[0] es ID, user[1] es Nombre, etc.
            print(f"{pro[0]:<5} | {pro[1]:<15} | {pro[2]:<20} | {pro[3]:<25}...") 
            # Nota: Usamos [:20] para no llenar la pantalla con el hash completo

    except sqlite3.Error as e:
        print(f"Error al consultar: {e}")
    
    finally:
        # 4. Cerrar conexión
        conexion.close()

if __name__ == "__main__":
    consultar_bd()