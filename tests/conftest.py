"""Shared test setup.

Day 33 (CAR-8): the Models -> Cloud list reads Ollama's public model list
over the network. Tests never touch the network: they get the short
fallback list unless a test turns the live list on against a mock server.
"""
import os

os.environ.setdefault("CARAVAN_OLLAMA_CLOUD_CATALOG", "static")
os.environ.pop("CARAVAN_OLLAMA_CLOUD_URL", None)
