"""Configuración compartida por módulos del backend."""

import os

from dotenv import load_dotenv

load_dotenv()

DB_PATH = os.getenv("DB_PATH", "../data/encuesta_multianual.duckdb")
STATIC_DIR = os.getenv("STATIC_DIR", "../frontend/dist")
ENVIRONMENT = os.getenv("ENVIRONMENT", "development")

KNOWN_FEATURES = ["olas_2016_2019"]

FEATURES = frozenset(
    f.strip() for f in os.getenv("FEATURES", "").split(",") if f.strip()
)


def feature(name: str) -> bool:
    if name not in KNOWN_FEATURES:
        raise KeyError(f"Feature flag desconocido: {name}")
    return name in FEATURES
