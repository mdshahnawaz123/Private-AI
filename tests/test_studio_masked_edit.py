import io
import tempfile
import unittest
from pathlib import Path
from PIL import Image
from services.image_engine.masked_edit import composite_edit, load_pair


class MaskedEditTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.reference = Path(self.tmp.name)/'source.png'
        self.mask = Path(self.tmp.name)/'mask.png'
        source = Image.new('RGBA', (20, 10), (35, 60, 100, 255))
        source.putpixel((0, 0), (4, 5, 6, 150))
        source.save(self.reference)
        mask = Image.new('L', source.size, 0)
        for x in range(5, 10):
            for y in range(2, 8):
                mask.putpixel((x, y), 255)
        mask.save(self.mask)

    def candidate(self, size=(20, 10)):
        buf = io.BytesIO()
        Image.new('RGB', size, 'red').save(buf, 'PNG')
        return buf.getvalue()

    def test_every_protected_pixel_preserved_and_only_mask_replaced(self):
        before = self.reference.read_bytes()
        result, meta = composite_edit(self.reference, self.mask, self.candidate())
        original, mask = load_pair(self.reference, self.mask)
        image = Image.open(io.BytesIO(result))
        for y in range(10):
            for x in range(20):
                expected = (255, 0, 0, 255) if mask.getpixel((x,y)) else original.getpixel((x,y))
                self.assertEqual(image.getpixel((x,y)), expected)
        self.assertEqual(self.reference.read_bytes(), before)
        self.assertFalse(meta['geometry_inside_mask_verified'])
        self.assertEqual(len(meta['mask_sha256']), 64)

    def test_matching_aspect_candidate_resized_explicitly(self):
        result, meta = composite_edit(self.reference, self.mask, self.candidate((10,5)))
        self.assertEqual(Image.open(io.BytesIO(result)).size, (20,10))
        self.assertTrue(meta['candidate_resized'])

    def test_wrong_framing_fails_closed(self):
        with self.assertRaisesRegex(ValueError, 'framing'):
            composite_edit(self.reference, self.mask, self.candidate((10,10)))

    def test_wrong_mask_dimensions_rejected(self):
        Image.new('L', (10,10)).save(self.mask)
        with self.assertRaisesRegex(ValueError, 'dimensions'):
            load_pair(self.reference, self.mask)

    def test_empty_full_grey_colour_and_transparent_masks_rejected(self):
        for color in [(0,0,0,255), (255,255,255,255), (128,128,128,255), (255,0,0,255), (255,255,255,0)]:
            with self.subTest(color=color):
                Image.new('RGBA', (20,10), color).save(self.mask)
                with self.assertRaises(ValueError):
                    load_pair(self.reference, self.mask)

    def test_jpeg_mask_rejected(self):
        Image.new('RGB',(20,10)).save(self.mask,format='JPEG')
        with self.assertRaisesRegex(ValueError, 'PNG'):
            load_pair(self.reference, self.mask)


if __name__ == '__main__':
    unittest.main()
