"""Include the prebuilt React application in release wheels."""
from pathlib import Path
from re import findall
from shutil import copytree, rmtree

from setuptools import setup
from setuptools.command.build_py import build_py
from setuptools.command.sdist import sdist


def validate_frontend() -> Path:
    source = Path(__file__).parent / "frontend" / "dist"
    index = source / "index.html"
    if not index.is_file():
        raise RuntimeError("Frontend не собран: выполните 'cd frontend && npm ci && npm run build' перед сборкой Python-пакета")
    referenced = findall(r'(?:src|href)="/(assets/[^\"]+)"', index.read_text(encoding="utf-8"))
    if not referenced or any(not (source / asset).is_file() for asset in referenced):
        raise RuntimeError("Frontend-сборка неполная: в index.html отсутствуют необходимые JS/CSS ресурсы")
    return source


class BuildWithFrontend(build_py):
    def run(self) -> None:
        source = validate_frontend()
        super().run()
        target = Path(self.build_lib) / "money_graph" / "web"
        if target.exists():
            rmtree(target)
        copytree(source, target)


class SourceWithFrontend(sdist):
    def run(self) -> None:
        validate_frontend()
        super().run()


setup(cmdclass={"build_py": BuildWithFrontend, "sdist": SourceWithFrontend})
