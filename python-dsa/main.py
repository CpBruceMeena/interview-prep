#!/usr/bin/env python3
"""
Python DSA — Interview Preparation
===================================
Run all category demos to see implementations, thought processes,
and complexity analysis for each data structure and algorithm.

Usage:
    python main.py          # Run all demos
    python main.py -l       # List all available categories

To run a specific category:
    python 01_arrays/questions.py
    python 03_stacks/questions.py
"""

import importlib
import sys
import time


CATEGORIES = [
    ("01_arrays", "Arrays"),
    ("02_strings", "Strings"),
    ("03_stacks", "Stacks"),
    ("04_queues", "Queues"),
    ("05_hashing", "Hashing"),
    ("06_linked_lists", "Linked Lists"),
    ("07_trees", "Trees"),
    ("08_graphs", "Graphs"),
    ("09_dynamic_programming", "Dynamic Programming"),
    ("10_sorting_searching", "Sorting & Searching"),
    ("11_backtracking", "Backtracking"),
    ("12_trie", "Trie"),
    ("13_heaps", "Heaps"),
    ("14_bit_manipulation", "Bit Manipulation"),
    ("15_advanced_strings", "Advanced Strings"),
    ("16_advanced_trees", "Advanced Trees"),
    ("17_sliding_window", "Sliding Window"),
]


def list_categories():
    print("\n📚 Available DSA Categories:\n")
    for i, (module, name) in enumerate(CATEGORIES, 1):
        print(f"  {i:2d}. {name:30s} → python-dsa/{module}/questions.py")
    print("\n")


def run_all():
    total_start = time.time()

    for module, name in CATEGORIES:
        print(f"\n{'#' * 70}")
        print(f"# {name:66s} #")
        print(f"{'#' * 70}")

        try:
            mod = importlib.import_module(f"{module}.questions")
            if hasattr(mod, 'demo'):
                mod.demo()
        except ModuleNotFoundError as e:
            print(f"   ❌ Could not load {module}: {e}")
        except Exception as e:
            print(f"   ❌ Error in {name}: {e}")

        print()

    total_time = time.time() - total_start
    print(f"\n{'=' * 70}")
    print(f"✅ All categories completed in {total_time:.2f} seconds!")
    print(f"{'=' * 70}")


if __name__ == "__main__":
    if len(sys.argv) > 1 and sys.argv[1] == "-l":
        list_categories()
    else:
        run_all()
