# Local development

- Use normal Git and commit each completed version.
- Install updates using `/usr/bin/python3 install.py`. It stages and atomically replaces files.
- NEVER overwrite an installed `gschemas.compiled` in place (including `shutil.copy2`) or run `glib-compile-schemas` in the live extension directory. GNOME memory-maps it; in-place replacement caused a real desktop crash. The installer regression tests cover this.
- Run hardware-changing tests only when the user is ready for the requested display transition. Tests under `tests/smoke-shell.sh` use isolated headless sessions.
