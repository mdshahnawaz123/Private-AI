import fitz
doc=fitz.open(r'data\docs\C3103 - Multi-Story Park\Documents\C3103-RPT-3CP6130-ST-0000001(B).pdf')
from services.pipeline import classify_image
c=0
for p in doc:
  for img in p.get_images(full=True):
    b=doc.extract_image(img[0])
    if classify_image({'width':b['width'], 'height':b['height']}) == 'ENGINEERING_TABLE': c+=1
print('Engineering tables:', c)
