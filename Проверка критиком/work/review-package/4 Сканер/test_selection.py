import unittest
from build_selection import select, THRESHOLDS_V2, VIDEO, CAMERA_IMAGES
from inventory import MEDIA

class SelectionTests(unittest.TestCase):
    def test_threshold(self):
        self.assertFalse(select('trip/small.jpg', 1048575))
        self.assertTrue(select('trip/exact.JPG', 1048576))

    def test_old_and_new_video_formats(self):
        for name in ['old.m2v', 'movie.WEBM', 'clip.flv', 'a.mp4']:
            self.assertTrue(select('trip/'+name, 2000000))

    def test_exclusions_any_depth(self):
        for name in ['RECYCLER/a.mp4', 'backup/node_modules/a.jpg', '.env/a.jpg', '.Trashes/a.mp4']:
            self.assertFalse(select(name, 2000000))

    def test_companions_are_not_hash_selection(self):
        self.assertFalse(select('trip/program.pdf', 2000000))
        self.assertFalse(select('Книжки/book.zip', 2000000))
        self.assertTrue(select('Поездка/Фото/a.jpg', 2000000))

    def test_version_2_thresholds(self):
        v2 = THRESHOLDS_V2
        self.assertTrue(select('2004/IMG_0001.JPG', 50_000, v2))
        self.assertFalse(select('2004/IMG_0001.JPG', 49_999, v2))
        self.assertTrue(select('phone/a.HEIC', 60_000, v2))
        self.assertFalse(select('site/logo.png', 149_999, v2))
        self.assertTrue(select('site/photo.png', 150_000, v2))
        self.assertFalse(select('raw/a.cr2', 100_000, v2))
        self.assertTrue(select('2005/clip.3gp', 120_000, v2))
        self.assertFalse(select('2005/empty.mp4', 0, v2))
        self.assertFalse(select('RECYCLER/IMG.jpg', 500_000, v2))
        self.assertFalse(select('trip/program.pdf', 500_000, v2))
        self.assertTrue(VIDEO <= MEDIA and CAMERA_IMAGES <= MEDIA)

if __name__ == '__main__':
    unittest.main()
