from datetime import datetime, timezone
import json
import os
from pathlib import Path

import geopandas as gpd
import numpy as np
import pandas as pd
import requests
from scipy.spatial import Delaunay
from shapely.geometry import Point, mapping


BASE_DIR = Path(__file__).resolve().parent


def cargar_env(ruta_env):
    if not ruta_env.exists():
        return
    for linea in ruta_env.read_text(encoding="utf-8-sig").splitlines():
        linea = linea.strip()
        if not linea or linea.startswith("#") or "=" not in linea:
            continue
        clave, valor = linea.split("=", 1)
        os.environ.setdefault(clave.strip(), valor.strip().strip('"').strip("'"))


cargar_env(BASE_DIR / ".env")

API_KEY = os.getenv("API_KEY_PURPLEAIR")
CSV_FILE = BASE_DIR / "sensores_detectados.csv"
CSV_CENSO_INEGI = BASE_DIR / "cpv2020.csv"
SALIDA_GEOJSON_SENSORES = BASE_DIR / "sensores.geojson"
SALIDA_GEOJSON_COLONIAS_PM25 = BASE_DIR / "AQ_PM25_v2.geojson"
SALIDA_GEOJSON_COLONIAS_PM10 = BASE_DIR / "AQ_PM10.geojson"
ARCHIVO_SHP_COLONIAS = BASE_DIR / "shp" / "2025_1_19_A.shp"
CAMPOS = "pm1.0,pm2.5,pm10.0"

MIN_PM = 0.0
MAX_PM25 = 500.4
MAX_PM10 = 604.0

# ---------------------------------------------------------------------------
# Histórico: se activa automáticamente en GitHub Actions (GITHUB_ACTIONS=true)
# o manualmente con la variable de entorno GUARDAR_HISTORICO=1
# ---------------------------------------------------------------------------
DIR_HISTORICO = BASE_DIR / "historico"
EN_GITHUB_ACTIONS = os.getenv("GITHUB_ACTIONS", "").lower() == "true"
GUARDAR_HISTORICO = EN_GITHUB_ACTIONS or os.getenv("GUARDAR_HISTORICO", "").lower() in (
    "1", "true", "si", "sí"
)

COLUMNAS_HIST_SENSORES = ["sensor_index", "name", "timestamp", "pm1_0", "pm2_5", "pm10_0"]
COLUMNAS_HIST_INTERPOLACION = [
    "timestamp", "cvegeo",
    "pm25_interpolado", "calidad_pm25",
    "pm10_interpolado", "calidad_pm10",
    "metodo", "n_sensores",
    "poblacion_total", "ninos_0a5", "adultos_mayores", "personas_discapacidad",
]


def cargar_datos_censales(ruta_csv):
    """Carga y procesa los indicadores sociodemográficos del censo INEGI por AGEB."""
    if not os.path.exists(ruta_csv):
        print(f"Advertencia: No se encontró el archivo censal en {ruta_csv}")
        return pd.DataFrame()

    df = pd.read_csv(
        ruta_csv,
        dtype={'ENTIDAD': str, 'MUN': str, 'LOC': str, 'AGEB': str, 'MZA': str}
    )

    if 'MZA' in df.columns:
        df = df[df['MZA'] == '000'].copy()

    df = df[df['AGEB'] != '0000'].copy()

    df['CVEGEO_CENSO'] = (
        df['ENTIDAD'].str.zfill(2) +
        df['MUN'].str.zfill(3) +
        df['LOC'].str.zfill(4) +
        df['AGEB'].str.zfill(4)
    )

    columnas_interes = ['POBTOT', 'P_0A2', 'P_3A5', 'P_60YMAS', 'PCON_DISC']
    for col in columnas_interes:
        if col in df.columns:
            df[col] = pd.to_numeric(df[col], errors='coerce').fillna(0).astype(int)
        else:
            df[col] = 0

    df['NIÑOS_0A5'] = df['P_0A2'] + df['P_3A5']

    df.rename(columns={
        'POBTOT': 'POBLACION_TOTAL',
        'P_60YMAS': 'ADULTOS_MAYORES',
        'PCON_DISC': 'PERSONAS_DISCAPACIDAD'
    }, inplace=True)

    cols_exportar = ['CVEGEO_CENSO', 'POBLACION_TOTAL', 'NIÑOS_0A5', 'ADULTOS_MAYORES', 'PERSONAS_DISCAPACIDAD']
    return df[cols_exportar]


