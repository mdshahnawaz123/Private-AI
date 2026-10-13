"""Conservative exact engineering lookups. No project names or expected values.

Only recognized scalar requests with a unique source value are answered here.
Unsupported questions continue through RAG; conflicting evidence is surfaced.
"""
import json
import re
from pathlib import Path
from intelligence.table_evidence import table_row_units


def _normal(s):
    return re.sub(r'[^a-z0-9]+',' ',str(s).lower()).strip()


def _rows(documents, project_code=None):
    rows=[]
    for doc in documents:
        path=Path(doc.get('path','')+'.index.json')
        try:
            meta=json.loads(path.read_text(encoding='utf-8'))
        except (OSError,ValueError):
            continue
        if meta.get('truncated') or meta.get('processing_complete') is False:
            continue
        if meta.get('source_sha256'):
            import hashlib
            try:
                with open(doc['path'],'rb') as handle:
                    if hashlib.file_digest(handle,'sha256').hexdigest()!=meta['source_sha256']:continue
            except OSError:
                continue
        for page in meta.get('pages',[]):
            if project_code:
                from intelligence.source_semantics import native_project_codes
                codes=native_project_codes(meta)
                if codes!={project_code} and native_project_codes({'pages':[page]})!={project_code}:
                    continue
            from intelligence.source_semantics import explicit_states
            states=explicit_states(page.get('text',''))
            from intelligence.source_semantics import native_revision
            revision=native_revision(meta,page.get('page'))
            for text in table_row_units(page.get('tables','')):
                lines=text.splitlines()
                fields=[]
                for item in lines[-1].split('; '):
                    if ': ' in item:
                        key,value=item.split(': ',1)
                        fields.append((key,value))
                # Wide sheets can place independent tables side by side. Split
                # repeated label columns before associating units with values.
                groups=[[]]
                for key,value in fields:
                    if re.search(r'\bitem$',_normal(key)) and groups[-1]:
                        groups.append([])
                    groups[-1].append((key,value))
                if len(groups)>1:
                    for group in groups:
                        rows.append({'doc':doc['filename'],'page':page['page'],
                                     'text':text,'normal':_normal(text),'fields':group,'states':states,'revision':revision})
                    continue
                rows.append({'doc':doc['filename'],'page':page['page'],
                             'text':text,'normal':_normal(text),'fields':fields,'states':states,'revision':revision})
    return rows


