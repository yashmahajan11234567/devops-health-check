"""Root conftest: makes pytest insert the project root into sys.path,
so 'from app import ...' resolves under plain 'pytest' (as in CI),
not just 'python -m pytest'."""
