import json
import pandas as pd

with open("AQ_PM25.geojson") as f:
    data = json.load(f)

# Extraer propiedades
props = [f["properties"] for f in data["features"]]
df = pd.DataFrame(props)

total = len(df)
nulos = df["valor_interpolado"].isna().sum()

print(f"Total de polígonos: {total}")
print(f"Polígonos sin datos (NaN): {nulos} ({round(nulos/total*100, 2)}%)")