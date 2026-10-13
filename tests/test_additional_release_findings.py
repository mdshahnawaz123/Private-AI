import ast,json,os,tempfile,unittest
from pathlib import Path
from types import SimpleNamespace
from intelligence.exact_answers import exact_answer
from intelligence.source_semantics import native_revision,explicit_states

class AdditionalReleaseFindings(unittest.TestCase):
    def test_commercial_total_cannot_inherit_residential_scope(self):
        with tempfile.TemporaryDirectory() as root:
            path=Path(root)/'summary.pdf';path.write_bytes(b'synthetic')
            table='| UNIT TYPE SUMMARY | |\n| ITEM | NO. |\n| Residential Units: | |\n| Apartments | 71 |\n| TOTAL | 71 |\n| Retail Units: | 7 |\n| F&B Units: | 4 |\n| TOTAL | 11 |'
            Path(str(path)+'.index.json').write_text(json.dumps({'pages':[{'page':1,'tables':table}]}))
            docs=[{'filename':path.name,'path':str(path)}]
            result=exact_answer('How many residential units are there?',docs)
            self.assertEqual(result['status'],'SUCCESS')
            self.assertEqual(result['facts'][0]['value'],'71')
            self.assertEqual(exact_answer('How many F&B units are there?',docs)['facts'][0]['value'],'4')

    def test_revision_number_label_is_not_a_conflicting_revision(self):
        meta={'pages':[{'page':1,'text':'Document Revision No.:\n3',
            'tables':'| Document Revision No.: | | 3 |\n| Revision No. | | |'}]}
        self.assertEqual(native_revision(meta),'3')

    def test_pressure_unit_changes_are_rejected(self):
        from intelligence.answer_guard import publication_issues
        evidence='[SOURCE: s.pdf | PAGE 1]\nDesign pressure: 250 Pa.'
        sources=[{'source':'s.pdf','page':1}]
        self.assertEqual(publication_issues('Pressure: 250 Pa. [SOURCE: s.pdf | PAGE 1]',evidence,sources),[])
        self.assertIn('Value/unit pair absent from cited page excerpts',publication_issues('Pressure: 250 psi. [SOURCE: s.pdf | PAGE 1]',evidence,sources))

    def test_native_draft_status_is_reported_without_construction_approval(self):
        with tempfile.TemporaryDirectory() as root:
            path=Path(root)/'native-a.pdf';path.write_bytes(b'synthetic')
            side=Path(str(path)+'.index.json')
            side.write_text(json.dumps({'pages':[{'page':1,'text':'Revision B. Status: Draft.'}]}))
            docs=[{'filename':path.name,'path':str(path)}]
            result=exact_answer('Is revision B approved for construction?',docs)
            self.assertEqual(result['status'],'SUCCESS')
            self.assertIn('status: DRAFT',result['answer'])
            self.assertIn('does not independently certify',result['answer'])
            self.assertEqual(exact_answer('Is revision C approved for construction?',docs)['status'],'NOT_FOUND')
            side.write_text(json.dumps({'pages':[{'page':1,'text':'Revision B. Status: Approved.\nStatus: Pending.'}]}))
            self.assertEqual(exact_answer('Is revision B approved for construction?',docs)['status'],'AMBIGUOUS')

    def test_requested_project_code_cannot_use_other_project_value(self):
        with tempfile.TemporaryDirectory() as root:
            docs=[]
            for code,value in [('SYNTH-A','123.45'),('SYNTH-B','987.65')]:
                path=Path(root)/(code+'.pdf');path.write_bytes(b'synthetic')
                Path(str(path)+'.index.json').write_text(json.dumps({'pages':[{'page':1,'text':'Project code: '+code,
                    'tables':'| Metric | SQ.M. |\n| --- | --- |\n| Plot Area | '+value+' |'}]}))
                docs.append({'filename':path.name,'path':str(path)})
            refused=exact_answer('What is the Plot Area of project SYNTH-B?',docs[:1])
            self.assertEqual(refused['status'],'NOT_FOUND')
            self.assertNotIn('123.45',refused['answer'])
            matched=exact_answer('What is the Plot Area of project SYNTH-B?',docs)
            self.assertEqual(matched['facts'][0]['value'],'987.65')

    def test_structured_project_id_wins_over_misordered_flattened_text(self):
        from intelligence.source_semantics import native_project_codes
        meta={'pages':[{'page':1,'text':'Project ID:\n10',
            'tables':'| Project ID: | | C3045 |'}]}
        self.assertEqual(native_project_codes(meta),{'C3045'})

    def test_conflicting_structured_project_ids_are_not_collapsed(self):
        from intelligence.source_semantics import native_project_codes
        meta={'pages':[{'page':1,'tables':'| Project ID: | C3045 |\n| Project Code: | C3085 |'}]}
        self.assertEqual(native_project_codes(meta),{'C3045','C3085'})

    def test_full_bua_per_level_breakdown_is_supported_and_cited(self):
        table='''BUILT-UP AREA BREAKDOWN (Per Level)
| ITEM | LEVEL | SQ.M | SQ.FT |
| --- | --- | --- | --- |
| 1 | Basement 1 | 10.00 | 107.64 |
| 2 | Ground Floor | 20.00 | 215.28 |
| TOTAL | | 30.00 | 322.92 |'''
        with tempfile.TemporaryDirectory() as root:
            path=Path(root)/'area.pdf';path.write_bytes(b'synthetic')
            Path(str(path)+'.index.json').write_text(json.dumps({'pages':[{'page':1,'tables':table}]}))
            docs=[{'filename':path.name,'path':str(path)}]
            result=exact_answer('Send me details of built-up area breakdown per level',docs)
            self.assertEqual(result['status'],'SUCCESS')
            self.assertIn('Basement 1',result['answer'])
            self.assertIn('Ground Floor',result['answer'])
            self.assertIn('30.00 sqm',result['answer'])
            self.assertIn('| ITEM | LEVEL | AREA (SQ M) | AREA (SQ FT) |',result['answer'])
            self.assertIn('Adding the displayed level figures does not reproduce it exactly',result['answer'])
            from intelligence.answer_publication import validate_precomputed_answer
            published,issues,allowed=validate_precomputed_answer(result['answer'],docs,result['sources'],
                'Send me details of built-up area breakdown per level')
            self.assertEqual(issues,[])
            self.assertEqual(allowed,[{'source':path.name,'page':1}])

    def test_full_bua_breakdown_rejects_missing_unit_or_conflicting_total(self):
        incomplete='''BUILT-UP AREA BREAKDOWN (Per Level)
| ITEM | LEVEL | SQ.M | SQ.FT |
| --- | --- | --- | --- |
| 1 | Ground Floor | 20.00 | |
| TOTAL | | 20.00 | 215.28 |'''
        conflicting='''BUILT-UP AREA BREAKDOWN (Per Level)
| ITEM | LEVEL | SQ.M | SQ.FT |
| --- | --- | --- | --- |
| 1 | Ground Floor | 20.00 | 215.28 |
| TOTAL | | 21.00 | 226.04 |'''
        for table in (incomplete,conflicting):
            with tempfile.TemporaryDirectory() as root:
                path=Path(root)/'area.pdf';path.write_bytes(b'synthetic')
                Path(str(path)+'.index.json').write_text(json.dumps({'pages':[{'page':1,'tables':table}]}))
                result=exact_answer('built-up area breakdown per level',
                    [{'filename':path.name,'path':str(path)}])
                self.assertIn(result['status'],{'NOT_FOUND','AMBIGUOUS'})

    def test_parking_calculation_returns_cited_table_and_checks_total(self):
        table='''| PARKING/GARBAGE/LIFT SUMMARY | | | |
| --- | --- | --- | --- |
| PARKING CALCULATION | | | |
| ITEM | NO. | REQUIRED | PROPOSED |
| Units less than 150 sqm | 8 | 8 | 9 |
| Tandem | | 2 | 1 |
| VAN PARKING | | - | 1 |
| TOTAL | | 10 | 11 |
| Bicycle Parking | | 3 RACKS | 3 RACKS |
| Notes:- POD and EV parking are distributed near each building | | | |'''
        with tempfile.TemporaryDirectory() as root:
            path=Path(root)/'parking.pdf';path.write_bytes(b'synthetic')
            sidecar={'pages':[{'page':1,'text':'Project ID: C3045','tables':table}]}
            Path(str(path)+'.index.json').write_text(json.dumps(sidecar),encoding='utf-8')
            docs=[{'filename':path.name,'path':str(path)}]
            question='Regarding parking.pdf: PARKING CALCULATION for project C3045'
            result=exact_answer(question,docs)
            self.assertEqual(result['status'],'SUCCESS')
            self.assertIn('| ITEM | NO. | REQUIRED | PROPOSED |',result['answer'])
            self.assertIn('| VAN PARKING',result['answer'])
            self.assertIn('3 RACKS',result['answer'])
            self.assertIn('matching the two printed totals',result['answer'])
            from intelligence.answer_publication import validate_precomputed_answer
            _,issues,_=validate_precomputed_answer(result['answer'],docs,result['sources'],question)
            self.assertEqual(issues,[])
            sidecar['pages'][0]['tables']=table.replace('| TOTAL | | 10 | 11 |','| TOTAL | | 12 | 11 |')
            Path(str(path)+'.index.json').write_text(json.dumps(sidecar),encoding='utf-8')
            self.assertEqual(exact_answer(question,docs)['status'],'AMBIGUOUS')

    def test_proposed_numeric_row_is_data_and_retains_disposition(self):
        with tempfile.TemporaryDirectory() as root:
            path=Path(root)/'native-a.pdf';path.write_bytes(b'synthetic')
            Path(str(path)+'.index.json').write_text(json.dumps({'pages':[{'page':1,
                'text':'Drawing SYNTH-060. Revision B. Status: Proposed.',
                'tables':'| Metric | SQ.M. | Qualification |\n| --- | --- | --- |\n| Plot Area | 987.65 | Proposed |\n| GFA Allowed | 500.00 | Limit |'}]}))
            result=exact_answer('What is the Plot Area?',[{'filename':path.name,'path':str(path)}])
            self.assertEqual(result['status'],'SUCCESS')
            self.assertEqual(result['facts'][0]['value'],'987.65')
            self.assertEqual(result['facts'][0]['revision'],'B')
            self.assertEqual(result['facts'][0]['qualification'],['PROPOSED'])
            self.assertIn('status: PROPOSED',result['answer'])

    def test_native_revision_conflicts_and_vision_are_not_inferred(self):
        self.assertEqual(native_revision({'pages':[{'page':1,'text':'Revision B.'}]}),'B')
        self.assertIsNone(native_revision({'pages':[{'page':1,'vision':'Revision B.'}]}))
        self.assertIsNone(native_revision({'pages':[{'page':1,'text':'Revision B. Revision C.'}]}))
        self.assertEqual(explicit_states('Revision B. Status: Draft.'),{'DRAFT'})
        self.assertEqual(explicit_states('Revision B. Status: Not Approved.'),{'UNKNOWN'})

    def test_source_citation_revision_uses_page_not_filename(self):
        with tempfile.TemporaryDirectory() as root:
            path=Path(root)/'native-a.pdf';path.write_bytes(b'synthetic')
            Path(str(path)+'.index.json').write_text(json.dumps({'pages':[{'page':1,'text':'Revision B.'}]}))
            tree=ast.parse((Path(__file__).resolve().parents[1]/'main.py').read_text(encoding='utf-8'))
            node=next(n for n in tree.body if isinstance(n,ast.FunctionDef) and n.name=='resolve_sources')
            import meta_parse
            scope={'os':os,'DOCS_DIR':root,'meta_parse':meta_parse,'db':SimpleNamespace(list_documents=lambda p:[{'filename':path.name,'path':str(path)}])}
            exec(compile(ast.Module(body=[node],type_ignores=[]),'source-resolver','exec'),scope)
            source=scope['resolve_sources']('SYNTH',[{'source':path.name,'page':1}])[0]
            self.assertEqual(source['revision'],'B')
            self.assertEqual(source['filename_revision_hint'],'A')

    def test_withheld_response_is_not_high_confidence(self):
        from response_schema import build_structured_response
        result=build_structured_response('approval','I could not verify the generated answer against the retrieved source pages.',
            [{'filename':'s.pdf','page':1}],focus_doc_used=True)
        self.assertEqual(result['type'],'not_found')
        self.assertEqual(result['confidence'],'low')

    def test_successful_publications_bound_only_owned_backup_generations(self):
        tree=ast.parse((Path(__file__).resolve().parents[1]/'main.py').read_text(encoding='utf-8'))
        node=next(n for n in tree.body if isinstance(n,ast.FunctionDef) and n.name=='_persist_index_generation')
        with tempfile.TemporaryDirectory() as root:
            scope={'os':os,'INDEX_DIR':root,'embedder':SimpleNamespace(model='synthetic')}
            exec(compile(ast.Module(body=[node],type_ignores=[]),'publisher','exec'),scope)
            def save(directory):
                p=Path(directory);p.mkdir();(p/'index.faiss').write_bytes(b'faiss');(p/'index.pkl').write_bytes(b'pickle')
            candidate=SimpleNamespace(save_local=save,index=SimpleNamespace(d=2,ntotal=1))
            unrelated=Path(root)/'SYNTH.previous-user-backup';unrelated.mkdir();(unrelated/'keep').write_text('user backup')
            for _ in range(6):scope['_persist_index_generation']('SYNTH',candidate)
            owned=[p for p in Path(root).glob('SYNTH.previous-*') if p!=unrelated]
            self.assertEqual(len(owned),2)
            self.assertTrue((Path(root)/'SYNTH/generation.json').is_file())
            self.assertEqual((unrelated/'keep').read_text(),'user backup')
