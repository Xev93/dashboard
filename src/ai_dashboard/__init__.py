from importlib.metadata import PackageNotFoundError, version

try:
    __version__ = version("ai-dashboard")
except PackageNotFoundError:
    __version__ = "0.0.0"

USER_AGENT = f"ai-dashboard/{__version__}"
