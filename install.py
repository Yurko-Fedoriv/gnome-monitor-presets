#!/usr/bin/python3
"""Install without modifying files that GNOME may currently have memory-mapped."""
import argparse
from pathlib import Path
import os
import shutil
import subprocess
import tempfile


def install(source, destination):
    source, destination = Path(source), Path(destination)
    destination.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix='.monitor-presets-install-', dir=destination.parent) as temporary:
        stage = Path(temporary) / 'extension'
        shutil.copytree(source, stage, ignore=shutil.ignore_patterns('__pycache__', '*.pyc', 'gschemas.compiled'))
        for name in ('LICENSE', 'NOTICE.md'):
            if (source.parent / name).is_file():
                shutil.copy2(source.parent / name, stage / name)
        subprocess.run(['glib-compile-schemas', '--strict', str(stage / 'schemas')], check=True)
        for path in stage.rglob('*'):
            if not path.is_file():
                continue
            target = destination / path.relative_to(stage)
            target.parent.mkdir(parents=True, exist_ok=True)
            if target.exists() and target.read_bytes() == path.read_bytes():
                continue
            # Rename publishes a new inode. Existing mmap readers retain the old
            # schema; copyfile/copy2 would truncate that inode underneath GNOME.
            os.replace(path, target)
    return destination


if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('--destination', type=Path, default=Path.home() / '.local/share/gnome-shell/extensions/monitor-presets@local')
    args = parser.parse_args()
    target = install(Path(__file__).parent / 'extension', args.destination)
    print(f'Installed to {target}. Log out and back in to load changed Shell code or schemas.')
