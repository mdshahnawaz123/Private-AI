import fitz

pdf_path = r"C:\3EH\ExpoDesignAI - Copy\data\docs\C3085 - 3EH -Expo Hills\Schedules\C3085-SCH-3EH6105-AR-0000001(5).pdf"
doc = fitz.open(pdf_path)

page = doc[4] # page 5
tabs = page.find_tables()
if len(tabs.tables) > 0:
    t = tabs.tables[0]
    ext = t.extract()
    for i, row in enumerate(ext):
        if row[1] == 'TOWER 6' or (row[3] and 'LEVEL 02' in row[3]):
            print(f"Row {i}: {row[:10]}")
