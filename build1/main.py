"""
Windows 11 GPU Preference Manager & Live Monitor
Entry Point
"""
import sys
import os

# Add local directory to path
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from main_window import run_app

if __name__ == "__main__":
    run_app()