def leer_csv(ruta):
    df = pd.read_csv(ruta)
    df = df.dropna(subset=["latitude", "longitude", "sensor_index"])
    df["sensor_index"] = df["sensor_index"].astype(int)
    return df


def consultar_sensor(sensor_index):
    """Devuelve (pm1.0, pm2.5, pm10.0) del sensor, o (None, None, None) si falla."""
    if not API_KEY:
        raise RuntimeError("Falta API_KEY_PURPLEAIR en .env o en las variables de entorno")

    url = f"https://api.purpleair.com/v1/sensors/{sensor_index}?fields={CAMPOS}"
    try:
        respuesta = requests.get(url, headers={"X-API-Key": API_KEY}, timeout=15)
        respuesta.raise_for_status()
        sensor = respuesta.json().get("sensor", {})
        return sensor.get("pm1.0"), sensor.get("pm2.5"), sensor.get("pm10.0")
    except requests.RequestException as error:
        print(f"No se pudo consultar {sensor_index}: {error}")
        return None, None, None


def clasificar_calidad_aire_pm25(valor):
    if valor is None or (isinstance(valor, float) and np.isnan(valor)):
        return "Sin datos"
    if valor <= 15:
        return "Bueno"
    if valor <= 33:
        return "Aceptable"
    if valor <= 79:
        return "Mala"
    if valor <= 130:
        return "Muy alta"
    return "Extremadamente mala"


def clasificar_calidad_aire_pm10(valor):
    if valor is None or (isinstance(valor, float) and np.isnan(valor)):
        return "Sin datos"
    if valor <= 45:
        return "Bueno"
    if valor <= 60:
        return "Aceptable"
    if valor <= 132:
        return "Mala"
    if valor <= 213:
        return "Muy alta"
    return "Extremadamente mala"


def lecturas_validas(sensor_id, pm10, pm25):
    try:
        pm10, pm25 = float(pm10), float(pm25)
    except (TypeError, ValueError):
        print(f"Sensor {sensor_id} descartado: lectura no numérica.")
        return None

    if not np.isfinite(pm10) or not np.isfinite(pm25):
        print(f"Sensor {sensor_id} descartado: lectura no finita.")
        return None

    if not (MIN_PM <= pm10 <= MAX_PM10 and MIN_PM <= pm25 <= MAX_PM25):
        print(
            f"Sensor {sensor_id} descartado por valor fuera de rango: "
            f"PM10={pm10}, PM2.5={pm25}"
        )
        return None

    return pm10, pm25


# ---------------------------------------------------------------------------
# Utilidades de histórico
# ---------------------------------------------------------------------------
def anexar_csv(df, ruta):
    """Agrega filas al final del CSV sin releerlo ni sobrescribirlo."""
    if df.empty:
        return
    ruta.parent.mkdir(parents=True, exist_ok=True)
    escribir_header = not ruta.exists() or ruta.stat().st_size == 0
    df.to_csv(ruta, mode="a", header=escribir_header, index=False, encoding="utf-8")


def _json_default(obj):
    if hasattr(obj, "item"):  # tipos numpy
        return obj.item()
    return str(obj)


def escribir_json_atomico(ruta, data):
    """Escribe en un temporal y lo reemplaza, para no dejar archivos a medias."""
    ruta.parent.mkdir(parents=True, exist_ok=True)
    tmp = ruta.with_suffix(ruta.suffix + ".tmp")
    with open(tmp, "w", encoding="utf-8") as archivo:
        json.dump(data, archivo, ensure_ascii=False, separators=(",", ":"),
                  allow_nan=False, default=_json_default)
    tmp.replace(ruta)