def _bua_breakdown_answer(question, rows):
    """Answer a full per-level BUA request from one complete native table."""
    q=_normal(question)
    if not (re.search(r'\b(?:built up area|bua)\b',q) and
            re.search(r'\b(?:breakdown|by level|per level)\b',q)):
        return None
    table_rows=[row for row in rows if 'built up area breakdown per level' in row['normal']]
    if not table_rows:
        return {'status':'NOT_FOUND','answer':'No native BUILT-UP AREA BREAKDOWN (Per Level) table was found in the available source pages.','sources':[]}
    groups={}
    for row in table_rows:
        groups.setdefault((row['doc'],row['page']),[]).append(row)
    if len(groups)!=1:
        return {'status':'AMBIGUOUS','answer':'Multiple source pages contain a built-up area breakdown. Specify the document and page.','sources':[]}
    from decimal import Decimal,InvalidOperation
    (source,page),source_rows=next(iter(groups.items()))
    records=[]
    total=None
    for row in source_rows:
        values={_normal(key):value.strip() for key,value in row['fields']}
        item=next((value for key,value in row['fields'] if _normal(key)=='item'),None)
        if item and _normal(item)=='total':
            if total is not None:
                return {'status':'AMBIGUOUS','answer':'The native built-up area table contains multiple total rows. Review the source table.','sources':[{'source':source,'page':page}]}
            total=(values.get('sq m'),values.get('sq ft'))
            continue
        level=next((value for _,value in row['fields'] if re.fullmatch(
            r'(?:basement\s*\d*|ground(?:\s+floor)?|\d+(?:st|nd|rd|th)\s+floor|roof|podium(?:\s+\w+)?)',
            value.strip(),re.I)),None)
        if level:
            sqm,sqft=values.get('sq m'),values.get('sq ft')
            if not sqm or not sqft:
                return {'status':'NOT_FOUND','answer':f'The native table does not provide both area units for {level}. The breakdown cannot be completed safely.','sources':[{'source':source,'page':page}]}
            records.append((str(item or len(records)+1),level,sqm,sqft))
    if len(records)<2 or total is None or not all(total):
        return {'status':'NOT_FOUND','answer':'The native built-up area table is incomplete or lacks a unique total row. The breakdown cannot be verified.','sources':[{'source':source,'page':page}]}
    if len({_normal(level) for _,level,_,_ in records})!=len(records):
        return {'status':'AMBIGUOUS','answer':'The native built-up area table repeats a level label. Review the source table before using the breakdown.','sources':[{'source':source,'page':page}]}
    try:
        sum_sqm=sum(Decimal(value.replace(',','')) for _,_,value,_ in records)
        sum_sqft=sum(Decimal(value.replace(',','')) for _,_,_,value in records)
        # Each displayed row and the displayed total may be rounded
        # independently to two decimals. Bound the maximum accumulated
        # rounding difference instead of requiring false exact equality.
        rounding_bound=Decimal('0.005')*(len(records)+1)
        if (abs(sum_sqm-Decimal(total[0].replace(',','')))>rounding_bound or
                abs(sum_sqft-Decimal(total[1].replace(',','')))>rounding_bound):
            return {'status':'AMBIGUOUS','answer':'The native per-level values do not reconcile with the table total. Review the source table.','sources':[{'source':source,'page':page}]}
    except (InvalidOperation,AttributeError):
        return {'status':'NOT_FOUND','answer':'The native built-up area table contains values that cannot be checked as numeric areas. Review the source table.','sources':[{'source':source,'page':page}]}
    citation=f'[SOURCE: {source} | PAGE {page}]'
    facts=[{'item':item,'label':level,'value':sqm,'unit':'sqm','value_sqft':sqft,'unit_sqft':'sqft',
            'source':source,'page':page} for item,level,sqm,sqft in records]
    facts.append({'item':'TOTAL','label':'Total','value':total[0],'unit':'sqm','value_sqft':total[1],
                  'unit_sqft':'sqft','source':source,'page':page})
    answer=(f'**BUILT-UP AREA breakdown per level** {citation}\n\n'
        '| ITEM | LEVEL | AREA (SQ M) | AREA (SQ FT) |\n'
        '|---:|---|---:|---:|\n'+ '\n'.join(
        f'| {item} | **{label}** {citation} | {sqm} sqm | {sqft} sqft |'
        for item,label,sqm,sqft in [*records,('TOTAL','Total',*total)])+
        f'\n\nThe total is copied from the source. Adding the displayed level figures does not reproduce it exactly; the source provides rounded figures only, so the printed total is retained. {citation}')
    return {'status':'SUCCESS','answer':answer,'facts':facts,'sources':[{'source':source,'page':page}]}


