# Barómetro 2026 | AMX LATAM — Dashboard General

Dashboard de resultados generales del Barómetro 2026, conectado en vivo a un Google Sheet público.

## Ejecutar localmente

```bash
pip install -r requirements.txt
streamlit run dashboard.py
```

## Publicar en Streamlit Community Cloud

1. Subir este repo a GitHub (puede ser privado).
2. Ir a https://share.streamlit.io → New app → conectar el repo → main file: `dashboard.py`.
3. En **Settings → Secrets** del app, agregar:
   ```toml
   DASHBOARD_PASSWORD = "tu-contraseña-aquí"
   ```
   Sin este secreto configurado, el dashboard queda sin contraseña (útil para desarrollo local).

## Actualizar el análisis de comentarios

`data/comentarios_clasificados.json` es un análisis de sentimiento fijo, generado una vez por LLM
sobre el ciclo cerrado. Si se abre un nuevo ciclo de encuesta, hay que regenerar este archivo
(ver `exportar_comentarios.py` en el repositorio de origen) y reemplazarlo aquí.