def crear_geojson(df, timestamp):
    features, puntos, valores_pm25, valores_pm10, historico = [], [], [], [], []

    for _, fila in df.iterrows():
        sensor_id = int(fila["sensor_index"])
        pm1, pm25, pm10 = consultar_sensor(sensor_id)
        if pm10 is None or pm25 is None:
            continue

        valores = lecturas_validas(sensor_id, pm10, pm25)
        if valores is None:
            continue
        pm10, pm25 = valores

        coordenadas = [float(fila["longitude"]), float(fila["latitude"])]
        nombre = fila.get("name", "")
        pm1 = float(pm1) if pm1 is not None else None
        features.append({
            "type": "Feature",
            "geometry": {"type": "Point", "coordinates": coordenadas},
            "properties": {
                "sensor_index": sensor_id,
                "name": nombre,
                "pm1_0": pm1,
                "pm2_5": pm25,
                "pm10_0": pm10,
                "AQ PM 2.5": clasificar_calidad_aire_pm25(pm25),
                "AQ PM 10": clasificar_calidad_aire_pm10(pm10),
                "timestamp": timestamp,
            },
        })
        puntos.append(coordenadas)
        valores_pm25.append(pm25)
        valores_pm10.append(pm10)
        historico.append({
            "sensor_index": sensor_id, "name": nombre, "timestamp": timestamp,
            "pm1_0": pm1, "pm2_5": pm25, "pm10_0": pm10,
        })

    with open(SALIDA_GEOJSON_SENSORES, "w", encoding="utf-8") as archivo:
        json.dump({"type": "FeatureCollection", "features": features}, archivo,
                  ensure_ascii=False, indent=2)
    print(f"GeoJSON de sensores generado ({len(features)} entidades): {SALIDA_GEOJSON_SENSORES}")

    # Histórico crudo de sensores: un CSV por mes (historico/sensores_YYYY-MM.csv)
    if GUARDAR_HISTORICO and historico:
        ruta = DIR_HISTORICO / f"sensores_{timestamp[:7]}.csv"
        anexar_csv(pd.DataFrame(historico, columns=COLUMNAS_HIST_SENSORES), ruta)
        print(f"Histórico de sensores actualizado: {ruta}")

    return np.array(puntos), np.array(valores_pm25), np.array(valores_pm10)


def cargar_datos_colonias_shp(archivo_shp, df_censo):
    """Lee el SHP de AGEBs, lo une con la información censal de INEGI y proyecta a WGS84."""
    gdf = gpd.read_file(archivo_shp)
    if gdf.crs is None:
        raise ValueError("El SHP no tiene CRS definido en su archivo .prj.")

    gdf = gdf.to_crs("EPSG:4326")

    posibles_llaves = ['CVEGEO', 'CVE_AGEB', 'CODIGO']
    col_cve = next((col for col in posibles_llaves if col in gdf.columns), gdf.columns[0])
    gdf['CVEGEO_SHP'] = gdf[col_cve].astype(str).str.zfill(13)

    if not df_censo.empty:
        gdf = gdf.merge(
            df_censo,
            left_on='CVEGEO_SHP',
            right_on='CVEGEO_CENSO',
            how='left'
        )

    elementos = []
    for _, fila in gdf.iterrows():
        if fila.geometry is not None and not fila.geometry.is_empty:
            elementos.append({
                "cvegeo": str(fila['CVEGEO_SHP']),
                "poblacion_total": int(fila.get("POBLACION_TOTAL", 0)) if pd.notnull(fila.get("POBLACION_TOTAL")) else 0,
                "niños_0a5": int(fila.get("NIÑOS_0A5", 0)) if pd.notnull(fila.get("NIÑOS_0A5")) else 0,
                "adultos_mayores": int(fila.get("ADULTOS_MAYORES", 0)) if pd.notnull(fila.get("ADULTOS_MAYORES")) else 0,
                "personas_discapacidad": int(fila.get("PERSONAS_DISCAPACIDAD", 0)) if pd.notnull(fila.get("PERSONAS_DISCAPACIDAD")) else 0,
                "geometry": fila.geometry
            })

    return elementos


def interpolar_lineal(punto, triangulo_indices, puntos, valores):
    v0, v1, v2 = puntos[triangulo_indices]
    z0, z1, z2 = valores[triangulo_indices]
    try:
        pesos = np.linalg.solve(
            np.array([v1 - v0, v2 - v0]).T,
            punto - v0,
        )
        return (1 - pesos[0] - pesos[1]) * z0 + pesos[0] * z1 + pesos[1] * z2
    except np.linalg.LinAlgError:
        return None


