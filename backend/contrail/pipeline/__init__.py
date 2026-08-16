"""Derivation pipeline: raw points -> Places, Tracks, Trips, Anchors.

Everything in here is a pure function over plain dataclasses. Nothing touches
the database, so the algorithms that decide what the product actually shows can
be tested without Postgres. Persistence lives in importer.py.

P1: raw_point is immutable. Every structure produced here can be deleted and
recomputed at any time.
"""
