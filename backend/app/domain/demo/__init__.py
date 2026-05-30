"""Domain-layer helpers for the demo dataset.

This package is **install-side / seed-only** — none of its code runs at
runtime against operator clusters. It exists so the demo reseed can
synthesize a UBI clickstream the rest of the product reads via its
read-only Protocol (Absolute Rule #4).
"""
