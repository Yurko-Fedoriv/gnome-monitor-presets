import importlib.util
from pathlib import Path
import tempfile
import unittest
from gi.repository import Gio

spec = importlib.util.spec_from_file_location('installer', Path(__file__).resolve().parents[1] / 'install.py')
installer = importlib.util.module_from_spec(spec)
spec.loader.exec_module(installer)


class InstallTests(unittest.TestCase):
    def test_schema_upgrade_preserves_live_reader_and_old_inode(self):
        with tempfile.TemporaryDirectory() as tmp:
            source = Path(tmp) / 'source'
            target = Path(tmp) / 'installed'
            (source / 'schemas').mkdir(parents=True)
            xml = source / 'schemas/test.gschema.xml'
            def schema(extra=''):
                return ('<schemalist><schema id="org.test.monitor.install" path="/org/test/monitor/install/">'
                        '<key name="kvm-detect-until" type="d"><default>0.0</default></key>' + extra + '</schema></schemalist>')
            xml.write_text(schema())
            installer.install(source, target)
            old_source = Gio.SettingsSchemaSource.new_from_directory(str(target / 'schemas'), None, False)
            old_schema = old_source.lookup('org.test.monitor.install', False)
            old_settings = Gio.Settings.new_full(old_schema, Gio.memory_settings_backend_new(), None)
            compiled = target / 'schemas/gschemas.compiled'
            old_inode = compiled.stat().st_ino
            xml.write_text(schema('<key name="monitor-actions" type="s"><default>\'[]\'</default></key>'))
            installer.install(source, target)
            self.assertNotEqual(old_inode, compiled.stat().st_ino)
            self.assertEqual(old_settings.get_double('kvm-detect-until'), 0)
            self.assertFalse(old_schema.has_key('monitor-actions'))
            fresh = Gio.SettingsSchemaSource.new_from_directory(str(target / 'schemas'), None, False)
            self.assertTrue(fresh.lookup('org.test.monitor.install', False).has_key('monitor-actions'))
            current_inode = compiled.stat().st_ino
            installer.install(source, target)
            self.assertEqual(compiled.stat().st_ino, current_inode)

    def test_invalid_schema_does_not_touch_install(self):
        with tempfile.TemporaryDirectory() as tmp:
            source, target = Path(tmp) / 'source', Path(tmp) / 'installed'
            (source / 'schemas').mkdir(parents=True)
            target.mkdir()
            (target / 'metadata.json').write_text('old')
            (source / 'metadata.json').write_text('new')
            (source / 'schemas/broken.gschema.xml').write_text('<broken')
            import subprocess
            with self.assertRaises(subprocess.CalledProcessError):
                installer.install(source, target)
            self.assertEqual((target / 'metadata.json').read_text(), 'old')
