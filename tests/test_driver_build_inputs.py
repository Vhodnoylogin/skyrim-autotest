import tempfile
from pathlib import Path
import unittest
from skyrim_autotest.build_driver import compilation_sources


class CompilationInputs(unittest.TestCase):
    def test_stale_extra_translation_unit_never_enters_compiler_arguments(self):
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp)
            for name in ('one.cpp','two.cpp','stale.cpp'): (root/name).write_text('int fixture;')
            self.assertEqual([p.name for p in compilation_sources(root,{'files':{'two.cpp':'b','one.cpp':'a'}})],
                             ['one.cpp','two.cpp'])

    def test_missing_declared_source_and_path_escape_fail(self):
        with tempfile.TemporaryDirectory() as tmp:
            for files in ({'missing.cpp':'a'},{'../else.cpp':'a'},{'sub\\else.cpp':'a'},{}):
                with self.subTest(files=files),self.assertRaises(ValueError):
                    compilation_sources(Path(tmp),{'files':files})
