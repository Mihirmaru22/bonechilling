# Releasing a new version

Releases are published automatically by `.github/workflows/release.yml`.

1. Bump the version in **both** places (they must match):
   - `src/bonechiling/__init__.py` → `__version__ = "0.2.1"`
   - `pyproject.toml` → `version = "0.2.1"`
2. Commit and push to `main`.
3. Tag and push the tag:
   ```bash
   git tag v0.2.1
   git push origin v0.2.1
   ```
4. In ~5 minutes the release appears at
   <https://github.com/Mihirmaru22/bonechilling/releases> with the installer,
   a portable zip and checksums. Share **https://github.com/Mihirmaru22/bonechilling/releases/latest**:
   it always points at the newest version.

If the tag doesn't match the version, the workflow stops with a clear error and
nothing is published. Tests must pass on Windows before anything is released.
