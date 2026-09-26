import os
import random
import threading
from dotenv import load_dotenv
from qdrant_client import QdrantClient, models

load_dotenv()

client = QdrantClient(url=os.getenv("QDRANT_URL"))
collection_name = os.getenv("COLLECTION_NAME")
model_name = os.getenv("EMBEDDING_MODEL")

# LangGraph runs section research agents concurrently, while QdrantClient's
# local FastEmbed model keeps a shared mutable batch accumulator. Serialize
# calls that perform local inference so concurrent agents cannot corrupt it.
_local_inference_lock = threading.Lock()

if not client.collection_exists(collection_name=collection_name):
    client.create_collection(
        collection_name=collection_name,
        vectors_config=models.VectorParams(size=384, distance=models.Distance.COSINE))

def retrieve_from_store(question: str, user_id:str, n_points: int = 3) -> str:
    with _local_inference_lock:
        results = client.query_points(
            collection_name=collection_name,
            query=models.Document(text=question, model=model_name),
            query_filter=models.Filter(
                must=[
                    models.FieldCondition(
                        key="group_id",
                        match=models.MatchValue(
                            value=user_id,
                        ),
                    )
                ]
            ),
            limit=n_points,
        )
    return results.points

def remove_data_from_store(user_id:str) -> str:
    client.delete(
        collection_name=collection_name,
        points_selector=models.FilterSelector(
            filter=models.Filter(
                must=[
                    models.FieldCondition(
                        key="group_id",
                        match=models.MatchValue(
                            value=user_id,
                        ),
                    )
                ]
            )
        )
    ) 

def rag_pipeline_setup(user_id, documents):
    with _local_inference_lock:
        client.upsert(
            collection_name=collection_name,
            points=[
                models.PointStruct(
                    id=idx,
                    vector=models.Document(text=document["page_content"], model=model_name),
                    payload={"group_id": user_id, "document": document},
                )
                for idx, document in enumerate(documents)
            ],
        )
