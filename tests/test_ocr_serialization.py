import json
import unittest
from unittest.mock import patch
from dataclasses import asdict
import numpy as np
from services.vision_adapter import EasyOCRExtractor
from engines.ocr_engine import OCREngine


class OCRSerializationTests(unittest.TestCase):
    def test_native_ocr_coordinates_survive_worker_json(self):
        reader=type('Reader',(),{'readtext':lambda self,path:[
            ([[np.int32(1),np.int32(2)],[np.int32(60),np.int32(2)],[np.int32(60),np.int32(20)],[np.int32(1),np.int32(20)]],'Grade 40/50',np.float32(.95))]})()
        with patch.object(EasyOCRExtractor,'__init__',lambda self:setattr(self,'reader',reader)):
            visual=EasyOCRExtractor().extract('fixture')
            self.assertEqual(json.loads(json.dumps(visual))['raw_text'],'Grade 40/50')
            engine=OCREngine()
            result=engine.recognize('fixture',page=13)
            records=json.loads(json.dumps([asdict(record) for record in result.results]))
            self.assertEqual(records[0]['page'],13)
            self.assertEqual(records[0]['bounding_box']['x'],1.0)
            self.assertGreater(records[0]['confidence'],.9)

if __name__=='__main__':unittest.main()
