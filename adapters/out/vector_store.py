"""Implementación del puerto RepositorioConocimiento usando ChromaDB
como vector store local. Cambiar a Qdrant/Pinecone = otra clase con
el mismo puerto."""
from __future__ import annotations

import os
from collections import Counter

import chromadb
from chromadb.utils import embedding_functions

from domain.ports import RepositorioConocimiento

# DefaultEmbeddingFunction (all-MiniLM-L6-v2) está entrenado sobre
# todo en inglés: con contenido y queries en español el ranking
# semántico es pobre (comprobado: un fragmento con el precio exacto
# quedaba en el puesto 9 de 12 para la query "precios"). Este modelo
# multilingüe da resultados muchísimo mejores en español.
MODELO_EMBEDDINGS_POR_DEFECTO = "paraphrase-multilingual-MiniLM-L12-v2"


class RepositorioConocimientoChroma(RepositorioConocimiento):
    def __init__(
        self,
        ruta_datos: str | None = None,
        coleccion: str = "conocimiento_negocio",
        modelo_embeddings: str | None = None,
    ):
        ruta_datos = ruta_datos or os.environ.get("CHROMA_PATH", "./chroma_data")
        modelo_embeddings = modelo_embeddings or os.environ.get(
            "CHROMA_EMBEDDING_MODEL", MODELO_EMBEDDINGS_POR_DEFECTO
        )
        self._client = chromadb.PersistentClient(path=ruta_datos)
        self._embed_fn = embedding_functions.SentenceTransformerEmbeddingFunction(
            model_name=modelo_embeddings
        )
        self._coleccion = self._client.get_or_create_collection(
            name=coleccion, embedding_function=self._embed_fn
        )

    def indexar_fragmentos(self, fragmentos: list[dict]) -> None:
        """fragmentos: [{"id": str, "texto": str, "metadata": dict}, ...]"""
        if not fragmentos:
            return
        self._coleccion.upsert(
            ids=[f["id"] for f in fragmentos],
            documents=[f["texto"] for f in fragmentos],
            metadatas=[f.get("metadata", {}) for f in fragmentos],
        )

    def vaciar(self) -> None:
        """Borra todos los fragmentos indexados y recrea la colección
        vacía. indexar_fragmentos() usa upsert, así que nunca retira por
        sí solo los fragmentos de notas que ya no existen — esto es lo
        que hace falta para cambiar de vault de forma limpia (ver
        scripts/vaciar_chroma.py) en vez de mezclar el vault nuevo con
        restos del anterior."""
        nombre = self._coleccion.name
        self._client.delete_collection(name=nombre)
        self._coleccion = self._client.get_or_create_collection(
            name=nombre, embedding_function=self._embed_fn
        )

    def buscar(self, consulta: str, top_k: int = 5) -> list[str]:
        resultado = self._coleccion.query(query_texts=[consulta], n_results=top_k)
        documentos = resultado.get("documents", [[]])
        return documentos[0] if documentos else []

    def buscar_con_fuentes(self, consulta: str, top_k: int = 5) -> list[dict]:
        resultado = self._coleccion.query(query_texts=[consulta], n_results=top_k)
        documentos = (resultado.get("documents") or [[]])[0]
        metadatos = (resultado.get("metadatas") or [[]])[0]
        return [
            {"texto": doc, **(meta or {})}
            for doc, meta in zip(documentos, metadatos, strict=True)
        ]

    def resumen(self) -> dict:
        # Solo metadatos, sin documentos/embeddings — barato incluso con
        # un vault grande, no recalcula nada.
        metadatos = self._coleccion.get(include=["metadatas"]).get("metadatas") or []
        por_fuente = Counter(m.get("fuente", "?") for m in metadatos)
        return {"total": len(metadatos), "por_fuente": dict(por_fuente)}
