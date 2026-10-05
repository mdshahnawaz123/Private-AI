import sqlite3

def run():
    conn = sqlite3.connect('data/expo.db')
    c = conn.cursor()
    c.execute("SELECT name FROM projects")
    print("Projects:", c.fetchall())
    
    c.execute("SELECT name FROM documents")
    print("Documents:", c.fetchall())
    
    conn.close()

if __name__ == "__main__":
    run()
