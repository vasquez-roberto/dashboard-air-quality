import csv
import os
from pathlib import Path

import requests


def cargar_env(ruta_env):
    if not ruta_env.exists():
        return
    for linea in ruta_env.read_text(encoding="utf-8-sig").splitlines():
        linea = linea.strip()
        if not linea or linea.startswith("#") or "=" not in linea:
            continue
        clave, valor = linea.split("=", 1)
        os.environ.setdefault(clave.strip(), valor.strip().strip('"').strip("'"))


cargar_env(Path(__file__).resolve().with_name(".env"))

API_KEY = os.getenv("API_KEY_PURPLEAIR")
OUTPUT_CSV = "sensores_detectados.csv"

params = {
    "fields": "sensor_index,name,latitude,longitude,model,hardware,location_type",
    "nwlat": 25.78,
    "nwlng": -100.40,
    "selat": 25.60,
    "selng": -100.10,
}


def obtener_sensores():
    if not API_KEY:
        raise RuntimeError("Falta API_KEY_PURPLEAIR en .env")

    respuesta = requests.get(
        "https://api.purpleair.com/v1/sensors",
        headers={"X-API-Key": API_KEY},
        params=params,
        timeout=30,
    )
    respuesta.raise_for_status()

    resultado = respuesta.json()
    campos = resultado["fields"]
    return [dict(zip(campos, fila)) for fila in resultado["data"]]


def guardar_csv(sensores):
    if not sensores:
        print("No se encontraron sensores.")
        return
    with open(OUTPUT_CSV, "w", newline="", encoding="utf-8") as archivo:
        escritor = csv.DictWriter(archivo, fieldnames=sensores[0].keys())
        escritor.writeheader()
        escritor.writerows(sensores)
    print(f"{len(sensores)} sensores guardados en {OUTPUT_CSV}")


if __name__ == "__main__":
    guardar_csv(obtener_sensores())