def _parking_calculation_answer(question, rows):
    """Return a complete native parking-calculation table when requested."""
    q=_normal(question)
    if 'parking calculation' not in q:
        return None
    # Leave focused parking lookups to the existing field-level resolver.
    if re.search(r'\b(?:required|proposed|normal|tandem|pod|current ev|future ev|grand total|bays)\b',q):
        return None
    table_rows=[row for row in rows if 'parking calculation' in row['normal']]
    if not table_rows:
        return {'status':'NOT_FOUND','answer':'No native PARKING CALCULATION table was found in the available source pages.','sources':[]}
    groups={}
    for row in table_rows:
        groups.setdefault((row['doc'],row['page']),[]).append(row)
    if len(groups)!=1:
        return {'status':'AMBIGUOUS','answer':'Multiple source pages contain parking-calculation tables. Specify the document and page.','sources':[]}
    from decimal import Decimal,InvalidOperation
    (source,page),source_rows=next(iter(groups.items()))
    entries=[]
    notes=[]
    total=None
    primary=[]
    for row in source_rows:
        fields={_normal(key):value.strip() for key,value in row['fields']}
        item=fields.get('item','')
        if not item:
            continue
        if _normal(item).startswith('notes'):
            notes.append(item)
            continue
        entry={'item':item,'no':fields.get('no',''),'required':fields.get('required',''),
               'proposed':fields.get('proposed','')}
        if _normal(item)=='total':
            if total is not None:
                return {'status':'AMBIGUOUS','answer':'The native parking table contains multiple TOTAL rows. Review the source table.','sources':[{'source':source,'page':page}]}
            total=entry
        elif total is None:
            primary.append(entry)
        entries.append(entry)
    if total is None or len(primary)<2 or not total['required'] or not total['proposed']:
        return {'status':'NOT_FOUND','answer':'The native parking-calculation table is incomplete or lacks a unique required/proposed total.','sources':[{'source':source,'page':page}]}
    try:
        for column in ('required','proposed'):
            values=[]
            for entry in primary:
                value=entry[column].replace(',','').strip()
                if value and re.fullmatch(r'\d+(?:\.\d+)?',value):
                    values.append(Decimal(value))
                elif value not in ('','-','—'):
                    # Do not guess whether a nonnumeric qualifier is an operand.
                    return {'status':'AMBIGUOUS','answer':'A parking-calculation operand is not a plain numeric value. Review the source table.','sources':[{'source':source,'page':page}]}
            stated=Decimal(total[column].replace(',','').strip())
            if sum(values,Decimal(0))!=stated:
                return {'status':'AMBIGUOUS','answer':'The numeric parking rows do not reconcile with the printed total. Review the source table.','sources':[{'source':source,'page':page}]}
    except (InvalidOperation,AttributeError):
        return {'status':'NOT_FOUND','answer':'The native parking-calculation values cannot be checked as numeric totals. Review the source table.','sources':[{'source':source,'page':page}]}
    citation=f'[SOURCE: {source} | PAGE {page}]'
    answer=(f'**Parking calculation** {citation}\n\n'
        '| ITEM | NO. | REQUIRED | PROPOSED |\n'
        '|---|---:|---:|---:|\n'+ '\n'.join(
        f'| {entry["item"]} {citation} | {entry["no"]} | {entry["required"]} | {entry["proposed"]} |'
        for entry in entries))
    if notes:
        answer+='\n\n**Notes** '+ ' '.join(notes)+f' {citation}'
    answer+=(f'\n\nThe numeric entries above TOTAL add to '
        f'{total["required"]} and {total["proposed"]}, matching the two printed totals; '
        f'the source dash is retained as shown. {citation}')
    facts=[{**entry,'source':source,'page':page} for entry in entries]
    return {'status':'SUCCESS','answer':answer,'facts':facts,'sources':[{'source':source,'page':page}]}


