import unittest
from build_selection import select

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

if __name__ == '__main__':
    unittest.main()
