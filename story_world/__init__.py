"""Datenfundament für die fortlaufende Story-Welt."""

__version__ = "0.6.0"
__min_python__ = "3.9"  # Update installiert nur, wenn das laufende Python mindestens diese Version hat

try:  # unterbrochenes Update reparieren, bevor irgendein anderes Modul geladen wird
    from ._reparatur import beim_start as _beim_start
    _beim_start()
except ImportError:
    pass
