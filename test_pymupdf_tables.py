import fitz

pdf_path = r"C:\3EH\ExpoDesignAI - Copy\data\docs\C3085 - 3EH -Expo Hills\Schedules\C3085-SCH-3EH6105-AR-0000001(5).pdf"
doc = fitz.open(pdf_path)

# Look at page 5 (0-indexed page 4) where Tower 6 is. 
# From audit: [SOURCE: C3085-SCH-3EH6105-AR-0000001(5).pdf | PAGE 5]
# Let's check page 4 and 5.
for p_idx in [3, 4, 5]:
    page = doc[p_idx]
    tabs = page.find_tables()
    print(f"Page {p_idx+1}: {len(tabs.tables)} tables found")
    if len(tabs.tables) > 0:
        t = tabs.tables[0]
        ext = t.extract()
        for i, row in enumerate(ext[:10]):
            print(f"  Row {i}: {row}")
        print("...")
