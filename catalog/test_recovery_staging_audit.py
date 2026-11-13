import sys
from pathlib import Path
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parent))
from recovery_staging_audit import canonical, waived


class RecoveryStagingTests(unittest.TestCase):
    def test_rstudio_rename_preserves_original_extension(self):
        self.assertEqual(canonical(r'Монтажные листы\Лист.Id_d00000be4710007.doc'),
                         r'Монтажные листы\Лист.doc')
        self.assertEqual(canonical('Other.Id_not_hex.doc'), 'Other.Id_not_hex.doc')

    def test_user_waiver_includes_rstudio_renamed_file(self):
        self.assertTrue(waived(r'Монтаж Эквадора копия винчестера\MPEG2_DVD_PAL.Id_d20000000022cdd.mpg'))
        self.assertTrue(waived(r'Монтаж Эквадора копия винчестера\Исходники\Спринт.avi'))

    def test_other_source_and_new_clip_are_not_waived(self):
        self.assertFalse(waived(r'Другая поездка\Исходники\Спринт.avi'))
        self.assertFalse(waived(r'Монтаж Эквадора копия винчестера\Исходники\Untitled Clip 01.mpeg'))


if __name__ == '__main__':
    unittest.main()
