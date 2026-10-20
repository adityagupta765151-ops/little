"""The fast lane. Commands answered here never reach the model."""
from .router import fast_route

__all__ = ["fast_route"]