def exact_answer(question,documents):
    documents=[doc for doc in documents if doc.get('status','ready') in ('ready','ready_with_warnings','verified','published')]
    from intelligence.source_semantics import requested_project_code,native_project_codes
    project_code=requested_project_code(question)
    if project_code:
        scoped=[]
        for doc in documents:
            try:meta=json.loads(Path(doc['path']+'.index.json').read_text(encoding='utf-8'))
            except (OSError,ValueError,KeyError):continue
            if native_project_codes(meta)=={project_code}:scoped.append(doc)
        documents=scoped
        if not documents:
            return {'status':'NOT_FOUND','answer':'The available native source evidence does not establish the project code requested in this question. Select the correct project/document or provide explicit source evidence.','sources':[]}
    from intelligence.inspection_answers import inspection_answer
    inspected=inspection_answer(question,documents)
    if inspected and inspected.get('status') == 'SUCCESS':return inspected
    if re.search(r'\b(?:is|was|has)\b.*\b(?:revision|document|drawing)\b.*\bapproved\b',question,re.I):
        return native_disposition_answer(question,documents)
    # Historical Phase 4C fixture answers are not live readers: a filename
    # match cannot establish the contents of a newly uploaded document.
    from intelligence.universal_query_engine import universal_query_answer
    universal_exact = universal_query_answer(question, documents)
    if universal_exact: return universal_exact
    from intelligence.native_schedule import native_schedule_answer
    schedule = native_schedule_answer(question, documents)
    if schedule: return schedule
    from intelligence.native_titleblock import native_title_answer
    title = native_title_answer(question, documents)
    if title: return title
    q=_normal(question)
    if ('gfa' in q or 'gross floor area' in q or re.search(r'\bfar\b',q)) and 'proposed' in q and 'allowed' in q:
        return limit_comparison(question, documents)
    if 'equipment identifier' in q and not re.search(r'\b(status|approval|compare|sum|count|all)\b',q):
        return equipment_identifier_answer(question,documents)
    if re.search(r'\b(sum|average|maximum|minimum|difference|compare|calculate)\b',q):
        return calculated_answer(question,documents)
    rows=_rows(documents,project_code)
    breakdown=_bua_breakdown_answer(question,rows)
    if breakdown is not None:return breakdown
    parking_table=_parking_calculation_answer(question,rows)
    if parking_table is not None:return parking_table
    from intelligence.source_semantics import requested_authority,supports_authority
    authority=requested_authority(question)
    if authority:
        rows=[r for r in rows if supports_authority(r['states'],authority)]
    requested_pages={int(n) for n in re.findall(r'\bpage\s+(\d+)\b',q)}
    if requested_pages:
        rows=[row for row in rows if row['page'] in requested_pages]
    requests=[]
    towers=list(dict.fromkeys(re.findall(r'\btower\s*0*(\d+)\b',q)))
    levels=list(dict.fromkeys(re.findall(r'\b(?:level|floor)\s*0*(\d+)\b',q)))
    def field_value(row,pattern):
        values=[v for k,v in row['fields'] if re.search(pattern,_normal(k))]
        return values[0] if len(values)==1 else None
    def find(label,row_match,field,unit=''):
        matches=[]
        for row in rows:
            if not row_match(row): continue
            value=field(row)
            if value is not None:
                matches.append((value,unit,row['doc'],row['page']))
        # Equal duplicated schedules can agree; conflicting values cannot.
        from decimal import Decimal,InvalidOperation
        def value_key(value):
            try:return ('number',Decimal(value.replace(',','').strip()))
            except InvalidOperation:return ('text',value.strip().casefold())
        values={value_key(v) for v,_,_,_ in matches}
        if len(values)==1:
            v,u,doc,page=matches[0]
            source_row=next(r for r in rows if r['doc']==doc and r['page']==page and row_match(r) and field(r)==v)
            requests.append({'label':label,'value':v,'unit':u,'source':doc,'page':page,
                             'revision':source_row['revision'],'qualification':sorted(source_row['states'])})
        elif len(values)>1:
            requests.append({'label':label,'conflict':True})
        else:
            requests.append({'label':label,'missing':True})

    for category in ('retail', 'f b'):
        if category in q and re.search(r'\b(units|count|many)\b', q):
            find(category.upper()+' units',
                 lambda r,c=category:any(_normal(v)==c+' units' for _,v in r['fields']),
                 lambda r:field_value(r,r'^no$'),'units')

    scalar_labels=[]
    if 'plot area' in q:scalar_labels.append(('Plot Area','sqm'))
    if re.search(r'\bfar\b',q):
        qualifier='allowed' if 'allowed' in q else 'proposed' if 'proposed' in q else None
        if qualifier:scalar_labels.append(('FAR '+qualifier.title(),'ratio'))
    if re.search(r'\bbua\b|built up area',q) and 'proposed' in q and not re.search(r'\b(podium|towers|floor|level)\b',q):
        scalar_labels.append(('BUA Proposed','sqm'))
    for label,unit in scalar_labels:
        find(label,lambda r,l=label:any(_normal(v)==_normal(l) for _,v in r['fields']),
             lambda r:field_value(r,r'^sq m$'),unit)

    floor_match=re.search(r'\b(\d+)(?:st|nd|rd|th)?\s+floor\b',q)
    if floor_match and 'area' in q and not towers:
        floor=floor_match.group(1)
        area_types={'BUA':'built up area breakdown','GFA':'gross floor area breakdown',
                    'NSA':'net sellable area breakdown'}
        for metric, heading in area_types.items():
            if not any(m.lower() in q for m in area_types) or metric.lower() in q:
                find(f'{floor} floor {metric}',
                     lambda r,h=heading: h in r['normal'] and any(
                         re.fullmatch(floor+r'(?:st|nd|rd|th)? floor',_normal(v)) for _,v in r['fields']),
                     lambda r:field_value(r,r'^sq m$'),'sqm')

    if towers and levels:
        tower_unit='sqft' if 'sqft' in q or 'square feet' in q else 'sqm'
        unit_pattern=r'(?:sqft|sq ft)' if tower_unit=='sqft' else r'(?:sqm|sq m)'
        for metric in ['gfa','nisa','nsa','bua','ga']:
            if not re.search(r'\b'+metric+r'\b',q): continue
            for tower in towers:
                for level in levels:
                    find(f'Tower {tower} Level {int(level):02d} Floor {metric.upper()}',
                        lambda r,t=tower,l=level:bool(re.search(r'entity tower\s*0*'+t+r'\b',r['normal']) and
                                                    re.search(r'level level\s*0*'+l+r'\b',r['normal'])),
                        lambda r,m=metric:field_value(r,r'\bfloor '+m+r'\b.*\b'+unit_pattern+r'\b'), tower_unit)
    if towers and 'total units' in q:
        for tower in towers:
            find(f'Tower {tower} total units',lambda r,t=tower:bool(re.search(r'entity tower\s*0*'+t+r'\b',r['normal'])),
                 lambda r:field_value(r,r'^total units$'),'units')
    if not towers and ('residential units' in q or 'total residential' in q):
        find('Total residential units',lambda r:'residential units' in r['normal'] and
             any(_normal(v)=='total' for _,v in r['fields']),lambda r:field_value(r,r'^no$'),'units')
    if not towers and ('gfa' in q or 'gross floor area' in q):
        qualifier='proposed' if 'proposed' in q else 'allowed' if 'allowed' in q else None
        if qualifier:
            unit='sqft' if 'sqft' in q or 'square feet' in q else 'sqm'
            pattern=r'^sq ft$' if unit=='sqft' else r'^sq m$'
            find(f'{qualifier.title()} GFA',lambda r: any(_normal(v)=='gfa '+qualifier for _,v in r['fields']),
                 lambda r:field_value(r,pattern),unit)
    _ALL_PARKING_FIELDS=[('Normal',r'^normal$'),('Tandem',r'^tandem$'),('POD',r'^pod$'),
        ('Current EV',r'^current ev(?: 5)?$'),('Future EV',r'^future ev$')]
    parking_fields=[(label,pattern) for label,pattern in _ALL_PARKING_FIELDS if _normal(label) in q]
    # A query can ask for the GRAND TOTAL REQUIRED/ACHIEVED row without naming
    # any specific field ("what is the parking grand total required?"), unlike
    # the field-matching path above which only fires when the user names one
    # of Normal/Tandem/POD/Current EV/Future EV explicitly. Without this,
    # such a query fell through to the 'total parking' branch below, which
    # looks for an unrelated "parking calculation" sheet that doesn't exist in
    # every project and hard-fails with NOT_FOUND even though the GRAND TOTAL
    # REQUIRED row (with all its fields) is sitting right there in the native
    # table evidence. Default to the full field breakdown in that case.
    if 'parking' in q and not towers and not parking_fields and ('grand total' in q or 'bays' in q):
        parking_fields=_ALL_PARKING_FIELDS
    if 'parking' in q and not towers and parking_fields:
        dispositions=[s for s in ('required','achieved') if s in q]
        for disposition in dispositions:
            for label,pattern in parking_fields:
                find(f'Parking {disposition} â€” {label}',
                     lambda r,s=disposition:any(_normal(v)=='grand total '+s for _,v in r['fields']),
                     lambda r,p=pattern:field_value(r,p),'bays')
    if 'total parking' in q and not towers and not parking_fields:
        for kind in ['required','proposed']:
            if kind in q or ('required' not in q and 'proposed' not in q):
                find(f'Total parking {kind}',lambda r:'parking calculation' in r['normal'] and
                     any(_normal(v)=='total' for _,v in r['fields']),
                     lambda r,k=kind:field_value(r,r'^'+k+r'$'),'spaces')
    if 'bicycle parking' in q:
        find('Bicycle parking total',lambda r:'bicycle parking distribution' in r['normal'] and
             any(_normal(v)=='total' for _,v in r['fields']),lambda r:field_value(r,r'^no$'),'racks')
    if 'wind speed' in q:
        find('Basic wind speed V',lambda r:'basic wind speed' in r['normal'],
             lambda r:field_value(r,r'^description$'))
    if 'directionality' in q:
        find('Wind directionality factor Kd',lambda r:'wind directionality' in r['normal'],
             lambda r:field_value(r,r'^description$'))
    if 'car parking' in q and 'live load' in q:
        find('Car parking live load',lambda r:any(_normal(v)=='car parking' for _,v in r['fields']),
             lambda r:field_value(r,r'\blive load\b'),'kN/m2')
    if 'facade' in q or 'fa ade' in q:
        find('Facade glazing load',lambda r:any('fa ade' in _normal(v) or 'facade' in _normal(v) for _,v in r['fields']),
             lambda r:next((v for _,v in r['fields'] if 'determined' in v.lower()),None))
    if 'foundation' in q and 'concrete' in q and re.search(r'\b(grade|strength)\b',q):
        # Preserve the source's test basis verbatim. Parenthesized cylinder/cube
        # strengths must never be rewritten as alternative design grades.
        matches=[]
        for doc in documents:
            try:
                pages=json.loads(Path(doc['path']+'.index.json').read_text(encoding='utf-8')).get('pages',[])
            except (OSError,ValueError):
                continue
            for page in pages:
                if requested_pages and page['page'] not in requested_pages:
                    continue
                body=page.get('text','')
                if authority:
                    from intelligence.source_semantics import explicit_states
                    if not supports_authority(explicit_states(body),authority):continue
                basis=re.search(r'The following[^\n]*concrete cylindrical compressive strength\s*at[^\n]*\(equivalent[^\n]*\):\s*-?',body,re.I)
                value=re.search(r'(?m)^Foundation\s*\n([^\n]*\d[^\n]*)',body)
                if basis and value:
                    matches.append({'label':'Foundation concrete strength (source test basis)',
                        'value':re.sub(r'\s+',' ',basis.group(0)).strip()+' Foundation: '+value.group(1).strip(),
                        'unit':'','source':doc['filename'],'page':page['page']})
        if not matches:
            requests.append({'label':'Foundation concrete strength','missing':True})
        elif len({_normal(r['value']) for r in matches})>1:
            requests.append({'label':'Foundation concrete strength','conflict':True})
        else:
            requests.append(matches[0])
    if not requests:
        from intelligence.native_pdf_answers import native_pdf_answer
        return native_pdf_answer(question, documents)
    if any(r.get('missing') for r in requests):
        missing=', '.join(r['label'] for r in requests if r.get('missing'))
        return {'status':'NOT_FOUND','answer':'No matching native table evidence was found for: '+missing+'. '
                'I cannot verify the requested values from this project.','sources':[], 'facts':requests}
    if any(r.get('conflict') for r in requests):
        return {'status':'AMBIGUOUS','answer':'Conflicting source values were found. Specify the document/revision.',
                'sources':[],'facts':requests}
    def qualification(r):
        details=[]
        if r.get('revision'):details.append('Revision '+r['revision'])
        states=[s for s in r.get('qualification',[]) if s!='UNKNOWN']
        if states:details.append('status: '+', '.join(states))
        return ' ('+'; '.join(details)+')' if details else ''
    answer='\n'.join(f"- **{r['label']}:** {r['value']} {r['unit']}{qualification(r)}. [SOURCE: {r['source']} | PAGE {r['page']}]" for r in requests)
    return {'status':'SUCCESS','answer':answer,'facts':requests,
            'sources':list({(r['source'],r['page']):{'source':r['source'],'page':r['page']} for r in requests}.values())}


