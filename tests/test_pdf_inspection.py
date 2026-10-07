import json,tempfile,unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch
import fitz
from services.pdf_inspection import inspect_page,supplement_inspection
from intelligence.inspection_answers import inspection_answer

class PDFInspectionTests(unittest.TestCase):
    def page(self):
        annotation=SimpleNamespace(info={'name':'Draft','subject':'Draft','id':'a1','content':'Check reference'},
            rect=fitz.Rect(10,20,100,70),type=(13,'Stamp'),xref=1)
        return SimpleNamespace(get_text=lambda mode:{'blocks':[{'lines':[{'spans':[{'text':'DETAIL-Z','bbox':[12,24,40,35]}]}]}]},
            annots=lambda:[annotation],rotation_matrix=fitz.Matrix(1,0,0,1,0,0),rotation=0,
            rect=fitz.Rect(0,0,200,200),get_pixmap=lambda **kwargs:SimpleNamespace(save=lambda path:Path(path).write_bytes(b'image')))

    def test_native_geometry_and_annotation_relationship_are_preserved(self):
        result=inspect_page(self.page())
        self.assertEqual(result['native_spans'][0]['bbox'],[12,24,40,35])
        annotation=result['annotations'][0]
        self.assertEqual(annotation['nearby_native_text'],['DETAIL-Z'])
        self.assertEqual(annotation['relationship_state'],'REVIEW_REQUIRED')
        self.assertEqual(annotation['internal_name'],'Draft')

    def test_rotation_maps_annotation_to_display_region(self):
        page=self.page();page.rotation_matrix=fitz.Matrix(0,1,-1,0,200,0);page.rotation=90
        result=inspect_page(page)['annotations'][0]
        self.assertEqual(result['display_bbox'],[130,10,180,100])
        self.assertEqual(result['bbox'],[10,20,100,70])

    def test_stamp_ocr_is_cached_and_never_establishes_approval(self):
        with tempfile.TemporaryDirectory() as root:
            path=Path(root)/'source.pdf';path.write_bytes(b'synthetic-source')
            page=self.page();document=SimpleNamespace(__enter__=lambda s:s,__exit__=lambda *a:None)
            class Doc:
                def __enter__(self):return self
                def __exit__(self,*args):pass
                def __getitem__(self,index):return page
            def worker(args,**kwargs):
                Path(args[-1]).write_text(json.dumps({'success':True,'raw_text':'Approved With Comments','ocr_confidence':1.0}))
                return SimpleNamespace(returncode=0)
            meta={'pages':[{'page':1}]}
            with patch('fitz.open',return_value=Doc()),patch('subprocess.run',side_effect=worker) as run:
                supplement_inspection(str(path),meta);supplement_inspection(str(path),meta)
                self.assertEqual(run.call_count,1)
                path.write_bytes(b'changed-source');supplement_inspection(str(path),meta)
                self.assertEqual(run.call_count,2)
            annotation=meta['pages'][0]['inspection']['annotations'][0]
            self.assertEqual(annotation['internal_name'],'Draft')
            self.assertEqual(annotation['appearance_text'],'Approved With Comments')
            self.assertEqual(annotation['metadata_authority'],'NOT_ESTABLISHED')
            self.assertEqual(annotation['verification_state'],'REVIEW_REQUIRED')

    def test_timeout_remains_unresolved_without_fake_stamp_reading(self):
        import subprocess
        with tempfile.TemporaryDirectory() as root:
            path=Path(root)/'source.pdf';path.write_bytes(b'synthetic-source')
            page=self.page()
            class Doc:
                def __enter__(self):return self
                def __exit__(self,*args):pass
                def __getitem__(self,index):return page
            meta={'pages':[{'page':1}]}
            with patch('fitz.open',return_value=Doc()),patch('subprocess.run',side_effect=subprocess.TimeoutExpired('worker',1)):
                self.assertGreater(supplement_inspection(str(path),meta),0)
            annotation=meta['pages'][0]['inspection']['annotations'][0]
            self.assertEqual(annotation['appearance_status'],'FAILED_REVIEW_REQUIRED')
            self.assertNotIn('appearance_text',annotation)

    def test_answer_preserves_conditional_stamp_and_metadata_disagreement(self):
        with tempfile.TemporaryDirectory() as root:
            path=str(Path(root)/'source.pdf')
            annotation=inspect_page(self.page())['annotations'][0]
            annotation['appearance_text']='Approved With Comments'
            Path(path+'.index.json').write_text(json.dumps({'pages':[{'page':2,'inspection':{'annotations':[annotation]}}]}))
            docs=[{'filename':'source.pdf','path':path,'status':'ready_with_warnings'}]
            result=inspection_answer('approval status page 2',docs)
            self.assertIn('Approved With Comments',result['answer'])
            self.assertIn('Draft',result['answer'])
            self.assertIn('REVIEW_REQUIRED',result['answer'])
            self.assertEqual(result['sources'][0]['page'],2)
            self.assertEqual(inspection_answer('review comments page 1',docs)['status'],'NOT_FOUND')
            self.assertIsNone(inspection_answer('approved GFA Tower 2',docs))
            self.assertEqual(inspection_answer('approval status',[dict(docs[0],status='processing')])['status'],'NOT_FOUND')
