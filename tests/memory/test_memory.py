"""
===============================================================================
PROJECT IKRU — Memory System Diagnostic Test
===============================================================================
Run:  python -m tests.memory.test_memory
From: software/
===============================================================================
"""

import os
import sys
import time

# Ensure parent directory is in sys.path
parent_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if parent_dir not in sys.path:
    sys.path.insert(0, parent_dir)

from ikru.memory import MemoryManager


def main():
    print("=" * 60)
    print("  IKRU Memory System — Diagnostic Test")
    print("=" * 60)

    # Use temp paths for test isolation
    project_root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    db_path = os.path.join(project_root, "data", "memory", "test_history.db")
    qdrant_path = os.path.join(project_root, "data", "memory", "test_qdrant")

    print(f"\n[1/6] Initializing MemoryManager...")
    print(f"  SQLite: {db_path}")
    print(f"  Qdrant: {qdrant_path}")
    t0 = time.time()
    memory = MemoryManager(db_path=db_path, qdrant_path=qdrant_path)
    print(f"  Done in {time.time() - t0:.1f}s")

    # --- Test: Record messages ---
    print(f"\n[2/6] Recording test messages...")
    test_messages = [
        ("user", "My name is Avin and I love building robots"),
        ("assistant", "Nice to meet you Avin! I love that you build robots, that is so cool!"),
        ("user", "I am working on a project called IKRU"),
        ("assistant", "IKRU sounds like an amazing project! Tell me more about it."),
        ("user", "My favorite color is blue and I like pizza"),
        ("assistant", "Blue is a great color! And pizza is delicious, great taste!"),
        ("user", "Remember that my birthday is on March 15th"),
        ("assistant", "I will remember that! March 15th, noted!"),
    ]
    for role, content in test_messages:
        if role == "user":
            memory.record_user_message(content)
        else:
            memory.record_assistant_message(content)
        print(f"  [{role}] {content[:60]}...")

    # Small delay to let background threads finish indexing
    print("  Waiting for background indexing...")
    time.sleep(3)

    # --- Test: Stats ---
    print(f"\n[3/6] Memory statistics:")
    stats = memory.get_stats()
    for key, value in stats.items():
        print(f"  {key}: {value}")

    # --- Test: SQLite facts ---
    print(f"\n[4/6] Extracted user facts (auto-detected):")
    facts = memory.db.get_all_facts()
    if facts:
        for f in facts:
            print(f"  [{f['category']}] {f['fact']} (confidence: {f['confidence']})")
    else:
        print("  (none extracted — this may indicate regex patterns need tuning)")

    # --- Test: Semantic recall ---
    print(f"\n[5/6] Semantic recall tests:")
    test_queries = [
        "What is the user's name?",
        "Tell me about the robot project",
        "What food does the user like?",
        "When is the user's birthday?",
        "What color does the user prefer?",
    ]
    for query in test_queries:
        results = memory.vector.search_memories(query, top_k=2, score_threshold=0.3)
        print(f"\n  Query: \"{query}\"")
        if results:
            for r in results:
                print(f"    [{r['score']:.2f}] {r['text'][:80]}...")
        else:
            print(f"    (no matches above threshold)")

    # --- Test: Context assembly ---
    print(f"\n[6/6] Full context assembly for LLM injection:")
    context = memory.build_memory_context("Hey Ikru, do you remember my name?")
    if context:
        print("-" * 40)
        print(context)
        print("-" * 40)
    else:
        print("  (no context assembled)")

    # --- Summary ---
    print(f"\n{'=' * 60}")
    print(f"  TEST COMPLETE")
    print(f"  Messages: {stats['messages']}, Facts: {stats['facts']}, Vectors: {stats['vector_memories']}")
    print(f"{'=' * 60}")

    # Cleanup test data
    cleanup = input("\nClean up test data? (y/n): ").strip().lower()
    if cleanup == "y":
        memory.clear_all()
        import shutil
        try:
            os.remove(db_path)
        except Exception:
            pass
        try:
            shutil.rmtree(qdrant_path)
        except Exception:
            pass
        print("Test data cleaned up.")


if __name__ == "__main__":
    main()
