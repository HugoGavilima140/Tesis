"""
Punto de entrada unificado del pipeline fintech IBM Dataset.

Uso:
  python main.py load   <ruta_csv>          # Carga completa
  python main.py update <ruta_csv>          # Actualización incremental
  python main.py migrate                    # Ejecutar migraciones pendientes
  python main.py migrate status             # Ver estado de migraciones
  python main.py add-column <tabla> <col> "<definicion>" <version>
"""
import sys

from config import setup_logging

log = setup_logging("Main")


def cmd_load(csv_path: str) -> None:
    from etl_ibm_loader import IBMDatasetETL
    IBMDatasetETL(csv_path).run()


def cmd_update(csv_path: str) -> None:
    from incremental_update import IncrementalUpdater
    IncrementalUpdater().run(csv_path)


def cmd_migrate(sub: str = "run", *args) -> None:
    from migration_manager import MigrationManager
    mgr = MigrationManager()
    if sub == "status":
        mgr.status()
    elif sub == "run":
        mgr.run_all()
    elif sub == "rollback":
        mgr.rollback_last()


def cmd_add_column(table: str, col: str, col_def: str, version: str) -> None:
    from migration_manager import MigrationManager
    MigrationManager().add_column(table, col, col_def, version)


def main() -> None:
    args = sys.argv[1:]
    if not args:
        print(__doc__)
        sys.exit(0)

    cmd = args[0]
    if cmd == "load":
        cmd_load(args[1])
    elif cmd == "update":
        cmd_update(args[1])
    elif cmd == "migrate":
        sub = args[1] if len(args) > 1 else "run"
        cmd_migrate(sub)
    elif cmd == "add-column" and len(args) >= 5:
        cmd_add_column(args[1], args[2], args[3], args[4])
    else:
        print(__doc__)
        sys.exit(1)


if __name__ == "__main__":
    main()
