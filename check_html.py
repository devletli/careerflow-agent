import requests
r = requests.get('http://localhost:3000/', timeout=10)
# Print first 5000 chars
print(r.text[:5000])