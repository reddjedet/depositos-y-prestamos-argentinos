import requests, pandas as pd, matplotlib.pyplot as plt
from datetime import date

# --- 1. CONFIGURACIÓN DE LA API DEL BCRA ---
B = "https://api.bcra.gob.ar/estadisticas/v4.0/monetarias"
# Función corta para consultar la API y devolver la respuesta como diccionario (JSON)
get = lambda u, **p: requests.get(u, params=p, timeout=60).json()

# --- 2. DESCARGAR EL CATÁLOGO DE VARIABLES ---
# El BCRA publica ~1.200 series. Las pedimos en 2 tandas de 1000 (paginación) y las unimos en una sola tabla
c = pd.concat([pd.DataFrame(get(B, limit=1000, offset=o).get("results", [])) for o in range(0, 2000, 1000)])
# Convertimos el último valor informado a número (los errores quedan como NaN)
c["v"] = pd.to_numeric(c.ultValorInformado, errors="coerce")

# --- 3. BUSCAR LAS SERIES CORRECTAS ---
# Como no sabemos el ID de cada serie, la buscamos por nombre, por unidad ("millones") y por
# rango de valores esperado (lo, hi). Devuelve el ID de la mejor coincidencia.
def pick(p, lo, hi):
    x = c[c.descripcion.str.contains(p, case=False)                               # el nombre contiene la palabra buscada
          & c.unidadExpresion.astype(str).str.contains("millones", case=False)    # está expresada en millones
          & c.v.between(lo, hi)].copy()                                           # su valor actual es razonable
    # Orden de preferencia: primero series diarias, luego "sector privado", luego descripciones cortas
    x["k"] = [(r.periodicidad != "D", "privado" not in r.descripcion.lower(), len(r.descripcion)) for r in x.itertuples()]
    x = x.sort_values("k")
    # Mostramos las 6 mejores candidatas para poder verificar que sea la correcta
    print(x[["idVariable", "periodicidad", "primerFechaInformada", "v", "descripcion"]].head(6).to_string())
    return int(x.idVariable.iloc[0])  # nos quedamos con la primera

# Diccionario {nombre del gráfico: ID de la serie}
IDS = {"Depósitos USD": pick("dep[óo]sito", 30000, 50000),
       "Préstamos USD": pick("pr[ée]stamo", 18000, 32000)}

# --- 4. DESCARGAR LA HISTORIA DE CADA SERIE ---
def f(i):
    r, o = [], 0
    while True:  # la API entrega máx. 3000 registros por pedido, así que pedimos de a tandas
        d = get(f"{B}/{i}", desde="2004-06-01", hasta=date.today(), limit=3000, offset=o)["results"][0]["detalle"]
        r += d; o += 3000
        if len(d) < 3000: break  # si vino una tanda incompleta, ya no hay más datos
    s = pd.DataFrame(r).set_index("fecha").valor   # tabla con la fecha como índice
    s.index = pd.to_datetime(s.index)               # texto -> fecha real
    # Ordenamos por fecha y calculamos el promedio de cada mes ("MS" = inicio de mes)
    return s.sort_index().resample("MS").mean()

# Unimos ambas series en una tabla: una columna por serie, una fila por mes
df = pd.concat({k: f(i) for k, i in IDS.items()}, axis=1)

# --- 5. AJUSTE POR INFLACIÓN DE EEUU ---
# Descargamos el índice de precios al consumidor (CPI) de EEUU desde FRED (Reserva Federal de St. Louis)
cpi = pd.read_csv("https://fred.stlouisfed.org/graph/fredgraph.csv?id=CPIAUCSL", index_col=0, parse_dates=True).iloc[:,0].dropna()
# Multiplicamos cada mes por (CPI actual / CPI de ese mes): expresa todo en dólares de hoy,
# así 100 USD de 2005 y de 2026 se pueden comparar sin que la inflación distorsione
df = df.mul(cpi.iloc[-1] / cpi.reindex(df.index, method="ffill"), axis=0)

# --- 6. GRÁFICO PRINCIPAL ---
ax = df.plot(figsize=(12, 5), grid=True, color=["#ed7d31", "#5b9bd5"], ylabel="Millones USD (reales)",
             title="Depósitos y préstamos en USD (promedio mensual, ajustado por inflación EEUU)")
# Sombreado rojo suave desde 2024 hasta hoy, para resaltar la etapa de recuperación
# Gobiernos: (nombre, inicio, fin, color). fin=None -> hasta hoy
gob = [("Kirchner",      "2003-05-25", "2007-12-10", "#2ca02c"),
       ("C. Fernández I", "2007-12-10", "2011-12-10", "#9467bd"),
       ("C. Fernández II","2011-12-10", "2015-12-10", "#c5b0d5"),
       ("Macri",         "2015-12-10", "2019-12-10", "#f2c200"),
       ("A. Fernández",  "2019-12-10", "2023-12-10", "#7f7f7f"),
       ("Milei",         "2023-12-10", None,         "red")]
for nombre, ini, fin, cl in gob:
    ini = max(pd.Timestamp(ini), df.index[0])                 # recorta Kirchner al inicio de los datos (2004-06)
    fin = pd.Timestamp(fin) if fin else df.index[-1]
    ax.axvspan(ini, fin, color=cl, alpha=.15)                 # recuadro de color
    ax.text(ini + (fin - ini) / 2, ax.get_ylim()[1] * .30, nombre,   # nombre centrado arriba
            ha="center", va="top", fontsize=8, fontweight="bold")

# --- 7. LÍNEAS PUNTEADAS DE PROMEDIO ---
# Cada promedio toma el color de su serie y aparece en la leyenda con su valor
col = dict(zip(df.columns, ["#ed7d31", "#5b9bd5"]))
for k in df:
    m = df[k].mean()
    ax.axhline(m, color=col[k], linestyle="--", linewidth=1.8, alpha=.7, label=f"Prom. {k}: {m:,.0f}")
ax.legend()

# --- 8. ETIQUETAS DE VALORES CLAVE ---
# Para cada serie rotulamos el máximo, el mínimo y el último valor
for k in df:
    for t in (df[k].idxmax(), df[k].idxmin(), df.index[-1]):
        ax.annotate(f"{df[k][t]:,.0f}", (t, df[k][t]), ha="center", va="bottom")

plt.show()  # mostrar el gráfico
