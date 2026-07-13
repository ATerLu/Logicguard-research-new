"""Build a document-entity graph for lightweight GraphRAG retrieval."""

from __future__ import annotations

from collections import defaultdict
from collections.abc import Iterable

import networkx as nx

from logicguard.data.schemas import CorpusDocument
from logicguard.graph.entities import RuleBasedEntityExtractor
from logicguard.graph.schemas import DocumentEntities, GraphIndex


def build_document_entity_graph(
    documents: Iterable[CorpusDocument],
    extractor: RuleBasedEntityExtractor,
) -> GraphIndex:
    """Build a bipartite graph connecting documents to extracted entities.

    Node ids are namespaced (`doc:<id>`, `ent:<normalized>`) so later modules can
    inspect paths without guessing node types. Edges currently mean "entity text
    appeared in document title or body"; later phases can add edge weights,
    sentence offsets, source trust, or poisoning labels.
    """

    graph = nx.Graph()
    document_lookup: dict[str, CorpusDocument] = {}
    document_entities: dict[str, DocumentEntities] = {}
    entity_to_docs: dict[str, set[str]] = defaultdict(set)

    for document in documents:
        document_lookup[document.doc_id] = document
        doc_node = _doc_node(document.doc_id)
        graph.add_node(doc_node, node_type="document", doc_id=document.doc_id, title=document.title)

        # Include title and text because dataset titles often contain the most
        # precise entity string for multi-hop QA support documents.
        extraction_text = f"{document.title}. {document.text}"
        entities = extractor.extract(extraction_text)
        document_entities[document.doc_id] = DocumentEntities(
            doc_id=document.doc_id,
            title=document.title,
            entities=entities,
        )

        for entity in entities:
            ent_node = _entity_node(entity.normalized)
            graph.add_node(
                ent_node,
                node_type="entity",
                normalized=entity.normalized,
                surface=entity.text,
            )
            graph.add_edge(doc_node, ent_node, edge_type="mentions")
            entity_to_docs[entity.normalized].add(document.doc_id)

    return GraphIndex(
        graph=graph,
        documents=document_lookup,
        document_entities=document_entities,
        entity_to_docs=dict(entity_to_docs),
    )


def _doc_node(doc_id: str) -> str:
    return f"doc:{doc_id}"


def _entity_node(normalized_entity: str) -> str:
    return f"ent:{normalized_entity}"
