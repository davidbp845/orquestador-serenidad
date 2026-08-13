"""No golpea la red ni descarga modelos de embeddings reales: se
mockean chromadb.PersistentClient y la función de embeddings, ya que
lo único que le corresponde probar a este adaptador es que traduce
correctamente el puerto RepositorioConocimiento a llamadas de
chromadb."""
from unittest.mock import MagicMock, patch

from adapters.out.vector_store import (
    MODELO_EMBEDDINGS_POR_DEFECTO,
    RepositorioConocimientoChroma,
)


def _construir_con_mocks(ruta_datos="./chroma_test", **kwargs):
    with patch("adapters.out.vector_store.chromadb.PersistentClient") as mock_client_cls, \
         patch("adapters.out.vector_store.embedding_functions.SentenceTransformerEmbeddingFunction") as mock_embed_cls:
        mock_client = MagicMock()
        mock_coleccion = MagicMock()
        mock_client.get_or_create_collection.return_value = mock_coleccion
        mock_client_cls.return_value = mock_client

        repo = RepositorioConocimientoChroma(ruta_datos=ruta_datos, **kwargs)
        return repo, mock_client, mock_coleccion, mock_client_cls, mock_embed_cls


def test_inicializa_cliente_persistente_en_la_ruta_indicada():
    repo, mock_client, mock_coleccion, mock_client_cls, _ = _construir_con_mocks(
        ruta_datos="/tmp/chroma_test"
    )
    mock_client_cls.assert_called_once_with(path="/tmp/chroma_test")
    mock_client.get_or_create_collection.assert_called_once()
    _, kwargs = mock_client.get_or_create_collection.call_args
    assert kwargs["name"] == "conocimiento_negocio"


def test_usa_chroma_path_del_entorno_si_no_se_indica_ruta(monkeypatch):
    monkeypatch.setenv("CHROMA_PATH", "/env/chroma")
    with patch("adapters.out.vector_store.chromadb.PersistentClient") as mock_client_cls, \
         patch("adapters.out.vector_store.embedding_functions.SentenceTransformerEmbeddingFunction"):
        mock_client_cls.return_value.get_or_create_collection.return_value = MagicMock()
        RepositorioConocimientoChroma()
        mock_client_cls.assert_called_once_with(path="/env/chroma")


def test_usa_modelo_multilingue_por_defecto():
    _, _, _, _, mock_embed_cls = _construir_con_mocks()
    mock_embed_cls.assert_called_once_with(model_name=MODELO_EMBEDDINGS_POR_DEFECTO)


def test_usa_modelo_embeddings_del_entorno_si_se_indica(monkeypatch):
    monkeypatch.setenv("CHROMA_EMBEDDING_MODEL", "otro-modelo")
    _, _, _, _, mock_embed_cls = _construir_con_mocks()
    mock_embed_cls.assert_called_once_with(model_name="otro-modelo")


def test_usa_modelo_embeddings_explicito_si_se_indica():
    _, _, _, _, mock_embed_cls = _construir_con_mocks(modelo_embeddings="otro-modelo-2")
    mock_embed_cls.assert_called_once_with(model_name="otro-modelo-2")


def test_indexar_fragmentos_llama_a_upsert_con_ids_documentos_y_metadatos():
    repo, _, mock_coleccion, _, _ = _construir_con_mocks()

    repo.indexar_fragmentos([
        {"id": "f1", "texto": "contenido 1", "metadata": {"fuente": "a.md"}},
        {"id": "f2", "texto": "contenido 2"},
    ])

    mock_coleccion.upsert.assert_called_once_with(
        ids=["f1", "f2"],
        documents=["contenido 1", "contenido 2"],
        metadatas=[{"fuente": "a.md"}, {}],
    )


def test_indexar_fragmentos_lista_vacia_no_llama_a_upsert():
    repo, _, mock_coleccion, _, _ = _construir_con_mocks()

    repo.indexar_fragmentos([])

    mock_coleccion.upsert.assert_not_called()


