import json
import os

# Archivos GeoJSON que deseas inspeccionar
ARCHIVOS_A_REVISAR = [
    "sensores.geojson",
    "AQ_PM25.geojson",
    "AQ_PM10.geojson",
    "historico_combinado.geojson"
]

SENSOR_BUSCADO = 121825

def buscar_sensor_en_geojson(ruta_archivo, sensor_id):
    if not os.path.exists(ruta_archivo):
        print(f"❌ El archivo '{ruta_archivo}' no existe.")
        return

    print(f"\n--- Analizando: {ruta_archivo} ---")
    
    try:
        with open(ruta_archivo, "r", encoding="utf-8") as f:
            datos = json.load(f)
        
        features = datos.get("features", [])
        coincidencias = 0

        for idx, feature in enumerate(features):
            props = feature.get("properties", {})
            
            # Comprobar en 'sensor_index' o dentro de 'name' por si acaso
            s_index = props.get("sensor_index")
            nombre = str(props.get("name", ""))

            if s_index == sensor_id or str(sensor_id) in nombre:
                coincidencias += 1
                print(f"  ⚠️  ENCONTRADO en la feature #{idx}:")
                print(f"      Propiedades: {props}")

        if coincidencias == 0:
            print(f"  ✅ El sensor {sensor_id} NO está presente en este GeoJSON.")
        else:
            print(f"  🚨 Total de apariciones del sensor {sensor_id}: {coincidencias}")

    except Exception as e:
        print(f"  ❌ Error al leer el archivo: {e}")

if __name__ == "__main__":
    print(f"Iniciando búsqueda del sensor {SENSOR_BUSCADO}...")
    for archivo in ARCHIVOS_A_REVISAR:
        buscar_sensor_en_geojson(archivo, SENSOR_BUSCADO)