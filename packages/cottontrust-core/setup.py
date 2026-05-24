"""
cottontrust-core — Pacote compartilhado do COTTONTRUST.

Contém as primitivas blockchain usadas pelo cliente e pelo coordinator:
    - wallet.py:    gerenciamento de wallets (aries-askar)
    - identity.py:  derivação de DIDs (Ed25519 + base58)
    - ledger.py:    operações no ledger Indy (indy-vdr)

Instalação em modo editável (desenvolvimento):
    pip install -e packages/cottontrust-core

Instalação no Dockerfile:
    COPY packages/cottontrust-core /tmp/cottontrust-core
    RUN pip install /tmp/cottontrust-core
"""
from setuptools import setup, find_packages

setup(
    name="cottontrust-core",
    version="0.1.0",
    description="Primitivas blockchain compartilhadas do COTTONTRUST",
    packages=find_packages(),
    python_requires=">=3.10",
    install_requires=[
        "indy-vdr>=0.3.4",
        "aries-askar>=0.3.2",
        "base58>=2.1.1",
        "loguru>=0.7.0",
    ],
)