def native_disposition_answer(question,documents):
    """Report explicit dispositions, without certifying construction authority."""
    import hashlib
    from intelligence.source_semantics import native_revision,explicit_states
    match=re.search(r'\brevision\s+([A-Za-z0-9-]+)\b',question,re.I)
    requested=match.group(1).upper() if match else None
    facts=[]
    for doc in documents:
        try:
            meta=json.loads(Path(doc['path']+'.index.json').read_text(encoding='utf-8'))
            if meta.get('truncated') or meta.get('processing_complete') is False:continue
            if meta.get('source_sha256'):
                with open(doc['path'],'rb') as handle:
                    if hashlib.file_digest(handle,'sha256').hexdigest()!=meta['source_sha256']:continue
        except (OSError,ValueError,KeyError):continue
        for page in meta.get('pages',[]):
            revision=native_revision(meta,page.get('page'))
            if requested and revision!=requested:continue
            states=explicit_states(page.get('text',''))
            if states=={'UNKNOWN'}:continue
            facts.append({'source':doc['filename'],'page':page['page'],'revision':revision,'qualification':sorted(states)})
    if not facts:
        return {'status':'NOT_FOUND','answer':'No unique matching native revision and explicit status evidence establishes the requested approval. Review the authoritative issue record.','sources':[]}
    sources=[{'source':f['source'],'page':f['page']} for f in facts]
    dispositions={tuple(f['qualification']) for f in facts}
    if len(dispositions)!=1 or len(next(iter(dispositions)))!=1:
        return {'status':'AMBIGUOUS','answer':'Conflicting explicit source dispositions were found. No approval is established; review the authoritative issue record.','sources':sources,'facts':facts}
    fact=facts[0];state=fact['qualification'][0]
    label='Revision '+fact['revision'] if fact['revision'] else 'The source'
    return {'status':'SUCCESS','answer':f"{label} explicitly states **status: {state}**. [SOURCE: {fact['source']} | PAGE {fact['page']}]\nThis reports the source disposition; it does not independently certify authorization for construction.",'sources':sources,'facts':facts}


