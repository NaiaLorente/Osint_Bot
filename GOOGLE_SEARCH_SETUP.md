# Configuración de Google Search API

Para obtener los mismos resultados que Google, configura las credenciales de Google Custom Search API:

1. Ve a [Google Cloud Console](https://console.cloud.google.com/)
2. Crea un proyecto o selecciona uno existente
3. Habilita la API "Custom Search JSON API"
4. Crea una API Key en "Credenciales"
5. Ve a [Google Custom Search Engine](https://cse.google.com/cse/)
6. Crea un nuevo motor de búsqueda (elige "Buscar en toda la web")
7. Obtén el "Search Engine ID" (cx)
8. Añade al .env:
   ```
   GOOGLE_SEARCH_API_KEY=tu_api_key_aqui
   GOOGLE_SEARCH_ENGINE_ID=tu_search_engine_id_aqui
   ```

Sin estas credenciales, el bot usa DuckDuckGo como fallback, que puede dar resultados diferentes.