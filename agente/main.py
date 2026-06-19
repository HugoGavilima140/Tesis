"""
agente/main.py — Entry point del Business Reasoning Agent de PayNova.

Modos de uso:
  1. Modo interactivo (chat):
       python -m agente.main

  2. Una sola pregunta:
       python -m agente.main --question "¿Cuál fue el GMV del mes pasado?"

  3. Verbose (muestra trazado ReAct completo):
       python -m agente.main --verbose

  4. Reconstruir índice de KB:
       python -m agente.main --rebuild-kb

  5. Mostrar estadísticas de memoria:
       python -m agente.main --stats

Desde el raíz del proyecto:
  python -m agente.main
"""

import argparse
import sys
from pathlib import Path

# Asegurar que el directorio padre esté en el path
sys.path.insert(0, str(Path(__file__).parent.parent))


def print_welcome():
    print("\n" + "=" * 60)
    print("  PayNova Business Reasoning Agent")
    print("  Arquitectura: ReAct + Multi-Hop + Reflexión")
    print("  Base de conocimiento: PayNova Knowledge Base (10 docs)")
    print("=" * 60)


def run_interactive(agent, verbose: bool = False):
    """Modo interactivo tipo chat."""
    print_welcome()
    print("\nEscribe tu pregunta de negocio. Escribe 'salir' para terminar.\n")
    print("Ejemplos de preguntas:")
    print("  • ¿Cuál fue el GMV total del último mes?")
    print("  • ¿Qué comercios tienen mayor riesgo de fraude?")
    print("  • ¿Cómo está el funnel de onboarding de comercios?")
    print("  • ¿Cuál es la tasa de aprobación de transacciones?")
    print()

    while True:
        try:
            question = input("Pregunta > ").strip()
        except (KeyboardInterrupt, EOFError):
            print("\n[Agente] Sesión terminada.")
            break

        if not question:
            continue

        if question.lower() in ("salir", "exit", "quit", "q"):
            print("[Agente] Hasta luego.")
            break

        print(f"\n[Agente] Procesando: '{question[:60]}...' \n")

        try:
            response = agent.answer(question, verbose=verbose)
            print("\n" + "=" * 60)
            print(response.to_text())
            print("=" * 60 + "\n")
        except Exception as e:
            print(f"[Agente] Error: {e}")
            if verbose:
                import traceback
                traceback.print_exc()


def run_single_question(agent, question: str, verbose: bool = False):
    """Ejecuta una sola pregunta y muestra la respuesta."""
    print_welcome()
    print(f"\n[Agente] Procesando: {question}\n")

    response = agent.answer(question, verbose=verbose)

    print("\n" + "=" * 60)
    print(response.to_text())
    print("=" * 60)


def run_demo(agent, verbose: bool = False):
    """Ejecuta una batería de preguntas de demostración."""
    demo_questions = [
        "¿Cuál fue el GMV total y los ingresos por MDR del mes pasado?",
        "¿Qué comercios son los más rentables en términos de MDR generado?",
        "¿Cuál es la tasa de aprobación de transacciones por canal de pago?",
        "¿Cuántos comercios están activos actualmente y cuántos están en proceso de onboarding?",
        "¿Qué Account Manager tiene el portafolio de comercios con mayor GMV?",
    ]

    print_welcome()
    print("\n[Demo] Ejecutando preguntas de demostración...\n")

    for i, question in enumerate(demo_questions, 1):
        print(f"\n{'='*60}")
        print(f"[Demo {i}/{len(demo_questions)}] {question}")
        print("=" * 60)
        try:
            response = agent.answer(question, verbose=verbose)
            print(response.to_text())
        except Exception as e:
            print(f"Error: {e}")

    print("\n[Demo] Completado.")


def show_stats(agent):
    """Muestra estadísticas de la memoria del agente."""
    stats = agent.memory.get_stats()
    print("\n=== Estadísticas de Memoria ===")
    for key, count in stats.items():
        print(f"  {key}: {count} entradas")


def main():
    parser = argparse.ArgumentParser(
        description="PayNova Business Reasoning Agent — ReAct + Multi-Hop"
    )
    parser.add_argument(
        "--question", "-q", type=str, default=None,
        help="Pregunta específica a responder (modo no interactivo)"
    )
    parser.add_argument(
        "--verbose", "-v", action="store_true",
        help="Mostrar trazado ReAct completo"
    )
    parser.add_argument(
        "--rebuild-kb", action="store_true",
        help="Reconstruir el índice de la base de conocimiento"
    )
    parser.add_argument(
        "--demo", action="store_true",
        help="Ejecutar preguntas de demostración"
    )
    parser.add_argument(
        "--stats", action="store_true",
        help="Mostrar estadísticas de memoria del agente"
    )
    parser.add_argument(
        "--kb-dir", type=str, default=None,
        help="Ruta alternativa a la base de conocimiento Markdown"
    )
    args = parser.parse_args()

    # Configurar KB dir si se proporciona
    if args.kb_dir:
        import agente.config as cfg
        cfg.KB_DIR = Path(args.kb_dir)

    # Inicializar el agente
    from agente.pipeline.react_loop import BusinessReasoningAgent
    agent = BusinessReasoningAgent(force_rebuild_kb=args.rebuild_kb)

    if args.stats:
        show_stats(agent)
        return

    if args.demo:
        run_demo(agent, verbose=args.verbose)
        return

    if args.question:
        run_single_question(agent, args.question, verbose=args.verbose)
        return

    # Modo interactivo por defecto
    run_interactive(agent, verbose=args.verbose)


if __name__ == "__main__":
    main()