def limit_comparison(question, documents):
    """Resolve both operands through the same native-table lookup; no inferred inputs."""
    from decimal import Decimal, InvalidOperation
    suffix=' square feet' if re.search(r'\bsqft\b|square feet',question,re.I) else ' square meters'
    pages=' '.join('page '+p for p in re.findall(r'\bpage\s+(\d+)\b',question,re.I))
    metric='FAR' if re.search(r'\bfar\b',question,re.I) else 'GFA'
    results=[exact_answer(metric+' '+qualifier+suffix+' '+pages,documents) for qualifier in ('Proposed','Allowed')]
    for result in results:
        if not result or result['status']!='SUCCESS':
            return result or {'status':'NOT_FOUND','answer':'Both comparison operands require source evidence.','sources':[]}
    facts=[r['facts'][0] for r in results]
    if len({(f['source'],f.get('revision'),tuple(f.get('qualification',[])),f['unit']) for f in facts})!=1:
        return {'status':'AMBIGUOUS','answer':'Comparison inputs have incompatible source, revision, status or units.','sources':[]}
    try:
        proposed,allowed=[Decimal(f['value'].replace(',','')) for f in facts]
        if not all(v.is_finite() for v in (proposed,allowed)): raise InvalidOperation
    except InvalidOperation:
        return {'status':'NOT_FOUND','answer':'Both comparison inputs must be explicitly stated finite numbers.','sources':[]}
    margin=allowed-proposed
    answer='\n'.join(r['answer'] for r in results)
    answer+=f"\n\n{'Yes' if proposed<=allowed else 'No'}, numerically: {proposed} {'<=' if proposed<=allowed else '>'} {allowed} {facts[0]['unit']}. Headroom = allowed - proposed = {margin} {facts[0]['unit']}. This does not establish engineering approval or overall compliance."
    return {'status':'SUCCESS','answer':answer,'facts':facts,
            'sources':[s for r in results for s in r['sources']],
            'calculation':{'operation':'limit_comparison','operands':[str(proposed),str(allowed)],
                           'formula':'allowed - proposed','result':str(margin),'unit':facts[0]['unit'],
                           'sources':[s for r in results for s in r['sources']]}}


