from selenium import webdriver
from selenium.webdriver.common.action_chains import ActionChains
import time
import auth
import urllib.parse

def run():
    token = auth.make_token({"id": 1, "username": "system", "role": "admin"})
    
    options = webdriver.ChromeOptions()
    options.add_argument('--headless')
    options.set_capability('goog:loggingPrefs', {'browser': 'ALL'})
    
    driver = webdriver.Chrome(options=options)
    
    proj = urllib.parse.quote("C3085 - 3EH -Expo Hills")
    rel = urllib.parse.quote("C3085-MDL-3EH6117-AR-0000001.ifc")
    url = f"http://127.0.0.1:8090/ui/viewer.html?v=11&project={proj}&rel={rel}&token={token}"
    driver.get(url)
    
    print("Waiting for model to load...")
    time.sleep(20)
    
    actions = ActionChains(driver)
    actions.move_by_offset(300, 300).click().perform()
    time.sleep(5)
    
    try:
        data = driver.execute_script("""
            if(typeof activeModel === 'undefined' || !activeModel) return null;
            return {
               hasRaycast: typeof activeModel.raycast === 'function',
               hasData: !!activeModel.data,
               hasDataMeshes: activeModel.data && typeof activeModel.data.meshes === 'function',
               hasDataLocalIds: activeModel.data && typeof activeModel.data.localIds === 'function'
            }
        """)
        print("Data:", data)
    except Exception as e:
        print("Error", e)
        
    logs = driver.get_log('browser')
    for log in logs:
        print(log)
        
    driver.quit()

if __name__ == "__main__":
    run()
