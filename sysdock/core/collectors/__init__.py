"""Portable, psutil-based metric collectors.

Each collector is a small stateful object: it caches static facts (core counts,
partition lists, NIC lists) and holds the previous sample so rate/delta metrics
(CPU %, network throughput, disk I/O) can be computed without blocking. The
shared :class:`sysdock.core.snapshot.SnapshotProvider` owns one instance of each
and drives them on a timer, so every surface reads identical data.

Every external call is wrapped defensively: a collector degrades to safe
defaults rather than raising, in keeping with the production bar.
"""
