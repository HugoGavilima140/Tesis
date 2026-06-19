"""
Gestor de migraciones evolutivas de schema.

Permite:
  1. Aplicar migraciones desde archivos .sql en carpeta /migrations
  2. Agregar columnas a tablas existentes de forma segura (ADD COLUMN IF NOT EXISTS)
  3. Crear índices sin bloquear producción (CREATE INDEX CONCURRENTLY)
  4. Registrar cada migración en schema_migrations con checksum
  5. Auditar el estado de todas las migraciones
"""
from __future__ import annotations

import hashlib
import logging
from datetime import datetime
from pathlib import Path
from textwrap import dedent
from typing import Optional

from sqlalchemy import create_engine, text

from config import DBConfig, db_config, setup_logging

log = setup_logging("MigrationManager")


# ──────────────────────────────────────────────────────────────
class MigrationManager:
    """
    Gestor de migraciones evolutivas.

    Convención de nombres para archivos de migración:
        YYYYMMDDNNN_descripcion_corta.sql
        Ejemplo: 20240315001_add_column_nivel_vip.sql
    """

    def __init__(
        self,
        config: DBConfig = db_config,
        migrations_dir: str = "../migrations",
    ) -> None:
        self.engine = create_engine(
            config.url, pool_size=2, max_overflow=0, pool_pre_ping=True
        )
        self.migrations_dir = Path(migrations_dir)
        self.schema = config.schema

    # ──────────────────────────────────────────────────
    # CONSULTAS DE ESTADO
    # ──────────────────────────────────────────────────
    def applied_versions(self) -> set[str]:
        with self.engine.connect() as conn:
            rows = conn.execute(
                text(f"SELECT version FROM {self.schema}.schema_migrations")
            )
            return {row[0] for row in rows}

    def status(self) -> None:
        applied = self.applied_versions()
        files   = sorted(self.migrations_dir.glob("*.sql"))
        log.info(f"{'─'*60}")
        log.info(f"  Migraciones disponibles: {len(files)}")
        log.info(f"  Migraciones aplicadas  : {len(applied)}")
        log.info(f"{'─'*60}")
        for f in files:
            ver = f.stem.split("_")[0]
            tag = "✓ APLICADA" if ver in applied else "✗ PENDIENTE"
            log.info(f"  [{tag}]  {f.name}")

    # ──────────────────────────────────────────────────
    # APLICAR UNA MIGRACIÓN
    # ──────────────────────────────────────────────────
    def apply(self, version: str, name: str, sql: str) -> None:
        checksum = hashlib.sha256(sql.encode()).hexdigest()
        log.info(f"Aplicando migración {version}: {name}")
        with self.engine.begin() as conn:
            conn.execute(text(sql))
            conn.execute(
                text(f"""
                    INSERT INTO {self.schema}.schema_migrations
                        (version, nombre, checksum)
                    VALUES (:v, :n, :c)
                    ON CONFLICT (version) DO NOTHING
                """),
                {"v": version, "n": name, "c": checksum},
            )
        log.info(f"  → Migración {version} aplicada (checksum: {checksum[:12]}…)")

    # ──────────────────────────────────────────────────
    # EJECUTAR TODAS LAS PENDIENTES
    # ──────────────────────────────────────────────────
    def run_all(self) -> int:
        applied = self.applied_versions()
        files   = sorted(self.migrations_dir.glob("*.sql"))
        count   = 0
        for f in files:
            ver  = f.stem.split("_")[0]
            name = "_".join(f.stem.split("_")[1:])
            if ver in applied:
                log.debug(f"Saltando migración ya aplicada: {ver}")
                continue
            sql = f.read_text(encoding="utf-8")
            self.apply(ver, name, sql)
            count += 1
        if count == 0:
            log.info("No hay migraciones pendientes.")
        else:
            log.info(f"{count} migración(es) aplicada(s).")
        return count

    # ──────────────────────────────────────────────────
    # OPERACIONES DE ALTO NIVEL (SIN ARCHIVO SQL)
    # ──────────────────────────────────────────────────
    def add_column(
        self,
        table: str,
        column: str,
        column_def: str,
        migration_version: str,
    ) -> None:
        """
        Agrega una columna de forma segura (IF NOT EXISTS).
        Registra la operación como una migración.
        """
        sql = dedent(f"""
            ALTER TABLE {self.schema}.{table}
            ADD COLUMN IF NOT EXISTS {column} {column_def};
        """).strip()
        self.apply(migration_version, f"add_column_{table}_{column}", sql)

    def add_index(
        self,
        index_name: str,
        table: str,
        columns: str,
        migration_version: str,
        unique: bool = False,
        where: Optional[str] = None,
        concurrent: bool = True,
    ) -> None:
        """
        Crea un índice (IF NOT EXISTS).
        concurrent=True usa CREATE INDEX CONCURRENTLY (sin bloqueo en producción).
        Nota: CONCURRENTLY no puede ejecutarse dentro de una transacción;
        se maneja con autocommit.
        """
        concurrent_kw = "CONCURRENTLY" if concurrent else ""
        unique_kw     = "UNIQUE" if unique else ""
        where_clause  = f"WHERE {where}" if where else ""

        sql = (
            f"CREATE {unique_kw} INDEX {concurrent_kw} IF NOT EXISTS {index_name} "
            f"ON {self.schema}.{table} ({columns}) {where_clause};"
        ).strip()

        if concurrent:
            # CONCURRENTLY requiere autocommit
            with self.engine.connect() as conn:
                conn.execution_options(isolation_level="AUTOCOMMIT")
                conn.execute(text(sql))
            # Registrar en schema_migrations manualmente
            checksum = hashlib.sha256(sql.encode()).hexdigest()
            with self.engine.begin() as conn:
                conn.execute(
                    text(f"""
                        INSERT INTO {self.schema}.schema_migrations
                            (version, nombre, checksum)
                        VALUES (:v, :n, :c)
                        ON CONFLICT (version) DO NOTHING
                    """),
                    {
                        "v": migration_version,
                        "n": f"add_index_{index_name}",
                        "c": checksum,
                    },
                )
        else:
            self.apply(migration_version, f"add_index_{index_name}", sql)

        log.info(f"Índice {index_name} creado en {self.schema}.{table}({columns})")

    def rename_column(
        self,
        table: str,
        old_name: str,
        new_name: str,
        migration_version: str,
    ) -> None:
        sql = (
            f"ALTER TABLE {self.schema}.{table} "
            f"RENAME COLUMN {old_name} TO {new_name};"
        )
        self.apply(migration_version, f"rename_{table}_{old_name}_to_{new_name}", sql)

    def add_check_constraint(
        self,
        table: str,
        constraint_name: str,
        expression: str,
        migration_version: str,
    ) -> None:
        sql = dedent(f"""
            ALTER TABLE {self.schema}.{table}
            ADD CONSTRAINT {constraint_name}
            CHECK ({expression})
            NOT VALID;

            ALTER TABLE {self.schema}.{table}
            VALIDATE CONSTRAINT {constraint_name};
        """).strip()
        self.apply(
            migration_version,
            f"add_check_{table}_{constraint_name}",
            sql,
        )

    # ──────────────────────────────────────────────────
    # GENERADOR DE ARCHIVO DE MIGRACIÓN
    # ──────────────────────────────────────────────────
    def generate_migration_file(self, description: str, sql: str) -> Path:
        """Genera un archivo .sql con timestamp automático."""
        ts  = datetime.now().strftime("%Y%m%d%H%M")
        slug = description.lower().replace(" ", "_")[:40]
        fname = self.migrations_dir / f"{ts}_{slug}.sql"
        fname.parent.mkdir(parents=True, exist_ok=True)
        header = dedent(f"""
            -- Migration: {ts}_{slug}
            -- Created : {datetime.now().isoformat()}
            -- Description: {description}
            -- ──────────────────────────────────────────
        """).strip()
        fname.write_text(f"{header}\n\n{sql}\n", encoding="utf-8")
        log.info(f"Archivo de migración generado: {fname}")
        return fname

    # ──────────────────────────────────────────────────
    # ROLLBACK PARCIAL (reversión de la última migración)
    # ──────────────────────────────────────────────────
    def rollback_last(self) -> None:
        """
        Elimina el registro de la última migración aplicada.
        El SQL de reversión debe ejecutarse manualmente (DDL es destructivo).
        """
        with self.engine.begin() as conn:
            conn.execute(
                text(f"""
                    DELETE FROM {self.schema}.schema_migrations
                    WHERE migration_id = (
                        SELECT MAX(migration_id)
                        FROM {self.schema}.schema_migrations
                    )
                """)
            )
        log.warning("Registro de última migración eliminado. "
                    "Revisar y ejecutar SQL de rollback manualmente.")


# ──────────────────────────────────────────────────────────────
# CLI mínimo
# ──────────────────────────────────────────────────────────────
if __name__ == "__main__":
    import sys

    mgr = MigrationManager()
    cmd = sys.argv[1] if len(sys.argv) > 1 else "status"

    if cmd == "status":
        mgr.status()

    elif cmd == "run":
        mgr.run_all()

    elif cmd == "add-column":
        # Uso: python migration_manager.py add-column <tabla> <columna> "<definicion>" <version>
        _, _, table, col, col_def, ver = sys.argv
        mgr.add_column(table, col, col_def, ver)

    elif cmd == "rollback":
        mgr.rollback_last()

    else:
        print("Comandos: status | run | add-column | rollback")
