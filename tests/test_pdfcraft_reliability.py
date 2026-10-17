import io
import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch
import pymupdf as fitz
from services.pdf_service import PdfService


class ServiceTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory(dir=Path(__file__).resolve().parents[1]/'output');self.addCleanup(self.tmp.cleanup)
        self.path=Path(self.tmp.name)/'source.pdf'
        doc=fitz.open();page=doc.new_page(width=400,height=300);page.insert_text((40,60),'SECRET engineering fixture');doc.save(self.path);doc.close()

    def test_same_path_annotation(self):
        PdfService.add_annotation(str(self.path),str(self.path),'rect',1,[20,20,100,90])
        with fitz.open(self.path) as doc:self.assertEqual(len(list(doc[0].annots())),1)

    def test_watermark(self):
        PdfService.add_watermark(str(self.path),str(self.path),text='REVIEW',opacity=.2)
        with fitz.open(self.path) as doc:self.assertIn('REVIEW',doc[0].get_text())

    def test_security_and_unlock(self):
        PdfService.set_security(str(self.path),str(self.path),'test-password')
        with fitz.open(self.path) as doc:
            self.assertTrue(doc.is_encrypted);self.assertTrue(doc.authenticate('test-password'))
        PdfService.remove_security(str(self.path),str(self.path),'test-password')
        with fitz.open(self.path) as doc:self.assertFalse(doc.is_encrypted)

    def test_unknown_annotation_rejected_unchanged(self):
        before=self.path.read_bytes()
        with self.assertRaises(ValueError):PdfService.add_annotation(str(self.path),str(self.path),'unsupported',1,[0,0,10,10])
        self.assertEqual(before,self.path.read_bytes())

    def test_failed_atomic_publish_preserves_working_file(self):
        before=self.path.read_bytes()
        with patch('services.pdf_service.os.replace',side_effect=OSError('failure')):
            with self.assertRaises(OSError):PdfService.add_annotation(str(self.path),str(self.path),'rect',1,[0,0,10,10])
        self.assertEqual(before,self.path.read_bytes())

    def test_redaction_rotated_encrypted_and_attachment_cleanup(self):
        doc=fitz.open(self.path)
        page=doc[0];box=page.search_for('SECRET')[0];page.set_rotation(90)
        visual=list(box*page.rotation_matrix)
        doc.embfile_add('attached.txt',b'SECRET')
        PdfService._save_atomic(doc,str(self.path),encryption=fitz.PDF_ENCRYPT_AES_256,user_pw='test',owner_pw='owner')
        PdfService.apply_permanent_redactions(str(self.path),str(self.path),[{'page':1,'rect':visual}],password='test')
        with fitz.open(self.path) as doc:
            self.assertTrue(doc.authenticate('test'))
            self.assertNotIn('SECRET',doc[0].get_text());self.assertEqual(doc.embfile_names(),[])

    def test_invalid_redaction_preserves_input(self):
        before=self.path.read_bytes()
        with self.assertRaises(ValueError):
            PdfService.apply_permanent_redactions(str(self.path),str(self.path),[{'page':9,'rect':[0,0,10,10]}])
        self.assertEqual(before,self.path.read_bytes())

    def test_native_markup_roundtrip_replace_and_delete(self):
        shapes=[{'id':'cloud1','type':'cloud','page':1,'x':30,'y':30,'w':80,'h':40,'color':'#ff0000','text':'Review'},
                {'id':'arrow1','type':'arrow','page':1,'start':{'x':20,'y':20},'end':{'x':80,'y':80},'color':'#00ff00'},
                {'id':'distance1','type':'distance','page':1,'points':[{'x':10,'y':10},{'x':100,'y':10}],'measurement':'1 m','color':'#0080ff'}]
        PdfService.synchronize_markups(str(self.path),shapes,'Actual Reviewer')
        info=PdfService.inspect_pdf(str(self.path));self.assertEqual(len(info['markups']),3)
        self.assertEqual(info['markups'][0]['author'],'Actual Reviewer')
        with fitz.open(self.path) as doc:self.assertEqual(len(list(doc[0].annots())),3)
        PdfService.synchronize_markups(str(self.path),shapes[:1],'Actual Reviewer')
        with fitz.open(self.path) as doc:self.assertEqual(len(list(doc[0].annots())),1)
        PdfService.synchronize_markups(str(self.path),[],'Actual Reviewer')
        with fitz.open(self.path) as doc:self.assertEqual(len(list(doc[0].annots())),0)

    def test_all_current_markup_types(self):
        shapes=[]
        for kind in ['rect','highlight','note','text','bubble','count','symbol','pen','stamp','ellipse','area','callout']:
            shapes.append({'id':kind,'type':kind,'page':1,'x':20,'y':20,'w':80,'h':40,'cx':80,'cy':80,'rx':30,'ry':20,'text':'Review',
                           'points':[{'x':20,'y':20},{'x':80,'y':20},{'x':80,'y':80}],
                           'box':{'x':80,'y':80,'w':100,'h':50},'arrow':{'x':20,'y':20},'color':'#ff0000'})
        PdfService.synchronize_markups(str(self.path),shapes,'Reviewer')
        with fitz.open(self.path) as doc:self.assertEqual(len(list(doc[0].annots())),len(shapes))

    def test_rotated_page_dimensions_and_markup_roundtrip(self):
        doc=fitz.open(self.path);doc[0].set_rotation(90);PdfService._save_atomic(doc,str(self.path))
        info=PdfService.inspect_pdf(str(self.path));self.assertEqual((info['pages'][0]['width'],info['pages'][0]['height']),(300,400))
        PdfService.synchronize_markups(str(self.path),[{'id':'box','type':'rect','page':1,'x':10,'y':20,'w':40,'h':30,'color':'#ff0000'}],'Reviewer')
        with fitz.open(self.path) as doc:
            page=doc[0];annotation=next(page.annots());expected=fitz.Rect(10,20,50,50)*page.derotation_matrix
            self.assertLess(abs(annotation.rect.x0-expected.x0),3)

    def test_organizer_remaps_markups_and_bookmarks(self):
        doc=fitz.open(self.path);doc.new_page(width=400,height=300);doc.set_toc([[1,'First',1],[1,'Second',2]]);PdfService._save_atomic(doc,str(self.path))
        PdfService.synchronize_markups(str(self.path),[{'id':'box','type':'rect','page':1,'x':10,'y':20,'w':40,'h':30,'color':'#ff0000'}],'Reviewer')
        PdfService.organize_pages(str(self.path),str(self.path),{'reorder':[2,1],'rotate':[{'page':2,'angle':90}]})
        info=PdfService.inspect_pdf(str(self.path));self.assertEqual(info['markups'][0]['page'],2)
        with fitz.open(self.path) as doc:self.assertEqual(doc.get_toc()[0][2],2)

    def test_render_pixel_budget(self):
        doc=fitz.open();doc.new_page(width=10000,height=10000);large=Path(self.tmp.name)/'large.pdf';doc.save(large);doc.close()
        with self.assertRaisesRegex(ValueError,'pixels'):PdfService.render_page(str(large),1,zoom=6)


