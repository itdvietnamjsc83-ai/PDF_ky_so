@echo off
python -m pytest tests -q
python tools\benchmark.py %1
