import unittest
from services.pdf_text_quality import native_text_usable,page_text_rotation
class TextQualityTests(unittest.TestCase):
 def test_good(self):self.assertTrue(native_text_usable('Door D-12 width 900 mm. Status TBC. Revision A. '*3))
 def test_controls(self):self.assertFalse(native_text_usable('abc\x00\x01\x8f'*100))
 def test_unicode(self):self.assertTrue(native_text_usable('\u5de5\u7a0b\u56fe\u7eb8'*30))
 def test_private_glyph(self):self.assertFalse(native_text_usable('\ue012'*100))
 def test_sparse(self):self.assertFalse(native_text_usable('KEO'))
 def test_rotation(self):
  class P:
   def get_text(self,mode):return {'blocks':[{'lines':[{'dir':(0,-1),'spans':[{'text':'Engineering drawing notes'}]}]}]}
  self.assertEqual(page_text_rotation(P()),90)
if __name__=='__main__':unittest.main()
