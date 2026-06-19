"""
Configuración de conexión y logging para el ETL fintech IBM Dataset.
Usa variables de entorno; con fallback a valores locales de desarrollo.
"""
import os
import logging
from dataclasses import dataclass, field
from typing import Optional


@dataclass
class DBConfig:
    host:     str = field(default_factory=lambda: os.getenv("DB_HOST", "localhost"))
    port:     int = field(default_factory=lambda: int(os.getenv("DB_PORT", "5432")))
    database: str = field(default_factory=lambda: os.getenv("DB_NAME", "produccion"))
    user:     str = field(default_factory=lambda: os.getenv("DB_USER", "postgres"))
    password: str = field(default_factory=lambda: os.getenv("DB_PASSWORD", "admin123"))
    schema:   str = "produccion"
    pool_size: int = 5
    max_overflow: int = 10

    @property
    def url(self) -> str:
        return (
            f"postgresql+psycopg2://{self.user}:{self.password}"
            f"@{self.host}:{self.port}/{self.database}"
        )

    @property
    def dsn(self) -> str:
        """Raw psycopg2 DSN string."""
        return (
            f"host={self.host} port={self.port} dbname={self.database} "
            f"user={self.user} password={self.password}"
        )


def setup_logging(name: str, level: int = logging.INFO) -> logging.Logger:
    logger = logging.getLogger(name)
    if logger.handlers:
        return logger
    logger.setLevel(level)

    fmt = logging.Formatter(
        "%(asctime)s  %(levelname)-8s  %(name)s  %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
    )

    sh = logging.StreamHandler()
    sh.setFormatter(fmt)
    logger.addHandler(sh)

    fh = logging.FileHandler(f"{name}.log", encoding="utf-8")
    fh.setFormatter(fmt)
    logger.addHandler(fh)

    return logger


# Instancia global
db_config = DBConfig()
