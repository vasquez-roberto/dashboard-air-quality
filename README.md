# Monitoreo de Calidad del Aire e Impacto Sociodemográfico

Este proyecto consulta en tiempo real las mediciones de sensores de calidad del aire (PurpleAir), realiza interpolación espacial (Delaunay/Triangulación lineal) hacia zonas censales (AGEBs/colonias) y enriquece las capas de salida con datos sociodemográficos del **Censo de Población y Vivienda 2020 (INEGI)**.

---

## Estructura de la Capa de Salida (`properties`)

Los archivos de salida (`AQ_PM25.geojson` y `AQ_PM10.geojson`) están estructurados con etiquetas legibles y formateadas para optimizar su visualización interactiva en GitHub, ArcGIS, QGIS u otros visores GeoJSON:

| Campo / Etiqueta en GeoJSON | Descripción | Origen del Dato |
| :--- | :--- | :--- |
| **` Valor Interpolado`** | Concentración estimada de PM2.5 o PM10 ($\mu g/m^3$). Contiene un espacio inicial para posicionarse en la parte superior del popup/visor. | Interpolación espacial de sensores en vivo |
| **` Calidad del Aire`** | Clasificación cualitativa (Bueno, Aceptable, Mala, Muy alta, Extremadamente mala). | Umbrales normativos según concentración |
| **`Población Total`** | Número total de personas en la zona censal. | Censo INEGI 2020 (`POBTOT`) |
| **`Niños de 0 a 5 años`** | Población de primera infancia vulnerable a partículas finas. | Censo INEGI 2020 (`P_0A2` + `P_3A5`) |
| **`Mayores de 60 años`** | Adultos mayores dentro del polígono. | Censo INEGI 2020 (`P_60YMAS`) |
| **`Personas con Discapacidad`** | Población con algún grado o tipo de discapacidad. | Censo INEGI 2020 (`PCON_DISC`) |
| **`Clave Geográfica (CVEGEO)`** | Identificador único estandarizado del INEGI a 13 dígitos. | Shapefile AGEBs / INEGI |
| **`Fecha de Actualización`** | Fecha y hora UTC en que se consultó el sensor y se ejecutó la interpolación. | Generado automáticamente en tiempo de ejecución |

---

## Funcionalidades del Script

1. **Lectura del Censo INEGI:** Carga y filtra los indicadores por nivel AGEB urbana eliminando registros municipales o no urbanos (`MZA == '000'`).
2. **Consulta API PurpleAir:** Descarga en vivo las métricas de `PM2.5` y `PM10`, descartando valores fuera de rango o sensores descalibrados.
3. **Interpolación Espacial:** 
   * Asigna el promedio directo si hay sensores dentro de la colonia/AGEB.
   * Aplica triangulación de Delaunay para estimar el valor en el centroide en zonas sin cobertura directa.
4. **Automatización:** Compatible con **GitHub Actions** para ejecución programada cada cierto tiempo.

---

## Archivos Requeridos

* `sensores_detectados.csv`: Archivo CSV con las coordenadas e IDs de los sensores PurpleAir.
* `cpv2020.csv`: Archivo con los datos censales por AGEB del INEGI.
* `shp/2025_1_19_A.shp`: Shapefile con los polígonos geográficos de las zonas.
* `.env`: Archivo de configuración con la clave de API (`API_KEY_PURPLEAIR`).