def test_vaciar_borra_la_coleccion_y_la_recrea_vacia():
    repo, mock_client, mock_coleccion_original, _, _ = _construir_con_mocks()
    mock_coleccion_nueva = MagicMock()
    mock_client.get_or_create_collection.return_value = mock_coleccion_nueva

    repo.vaciar()

    mock_client.delete_collection.assert_called_once_with(name=mock_coleccion_original.name)
    assert mock_client.get_or_create_collection.call_count == 2  # al construir, y al vaciar

    # A partir de aquí, indexar_fragmentos() debe ir contra la colección
    # nueva, no contra la que se acaba de borrar.
    repo.indexar_fragmentos([{"id": "f1", "texto": "x", "metadata": {}}])
    mock_coleccion_nueva.upsert.assert_called_once()
    mock_coleccion_original.upsert.assert_not_called()


def test_buscar_devuelve_los_documentos_de_la_query():
    repo, _, mock_coleccion, _, _ = _construir_con_mocks()
    mock_coleccion.query.return_value = {"documents": [["frag1", "frag2"]]}

    resultado = repo.buscar("¿cuáles son los precios?", top_k=3)

    mock_coleccion.query.assert_called_once_with(
        query_texts=["¿cuáles son los precios?"], n_results=3
    )
    assert resultado == ["frag1", "frag2"]


def test_buscar_sin_documentos_devuelve_lista_vacia():
    repo, _, mock_coleccion, _, _ = _construir_con_mocks()
    mock_coleccion.query.return_value = {"documents": []}

    assert repo.buscar("consulta") == []


def test_buscar_con_fuentes_combina_documentos_y_metadatos():
    repo, _, mock_coleccion, _, _ = _construir_con_mocks()
    mock_coleccion.query.return_value = {
        "documents": [["frag1", "frag2"]],
        "metadatas": [[
            {"fuente": "a.md", "categoria": "servicios", "publicar_web": True},
            {"fuente": "b.md", "categoria": "faq", "publicar_web": False},
        ]],
    }

    resultado = repo.buscar_con_fuentes("¿cuáles son los precios?", top_k=3)

    mock_coleccion.query.assert_called_once_with(
        query_texts=["¿cuáles son los precios?"], n_results=3
    )
    assert resultado == [
        {"texto": "frag1", "fuente": "a.md", "categoria": "servicios", "publicar_web": True},
        {"texto": "frag2", "fuente": "b.md", "categoria": "faq", "publicar_web": False},
    ]


def test_buscar_con_fuentes_sin_resultados_devuelve_lista_vacia():
    repo, _, mock_coleccion, _, _ = _construir_con_mocks()
    mock_coleccion.query.return_value = {"documents": [], "metadatas": []}

    assert repo.buscar_con_fuentes("consulta") == []


def test_resumen_cuenta_fragmentos_por_fuente():
    repo, _, mock_coleccion, _, _ = _construir_con_mocks()
    mock_coleccion.get.return_value = {
        "metadatas": [
            {"fuente": "servicios.md", "categoria": "servicios"},
            {"fuente": "servicios.md", "categoria": "servicios"},
            {"fuente": "faq.md", "categoria": "faq"},
        ]
    }

    resultado = repo.resumen()

    mock_coleccion.get.assert_called_once_with(include=["metadatas"])
    assert resultado == {"total": 3, "por_fuente": {"servicios.md": 2, "faq.md": 1}}


def test_resumen_sin_fragmentos_indexados():
    repo, _, mock_coleccion, _, _ = _construir_con_mocks()
    mock_coleccion.get.return_value = {"metadatas": []}

    assert repo.resumen() == {"total": 0, "por_fuente": {}}


def test_resumen_metadata_sin_fuente_se_agrupa_aparte():
    repo, _, mock_coleccion, _, _ = _construir_con_mocks()
    mock_coleccion.get.return_value = {"metadatas": [{"categoria": "faq"}]}

    assert repo.resumen() == {"total": 1, "por_fuente": {"?": 1}}
