import time
import requests

def wait_for_server(url: str, timeout: float = 90.0, interval: float = 0.5):

    start = time.time()

    while True:
        try:
            response = requests.get(url, timeout=2)
            if response.status_code == 200:
                return
        except:
            pass

        if time.time() - start > timeout:
            raise TimeoutError(f"Server not ready after {timeout} seconds")

        time.sleep(interval)