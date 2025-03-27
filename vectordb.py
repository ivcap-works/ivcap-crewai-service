from typing import Optional
from embedchain.factory import VectorDBFactory
from pydantic import BaseModel
import chromadb

from chromadb.api.client import Client
from chromadb.config import Settings
from embedchain.vectordb.chroma import ChromaDB, ChromaDbConfig


def wrap_client_init(func):
    def wrapper(self, settings: Settings, **kwargs):
        settings.is_persistent = False
        return func(self, settings=settings, **kwargs)
    return wrapper
Client.__init__ = wrap_client_init(Client.__init__)

def create_chroma_db() -> ChromaDB:
    db = ChromaDB(config=ChromaDbConfig(chroma_settings={"is_persistent": False}))
    return db

def create_vectordb_config() -> dict:
    db = create_chroma_db()
    config = {
        "vectordb": {
            "provider": "chroma",
            "config": {
                "db": db
            }
        }
    }
    return config


class ChromaDbProxyConfig():
    def __init__(self, db: chromadb.ClientAPI):
        self._db = db

    @property
    def db(self):
        return self._db

class ChromaDbProxy():
    def __init__(self, config: Optional[ChromaDbProxyConfig] = None):
        self._obj = config.db

    def __getattr__(self, name):
        return getattr(self._obj, name)

    def __setattr__(self, name, value):
        if name == '_obj':
            super().__setattr__(name, value)  # Avoid recursion for _obj
        else:
            setattr(self._obj, name, value)

def get_full_class_name(obj):
    if isinstance(obj, type):
        class_obj = obj
    else:
        class_obj = obj.__class__
    return f"{class_obj.__module__}.{class_obj.__name__}"

# wrap the default chromadb settings
VectorDBFactory.provider_to_class["chroma"] = get_full_class_name(ChromaDbProxy)
VectorDBFactory.provider_to_config_class["chroma"] = get_full_class_name(ChromaDbProxyConfig)