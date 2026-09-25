# Notebook utilities SparkLab binds in Fabric and Synapse notebooks. Not the Microsoft package.
from typing import Any

def __getattr__(name: str) -> Any: ...
