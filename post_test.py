import json
import threading
from urllib import request

url = 'http://localhost:8000/api/v1/cart'
data = json.dumps({'guest_token': 'concurrency-test', 'currency': 'ARS'}).encode('utf-8')
headers = {'Content-Type': 'application/json'}

def post():
    req = request.Request(url, data=data, headers=headers, method='POST')
    try:
        with request.urlopen(req) as resp:
            body = resp.read().decode('utf-8')
            print('status', resp.status)
            print(body)
    except Exception as exc:
        print('error', exc)

threads = [threading.Thread(target=post) for _ in range(2)]
for t in threads:
    t.start()
for t in threads:
    t.join()