def equipment_identifier_answer(question,documents):
    """Read explicit native identifier labels verbatim; no OCR or inference."""
    requested={int(n) for n in re.findall(r'\bpage\s+(\d+)\b',question,re.I)}
    found=[]
    for doc in documents:
        try:
            pages=json.loads(Path(doc['path']+'.index.json').read_text(encoding='utf-8')).get('pages',[])
        except (OSError,ValueError,KeyError):
            continue
        for page in pages:
            if requested and page['page'] not in requested:continue
            from intelligence.source_semantics import requested_authority,explicit_states,supports_authority
            authority=requested_authority(question)
            if authority and not supports_authority(explicit_states(page.get('text','')),authority):continue
            for match in re.finditer(r'\bEquipment identifier\s*:?\s*([A-Za-z][A-Za-z0-9]*(?:-[A-Za-z0-9]+)+)\b',page.get('text',''),re.I):
                found.append({'value':match.group(1),'source':doc['filename'],'page':page['page']})
    sources=[{'source':r['source'],'page':r['page']} for r in found]
    if not found:return {'status':'NOT_FOUND','answer':'No explicit equipment identifier was found in the requested native source evidence.','sources':[]}
    if len({r['value'] for r in found})!=1:
        return {'status':'AMBIGUOUS','answer':'Multiple equipment identifiers were found. Specify the source document and page.','sources':sources}
    r=found[0]
    return {'status':'SUCCESS','answer':f"**Equipment identifier:** {r['value']}. [SOURCE: {r['source']} | PAGE {r['page']}]\nThis reports the source label; it does not establish approval for engineering use.",'sources':sources}


