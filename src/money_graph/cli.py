from __future__ import annotations

import argparse
import sys
from pathlib import Path

import uvicorn

from .analytics import DataContractError, run_analysis


def parser() -> argparse.ArgumentParser:
    root = argparse.ArgumentParser(prog="money-graph", description="Explainable AML Graph Intelligence")
    commands = root.add_subparsers(dest="command", required=True)
    analyze = commands.add_parser("analyze", help="Рассчитать модель и выгрузки")
    analyze.add_argument("--data", type=Path, required=True)
    analyze.add_argument("--out", type=Path, required=True)
    analyze.add_argument("--config", type=Path)
    serve = commands.add_parser("serve", help="Запустить API для готовых артефактов")
    serve.add_argument("--artifacts", type=Path, required=True)
    serve.add_argument("--host", default="127.0.0.1")
    serve.add_argument("--port", default=8000, type=int)
    demo = commands.add_parser("demo", help="Пересчитать данные и запустить API")
    demo.add_argument("--data", type=Path, required=True)
    demo.add_argument("--out", type=Path, required=True)
    demo.add_argument("--config", type=Path)
    demo.add_argument("--host", default="127.0.0.1")
    demo.add_argument("--port", default=8000, type=int)
    return root


def main() -> None:
    args = parser().parse_args()
    try:
        if args.command in {"serve", "demo"}:
            from .api import frontend_directory
            frontend_directory()
        if args.command in {"analyze", "demo"}:
            manifest = run_analysis(args.data, args.out, getattr(args, "config", None))
            print(f"Готово: {args.out} ({manifest['elapsed_seconds']} сек.)")
            if args.command == "analyze":
                return
        from .api import create_app
        uvicorn.run(create_app(args.artifacts if args.command == "serve" else args.out, serve_frontend=True), host=args.host, port=args.port)
    except DataContractError as error:
        print(f"Ошибка контракта данных: {error}", file=sys.stderr)
        raise SystemExit(2) from error
    except ValueError as error:
        print(f"Ошибка запуска: {error}", file=sys.stderr)
        raise SystemExit(2) from error


if __name__ == "__main__":
    main()
