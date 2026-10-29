"""PersonaTrace Ultimate GUI package.

Dashboard server lives in :mod:`personatrace.gui.server`. This package
deliberately imports nothing on load so that importing it can never crash
because another (not yet built) module is missing; the server imports
core/storage lazily with a demo-data fallback.
"""