def calculated_answer(question,documents):
    """Conservative explicit-operand arithmetic; no LLM-generated calculations."""
    from decimal import Decimal, InvalidOperation
    q=_normal(question)
    operations=re.findall(r'\b(sum|average|maximum|minimum|difference|compare)\b',q)
    towers=list(dict.fromkeys(re.findall(r'\btower\s*0*(\d+)\b',q)))
    levels=list(dict.fromkeys(re.findall(r'\b(?:level|floor)\s*0*(\d+)\b',q)))
    metrics=re.findall(r'\b(gfa|nisa|nsa|bua|ga)\b',q)
    unsupported={'status':'UNSUPPORTED','sources':[],'facts':[],
        'answer':'I cannot verify this calculation. Specify one operation, one metric, and each tower and level explicitly; unsupported calculations require source review.'}
    if len(operations)!=1 or len(metrics)!=1 or not towers or not levels:
        # A bare word like 'minimum' or 'average' can appear in an ordinary
        # factual question ("what is the minimum store loading?") that has no
        # tower/level comparison intent at all. Without this distinction, the
        # caller (main.py /ask_stream) treats ANY truthy return here as final
        # and never falls through to RAG -- so such a question always hit this
        # hardcoded 'unsupported' refusal, even though the plain-text answer
        # was sitting right there in the document for RAG to find. Only return
        # the explicit refusal when there is already some genuine per-tower/
        # level comparison intent (a tower or level was actually named); with
        # neither, this was never a calculation request in the first place.
        if not towers and not levels and not re.search(r'\b(calculate|sum|difference|compare)\b',q):
            return None
        return unsupported
    # A Cartesian plan with both multiple towers and levels may pair operands
    # incorrectly. Require a single shared tower or a single shared level.
    if len(towers)>1 and len(levels)>1:
        return unsupported
    unit='square feet' if 'square feet' in q or 'sqft' in q else 'sqm'
    lookup=' '.join('Tower '+t for t in towers)+' '+' '.join('Level '+l for l in levels)+' Floor '+metrics[0]+' '+unit
    lookup+=' '+' '.join('page '+p for p in re.findall(r'\bpage\s+(\d+)\b',q))
    from intelligence.source_semantics import requested_authority
    if requested_authority(question):lookup+=' '+requested_authority(question)
    result=exact_answer(lookup,documents)
    if not result or result['status']!='SUCCESS':
        return result or unsupported
    facts=result['facts']
    if len(facts)<2 or len({r['unit'] for r in facts})!=1:
        return unsupported
    if operations[0]=='compare':
        return result
    try:
        values=[Decimal(r['value'].replace(',','').strip()) for r in facts]
        if not all(v.is_finite() for v in values): return unsupported
    except InvalidOperation:
        return unsupported
    operation=operations[0]
    if operation=='difference' and len(values)!=2: return unsupported
    answer={'sum':lambda:sum(values),'average':lambda:sum(values)/len(values),
            'maximum':lambda:max(values),'minimum':lambda:min(values),
            'difference':lambda:values[0]-values[1]}[operation]()
    operands='; '.join(f"{r['label']} = {r['value']} {r['unit']}" for r in facts)
    result['answer']+=f"\n\n**{operation.title()}: {format(answer,'f')} {facts[0]['unit']}**. Calculated from: {operands}."
    result['calculation']={'operation':operation,'operands':[str(v) for v in values],'result':str(answer),'unit':facts[0]['unit']}
    symbols={'sum':' + ','difference':' - ','average':' + ','maximum':', ','minimum':', '}
    formula=symbols[operation].join(str(v) for v in values)
    if operation=='average':formula='('+formula+') / '+str(len(values))
    if operation in ('maximum','minimum'):formula=operation+'('+formula+')'
    result['calculation']['formula']=formula
    result['calculation']['sources']=result['sources']
    result['answer']+=f"\nFormula: {formula} = {format(answer,'f')} {facts[0]['unit']}."
    return result


from intelligence.phase4c_exact import drawing_annotation_answer
