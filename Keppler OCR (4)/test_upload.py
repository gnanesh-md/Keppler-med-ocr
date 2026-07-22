import requests
s = requests.Session()
r = s.post("http://127.0.0.1:7610/api/v1/auth/login", json={"username": "testuser", "password": "password"})
if r.status_code == 401:
    r = s.post("http://127.0.0.1:7610/api/v1/auth/register", json={"username": "testuser", "password": "password"})
    r = s.post("http://127.0.0.1:7610/api/v1/auth/login", json={"username": "testuser", "password": "password"})

token = r.json()["access_token"]
headers = {"Authorization": f"Bearer {token}"}
with open("README.md", "rb") as f:
    res = s.post("http://127.0.0.1:7610/api/v1/ocr/upload", files={"file": f}, data={"client_blueprint": "Universal OCR (Any Text)"}, headers=headers)
    print(res.status_code, res.text)