def generar_geojson_colonias(nombre_archivo, colonias_data, puntos_data,
                             valores_puntos, contaminante, timestamp):
    """Genera el GeoJSON de la capa actual y devuelve un DataFrame con el valor
    interpolado por AGEB (columnas: cvegeo, valor, calidad, metodo, n_sensores)."""
    try:
        triangulacion = Delaunay(puntos_data)
    except Exception as error:
        print(f"Error Delaunay: {error}")
        triangulacion = None

    features = []
    registros = []
    for colonia in colonias_data:
        geom = colonia["geometry"]
        valores_en_colonia = [
            valores_puntos[i] for i, (lon, lat) in enumerate(puntos_data)
            if geom.contains(Point(lon, lat))
        ]
        if valores_en_colonia:
            valor = float(np.mean(valores_en_colonia))
            metodo = "promedio_sensores"
        elif triangulacion is None:
            valor = None
            metodo = "sin_datos"
        else:
            centroide = geom.centroid
            punto = np.array([centroide.x, centroide.y])
            indice = triangulacion.find_simplex(punto)
            valor = (interpolar_lineal(punto, triangulacion.simplices[indice],
                                       puntos_data, valores_puntos)
                     if indice != -1 else None)
            metodo = "interpolacion_delaunay"

        valor = round(float(valor), 2) if valor is not None and np.isfinite(valor) else None
        if valor is None:
            metodo = "sin_datos"

        calidad = (
            clasificar_calidad_aire_pm25(valor)
            if contaminante == "pm2_5"
            else clasificar_calidad_aire_pm10(valor)
        )

        # PROPIEDADES CON FORMATO DE ETIQUETAS DESCRIPTIVAS Y ESPACIO INICIAL PARA PREVALECER EN VISORES
        features.append({
            "type": "Feature",
            "geometry": mapping(geom),
            "properties": {
                " Valor Interpolado": valor,
                " Calidad del Aire": calidad,
                "Población Total": colonia["poblacion_total"],
                "Niños de 0 a 5 años": colonia["niños_0a5"],
                "Mayores de 60 años": colonia["adultos_mayores"],
                "Personas con Discapacidad": colonia["personas_discapacidad"],
                "Clave Geográfica (CVEGEO)": colonia["cvegeo"],
                "Fecha de Actualización": timestamp,
            },
        })
        registros.append({
            "cvegeo": colonia["cvegeo"],
            "valor": valor,
            "calidad": calidad,
            "metodo": metodo,
            "n_sensores": len(valores_en_colonia),
        })

    with open(nombre_archivo, "w", encoding="utf-8") as archivo:
        json.dump({"type": "FeatureCollection", "features": features}, archivo,
                  ensure_ascii=False, indent=2, allow_nan=False)
    print(f"GeoJSON reproyectado generado ({len(features)} entidades): {nombre_archivo}")

    return pd.DataFrame(registros, columns=["cvegeo", "valor", "calidad", "metodo", "n_sensores"])


# ---------------------------------------------------------------------------
# Histórico de interpolación por AGEB (CSV + GeoJSON)
# ---------------------------------------------------------------------------
def construir_tabla_historica(colonias, df25, df10, timestamp):
    """Une PM2.5 y PM10 por AGEB junto con los datos censales de cada una."""
    base = pd.DataFrame([
        {
            "cvegeo": c["cvegeo"],
            "poblacion_total": c["poblacion_total"],
            "ninos_0a5": c["niños_0a5"],
            "adultos_mayores": c["adultos_mayores"],
            "personas_discapacidad": c["personas_discapacidad"],
        }
        for c in colonias
    ]).drop_duplicates(subset="cvegeo")

    t25 = df25.rename(columns={"valor": "pm25_interpolado", "calidad": "calidad_pm25"})
    t10 = df10[["cvegeo", "valor", "calidad"]].rename(
        columns={"valor": "pm10_interpolado", "calidad": "calidad_pm10"}
    )

    tabla = (
        base.merge(t25.drop_duplicates(subset="cvegeo"), on="cvegeo", how="left")
            .merge(t10.drop_duplicates(subset="cvegeo"), on="cvegeo", how="left")
    )
    tabla.insert(0, "timestamp", timestamp)
    tabla = tabla.dropna(subset=["pm25_interpolado", "pm10_interpolado"], how="all")
    return tabla[COLUMNAS_HIST_INTERPOLACION].reset_index(drop=True)