class ApiTests(unittest.TestCase):
    def setUp(self):
        from fastapi import FastAPI,HTTPException
        from fastapi.testclient import TestClient
        import services.pdf_api as api
        self.api=api
        self.tmp=tempfile.TemporaryDirectory(dir=Path(__file__).resolve().parents[1]/'output');self.addCleanup(self.tmp.cleanup)
        root=Path(self.tmp.name);(root/'cache').mkdir();api._PDF_SESSION_CACHE.clear();api._PDF_LOCKS.clear()
        self.root=root
        for target,value in [('services.pdf_api.PDF_CACHE_DIR',str(root/'cache')),('services.pdf_api.db.DATA_DIR',str(root))]:
            patcher=patch(target,value);patcher.start();self.addCleanup(patcher.stop)
        def project_guard(request,project):
            user=api.auth.require_user(request)
            if project!='Allowed':raise HTTPException(403,'No access')
            return user
        patcher=patch('services.pdf_api.auth.require_project',side_effect=project_guard);patcher.start();self.addCleanup(patcher.stop)
        for name,value in [('folder_access',(True,[])),('list_folders',[]),('record_document',None)]:
            patcher=patch('services.pdf_api.db.'+name,return_value=value);patcher.start();self.addCleanup(patcher.stop)
        app=FastAPI()
        @app.middleware('http')
        async def actor(request,call_next):
            identity=request.headers.get('x-test-user')
            request.state.user={'id':int(identity),'username':'Reviewer','role':'user'} if identity else None
            return await call_next(request)
        app.include_router(api.pdf_router);self.client=TestClient(app);self.addCleanup(self.client.close)
        doc=fitz.open();doc.new_page().insert_text((40,60),'SECRET');self.pdf=doc.tobytes();doc.close()

    def upload(self):
        response=self.client.post('/api/v1/pdf/open',headers={'x-test-user':'1'},files={'file':('fixture.pdf',self.pdf,'application/pdf')})
        self.assertEqual(response.status_code,200,response.text);return response.json()['doc_id']

    def test_upload_render_export_owner_and_path_guards(self):
        identity=self.upload()
        self.assertEqual(self.client.get('/api/v1/pdf/render-page',params={'doc_id':identity},headers={'x-test-user':'1'}).status_code,200)
        self.assertEqual(self.client.get('/api/v1/pdf/export',params={'doc_id':identity},headers={'x-test-user':'2'}).status_code,403)
        self.assertEqual(self.client.get('/api/v1/pdf/export',params={'doc_id':'../source'},headers={'x-test-user':'1'}).status_code,400)
        self.assertEqual(self.client.get('/api/v1/pdf/export',params={'doc_id':identity}).status_code,401)

    def test_redact_then_render_and_export(self):
        identity=self.upload();headers={'x-test-user':'1'}
        r=self.client.post('/api/v1/pdf/redact-apply',headers=headers,json={'doc_id':identity,'redactions':[{'page':1,'rect':[0,0,200,100]}]})
        self.assertEqual(r.status_code,200,r.text)
        result=self.client.get('/api/v1/pdf/export',headers=headers,params={'doc_id':identity})
        self.assertEqual(result.status_code,200)
        with fitz.open(stream=result.content,filetype='pdf') as doc:self.assertNotIn('SECRET',doc[0].get_text())

    def test_save_copy_does_not_overwrite_original(self):
        identity=self.upload();folder=self.root/'docs'/'Allowed'/'Documents';folder.mkdir(parents=True)
        original=folder/'fixture.pdf';original.write_bytes(self.pdf)
        r=self.client.post('/api/v1/pdf/save-to-project',headers={'x-test-user':'1'},json={'doc_id':identity,'project':'Allowed','filename':'fixture.pdf'})
        self.assertEqual(r.status_code,200,r.text);self.assertEqual(original.read_bytes(),self.pdf)
        self.assertNotEqual(r.json()['saved_path'],str(original))

    def test_unauthorized_and_traversal_save(self):
        identity=self.upload()
        for project,folder in [('Other','Documents'),('Allowed','../escape')]:
            r=self.client.post('/api/v1/pdf/save-to-project',headers={'x-test-user':'1'},json={'doc_id':identity,'project':project,'folder':folder,'filename':'copy.pdf'})
            self.assertIn(r.status_code,(400,403))

    def test_native_markups_export_and_reopen(self):
        identity=self.upload();headers={'x-test-user':'1'}
        markup={'id':'review1','page':1,'type':'cloud','x':10,'y':10,'w':80,'h':80,'color':'#ff0000','text':'Review'}
        r=self.client.post('/api/v1/pdf/markups',headers=headers,json={'doc_id':identity,'markups':[markup]})
        self.assertEqual(r.status_code,200,r.text)
        exported=self.client.get('/api/v1/pdf/export',headers=headers,params={'doc_id':identity})
        reopened=self.client.post('/api/v1/pdf/open',headers=headers,files={'file':('review.pdf',exported.content,'application/pdf')})
        self.assertEqual(len(reopened.json()['info']['markups']),1)

    def test_pdf_qa_unsupported_answer_is_withheld(self):
        identity=self.upload()
        draft={'answer':'The beam depth is 999 mm [Page 1].','cited_pages':[1],'highlights':[]}
        with patch('services.pdf_api.PdfService.ask_document',return_value=draft):
            response=self.client.post('/api/v1/pdf/ask',headers={'x-test-user':'1'},json={'doc_id':identity,'question':'What is the beam depth?'})
        self.assertEqual(response.status_code,200,response.text)
        self.assertEqual(response.json()['verification'],'WITHHELD')
        self.assertNotIn('999',response.json()['answer'])

    def test_security_route_then_render(self):
        identity=self.upload();headers={'x-test-user':'1'}
        result=self.client.post('/api/v1/pdf/security',headers=headers,json={'doc_id':identity,'user_password':'test'})
        self.assertEqual(result.status_code,200,result.text)
        result=self.client.get('/api/v1/pdf/render-page',headers=headers,params={'doc_id':identity})
        self.assertEqual(result.status_code,200,result.text)

    def test_encrypted_session_thumbnail_search_and_markups(self):
        identity=self.upload();headers={'x-test-user':'1'}
        self.assertEqual(self.client.post('/api/v1/pdf/security',headers=headers,json={'doc_id':identity,'user_password':'test'}).status_code,200)
        for endpoint,params in [('thumbnail',{}),('search',{'q':'SECRET'})]:
            response=self.client.get('/api/v1/pdf/'+endpoint,headers=headers,params={'doc_id':identity,**params})
            self.assertEqual(response.status_code,200,response.text)
        response=self.client.post('/api/v1/pdf/markups',headers=headers,json={'doc_id':identity,'markups':[]})
        self.assertEqual(response.status_code,200,response.text)

    def test_folder_denial_on_open(self):
        folder=self.root/'docs'/'Allowed'/'Private';folder.mkdir(parents=True);(folder/'private.pdf').write_bytes(self.pdf)
        with patch('services.pdf_api.db.folder_access',return_value=(False,[])),patch('services.pdf_api.db.document_folder_id_for_path',return_value=5):
            result=self.client.post('/api/v1/pdf/open',headers={'x-test-user':'1'},data={'project':'Allowed','rel':'Private/private.pdf'})
        self.assertEqual(result.status_code,403)