def actualizar_geojson_historico(colonias, tabla, timestamp):
    """Mantiene un GeoJSON por día: cada AGEB aparece una sola vez (geometría + datos
    censales) y acumula sus lecturas en la propiedad 'historial'."""
    ruta = DIR_HISTORICO / f"AQ_historico_{timestamp[:10]}.geojson"
    por_cvegeo = {}

    if ruta.exists():
        try:
            with open(ruta, encoding="utf-8") as archivo:
                datos = json.load(archivo)
            por_cvegeo = {f["properties"]["cvegeo"]: f for f in datos["features"]}
        except (OSError, ValueError, KeyError, TypeError) as error:
            respaldo = ruta.with_name(ruta.stem + f".corrupto_{int(datetime.now().timestamp())}.geojson")
            ruta.replace(respaldo)
            print(f"Histórico GeoJSON ilegible ({error}); se respaldó en {respaldo.name}")
            por_cvegeo = {}

    colonias_por_cve = {c["cvegeo"]: c for c in colonias}
    tabla_json = tabla.astype(object).where(tabla.notna(), None)

    for fila in tabla_json.to_dict("records"):
        cve = fila["cvegeo"]
        colonia = colonias_por_cve.get(cve)
        if colonia is None:
            continue

        feature = por_cvegeo.get(cve)
        if feature is None:
            feature = {
                "type": "Feature",
                "geometry": mapping(colonia["geometry"]),
                "properties": {"cvegeo": cve, "historial": []},
            }
            por_cvegeo[cve] = feature

        props = feature["properties"]
        props.update({
            "poblacion_total": fila["poblacion_total"],
            "ninos_0a5": fila["ninos_0a5"],
            "adultos_mayores": fila["adultos_mayores"],
            "personas_discapacidad": fila["personas_discapacidad"],
        })

        historial = props["historial"]
        if historial and historial[-1].get("timestamp") == timestamp:
            continue  # evita duplicar si se reejecuta con el mismo timestamp
        historial.append({
            "timestamp": timestamp,
            "pm25": fila["pm25_interpolado"],
            "calidad_pm25": fila["calidad_pm25"],
            "pm10": fila["pm10_interpolado"],
            "calidad_pm10": fila["calidad_pm10"],
            "metodo": fila["metodo"],
            "n_sensores": fila["n_sensores"],
        })

    escribir_json_atomico(ruta, {"type": "FeatureCollection", "features": list(por_cvegeo.values())})
    print(f"Histórico GeoJSON actualizado ({len(por_cvegeo)} AGEB): {ruta}")


def guardar_historico_interpolacion(colonias, df25, df10, timestamp):
    tabla = construir_tabla_historica(colonias, df25, df10, timestamp)
    if tabla.empty:
        print("Sin valores interpolados que guardar en el histórico.")
        return

    ruta_csv = DIR_HISTORICO / f"interpolacion_{timestamp[:10]}.csv"
    anexar_csv(tabla, ruta_csv)
    print(f"Histórico CSV actualizado (+{len(tabla)} filas): {ruta_csv}")

    actualizar_geojson_historico(colonias, tabla, timestamp)


if __name__ == "__main__":
    ejecucion = datetime.now(timezone.utc).isoformat()
    print(f"Histórico {'ACTIVADO' if GUARDAR_HISTORICO else 'desactivado'} "
          f"(GitHub Actions: {EN_GITHUB_ACTIONS})")

    # 1. Cargar censos antes de construir capas espaciales
    df_censo = cargar_datos_censales(CSV_CENSO_INEGI)

    # 2. Consultar sensores
    sensores = leer_csv(CSV_FILE)
    puntos, pm25, pm10 = crear_geojson(sensores, ejecucion)

    # 3. Interpolar y generar archivos unificados
    if len(puntos) >= 3 and os.path.exists(ARCHIVO_SHP_COLONIAS):
        colonias = cargar_datos_colonias_shp(ARCHIVO_SHP_COLONIAS, df_censo)
        df25 = generar_geojson_colonias(SALIDA_GEOJSON_COLONIAS_PM25, colonias, puntos,
                                        pm25, "pm2_5", ejecucion)
        df10 = generar_geojson_colonias(SALIDA_GEOJSON_COLONIAS_PM10, colonias, puntos,
                                        pm10, "pm10", ejecucion)

        # 4. Histórico de interpolación (CSV + GeoJSON) por AGEB
        if GUARDAR_HISTORICO:
            guardar_historico_interpolacion(colonias, df25, df10, ejecucion)
    else:
        print("No se generaron capas de colonias: faltan sensores o el SHP.")

    print("Proceso completado.")